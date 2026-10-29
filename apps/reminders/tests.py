"""Phase 3 tests: reminder scheduling, duplicate prevention, reschedule/cancel handling, processing,
notification access and the management command. Test fixtures only.

The clock is frozen with ``frozen(...)`` so results never depend on today's date.
NOW is Mon 2 Nov 2026 08:00 (Africa/Kampala); the default test lecture starts Tue 3 Nov 09:00, i.e. 25 hours later.
"""
from contextlib import contextmanager
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.academics.models import Enrolment, EnrolmentStatus, StudentProfile
from apps.academics.tests import PW, make_user
from apps.accounts.models import AuditLog, Role
from apps.timetables import services as tt
from apps.timetables.models import LectureSession
from apps.timetables.tests import TimetableFixtureMixin, at

from . import channels, services
from .models import (MAX_ATTEMPTS, Notification, NotificationKind, NotificationStatus, ReminderConfig,
                     ReminderInterval, ReminderRun, RunStatus, humanize_minutes)

NOW = at(2, 8, 0)
R, C = NotificationKind.REMINDER, NotificationKind.SCHEDULE_CHANGE
S = NotificationStatus


@contextmanager
def frozen(dt):
    with patch("django.utils.timezone.now", return_value=dt):
        yield


class ReminderBase(TimetableFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Enrolment.objects.create(student=cls.student, offering=cls.offering)
        Enrolment.objects.create(student=cls.student2, offering=cls.offering)
        cls.stu3_user = make_user("stu3", Role.STUDENT)
        cls.student3 = StudentProfile.objects.create(user=cls.stu3_user, registration_number="S003", programme=cls.programme)

    def schedule(self, start=None, end=None, now=NOW):
        session = LectureSession(offering=self.offering, lecturer=self.lecturer, venue=self.venue_a,
                                 start_at=start or at(3, 9), end_at=end or at(3, 11))
        with frozen(now):
            return tt.create_session(session, self.admin)

    def reminders(self, **filters):
        return Notification.objects.filter(kind=R, **filters)

    def process(self, now, **kw):
        return services.process_due_reminders(now=now, **kw)


class SchedulingTests(ReminderBase):
    def test_default_intervals_are_seeded(self):
        self.assertEqual(list(ReminderInterval.objects.filter(is_active=True).values_list("minutes_before", flat=True)),
                         [1440, 60, 15])
        self.assertTrue(ReminderConfig.get().reminders_enabled)

    def test_humanize_minutes(self):
        self.assertEqual([humanize_minutes(m) for m in (1440, 60, 15, 90, 1)],
                         ["24 hours", "1 hour", "15 minutes", "90 minutes", "1 minute"])

    def test_new_lecture_schedules_reminders_for_enrolled_students_only(self):
        session = self.schedule()
        rows = self.reminders(session=session)
        self.assertEqual(rows.count(), 6)  # 2 enrolled students x 3 intervals
        self.assertEqual(set(rows.values_list("recipient__username", flat=True)), {"stu1", "stu2"})
        self.assertFalse(rows.exclude(status=S.PENDING).exists())
        row = rows.get(recipient=self.stu_user, minutes_before=1440)
        self.assertEqual(row.scheduled_for, at(2, 9, 0))
        self.assertEqual(rows.get(recipient=self.stu_user, minutes_before=15).scheduled_for, at(3, 8, 45))
        self.assertTrue(row.title and row.message and row.created_at)

    def test_reminder_times_already_passed_are_not_created(self):
        session = self.schedule(now=at(3, 8, 30))  # lecture at 09:00 is 30 minutes away
        rows = self.reminders(session=session)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(set(rows.values_list("minutes_before", flat=True)), {15})

    def test_resync_creates_no_duplicates(self):
        session = self.schedule()
        with frozen(NOW):
            again = services.sync_session_reminders(session)
            services.sync_upcoming()
        self.assertEqual(again["created"], 0)
        self.assertEqual(self.reminders(session=session).count(), 6)

    def test_database_constraint_rejects_duplicate(self):
        session = self.schedule()
        row = self.reminders(session=session).first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Notification.objects.create(recipient=row.recipient, session=session, kind=R, interval=row.interval,
                                        title="dup", message="dup", scheduled_for=row.scheduled_for)

    def test_withdrawn_and_inactive_recipients_are_dropped_on_sync(self):
        session = self.schedule()
        Enrolment.objects.filter(student=self.student2).update(status=EnrolmentStatus.WITHDRAWN)
        with frozen(NOW):
            services.sync_upcoming()
        gone = self.reminders(session=session, recipient=self.stu2_user)
        self.assertEqual(set(gone.values_list("status", flat=True)), {S.CANCELLED})
        self.assertIn("no longer eligible", gone.first().status_detail)
        self.assertEqual(self.reminders(session=session, recipient=self.stu_user, status=S.PENDING).count(), 3)
        self.stu_user.is_active = False
        self.stu_user.save()
        with frozen(NOW):
            services.sync_upcoming()
        self.assertFalse(self.reminders(session=session, status=S.PENDING).exists())

    def test_late_enrolment_is_picked_up_by_sync(self):
        session = self.schedule()
        Enrolment.objects.create(student=self.student3, offering=self.offering)
        with frozen(NOW):
            stats = services.sync_upcoming()
        self.assertEqual(stats["created"], 3)
        self.assertEqual(self.reminders(session=session, recipient=self.stu3_user).count(), 3)

    def test_lectures_created_before_reminders_existed_are_scheduled_by_sync(self):
        session = self.make_session(start=at(3, 9), end=at(3, 11))  # no signal fired: simulates Phase 2 data
        self.assertFalse(self.reminders(session=session).exists())
        run = self.process(NOW)
        self.assertEqual(run.sync_created, 6)
        self.assertEqual(self.reminders(session=session).count(), 6)

    def test_interval_edits_apply_to_pending_reminders(self):
        session = self.schedule()
        ReminderInterval.objects.filter(minutes_before=60).update(minutes_before=90)
        ReminderInterval.objects.filter(minutes_before=15).update(is_active=False)
        extra = ReminderInterval.objects.create(minutes_before=30)
        with frozen(NOW):
            services.sync_upcoming()
        moved = self.reminders(session=session, recipient=self.stu_user, interval__minutes_before=90).get()
        self.assertEqual(moved.scheduled_for, at(3, 7, 30))
        self.assertEqual(moved.minutes_before, 90)
        off = self.reminders(session=session, minutes_before=15)
        self.assertEqual(set(off.values_list("status", flat=True)), {S.CANCELLED})
        self.assertIn("inactive", off.first().status_detail)
        self.assertEqual(self.reminders(session=session, interval=extra, status=S.PENDING).count(), 2)

    def test_recipient_filter_hook_excludes_reminders_but_not_change_notices(self):
        def exclude_student2(qs, session):
            return qs.exclude(pk=self.student2.pk)
        services.register_recipient_filter(exclude_student2)
        self.addCleanup(services.unregister_recipient_filter, exclude_student2)
        session = self.schedule()
        self.assertEqual(set(self.reminders(session=session).values_list("recipient__username", flat=True)), {"stu1"})
        with frozen(NOW):
            tt.cancel_session(session, self.admin, reason="Lecturer unwell")
        notices = Notification.objects.filter(kind=C, session=session)
        self.assertEqual(set(notices.values_list("recipient__username", flat=True)), {"stu1", "stu2"})


class RescheduleAndCancelTests(ReminderBase):
    def test_reschedule_moves_pending_reminders_and_notifies_students(self):
        session = self.schedule()
        with frozen(NOW):
            tt.reschedule_session(session, self.admin, start=at(4, 14), end=at(4, 16), venue=self.venue_a, reason="Clash")
        rows = self.reminders(session=session)
        self.assertEqual(rows.count(), 6)  # moved in place, not duplicated
        self.assertEqual(rows.get(recipient=self.stu_user, minutes_before=60).scheduled_for, at(4, 13))
        notices = Notification.objects.filter(kind=C, session=session)
        self.assertEqual(notices.count(), 2)
        first = notices.get(recipient=self.stu_user)
        self.assertEqual((first.status, first.read_at), (S.DELIVERED, None))
        self.assertIn("rescheduled", first.title.lower())
        self.assertIn("Clash", first.message)
        self.assertFalse(notices.filter(recipient=self.lec_user).exists())

    def test_reschedule_after_delivery_keeps_history_and_schedules_new_reminders(self):
        session = self.schedule()
        self.process(at(2, 9, 30))  # 24-hour reminders are due and delivered
        self.assertEqual(self.reminders(status=S.DELIVERED).count(), 2)
        with frozen(at(2, 9, 30)):
            tt.reschedule_session(session, self.admin, start=at(5, 10), end=at(5, 12), venue=self.venue_a, reason="Moved")
        old = self.reminders(session=session, superseded=True)
        self.assertEqual(old.count(), 2)
        self.assertEqual(set(old.values_list("status", flat=True)), {S.DELIVERED})
        current = self.reminders(session=session, superseded=False)
        self.assertEqual(current.count(), 6)
        self.assertEqual(set(current.values_list("status", flat=True)), {S.PENDING})
        self.assertEqual(current.get(recipient=self.stu_user, minutes_before=1440).scheduled_for, at(4, 10))

    def test_reschedule_to_a_near_time_cancels_elapsed_reminders_and_later_move_reactivates(self):
        session = self.schedule()
        with frozen(NOW):
            tt.reschedule_session(session, self.admin, start=at(2, 8, 40), end=at(2, 9, 40), venue=self.venue_a, reason="Urgent")
        rows = self.reminders(session=session)
        self.assertEqual(rows.filter(status=S.PENDING).count(), 2)       # only the 15-minute reminders can still fire
        self.assertEqual(set(rows.filter(status=S.PENDING).values_list("minutes_before", flat=True)), {15})
        self.assertEqual(rows.filter(status=S.CANCELLED).count(), 4)
        with frozen(NOW):
            tt.reschedule_session(session, self.admin, start=at(10, 9), end=at(10, 11), venue=self.venue_a, reason="Back to normal")
        self.assertEqual(self.reminders(session=session, status=S.PENDING).count(), 6)
        self.assertEqual(self.reminders(session=session).count(), 6)

    def test_cancel_cancels_pending_notifies_and_keeps_delivered_history(self):
        session = self.schedule()
        self.process(at(2, 9, 30))
        with frozen(at(2, 9, 30)):
            tt.cancel_session(session, self.admin, reason="Lecturer unwell")
        rows = self.reminders(session=session)
        self.assertEqual(rows.filter(status=S.DELIVERED).count(), 2)
        cancelled = rows.filter(status=S.CANCELLED)
        self.assertEqual(cancelled.count(), 4)
        self.assertEqual(cancelled.first().status_detail, "Lecture cancelled.")
        notices = Notification.objects.filter(kind=C, session=session)
        self.assertEqual(notices.count(), 2)
        self.assertIn("cancelled", notices.first().title.lower())
        run = self.process(at(3, 8, 30))
        self.assertEqual(run.delivered, 0)
        self.assertEqual(self.reminders(session=session, status=S.DELIVERED).count(), 2)


class ProcessingTests(ReminderBase):
    def test_only_due_reminders_are_delivered(self):
        session = self.schedule()
        run = self.process(at(3, 8, 30))  # 24h and 1h reminders are due; 15-minute ones (08:45) are not
        self.assertEqual((run.due_found, run.delivered, run.failed, run.status), (4, 4, 0, RunStatus.COMPLETED))
        rows = self.reminders(session=session)
        self.assertEqual(rows.filter(status=S.DELIVERED).count(), 4)
        self.assertEqual(rows.filter(status=S.PENDING).count(), 2)
        done = rows.filter(status=S.DELIVERED).first()
        self.assertEqual((done.delivered_at, done.processed_at), (at(3, 8, 30), at(3, 8, 30)))
        self.assertIn("starts in about 30 minutes", done.title)
        self.assertIn("Hall A", done.message)

    def test_repeated_runs_never_duplicate_or_redeliver(self):
        session = self.schedule()
        first = self.process(at(3, 8, 30))
        total = Notification.objects.count()
        second = self.process(at(3, 8, 30))
        self.assertEqual((first.delivered, second.delivered, second.due_found), (4, 0, 0))
        self.assertEqual(Notification.objects.count(), total)
        third = self.process(at(3, 8, 50))  # the 15-minute reminders become due
        self.assertEqual(third.delivered, 2)
        self.assertEqual(self.reminders(session=session, status=S.DELIVERED).count(), 6)
        self.assertEqual(self.process(at(3, 8, 55)).delivered, 0)

    def test_handled_reminder_is_skipped_if_seen_again(self):
        self.schedule()
        self.process(at(3, 8, 30))
        run = ReminderRun.objects.create(started_at=at(3, 8, 31))
        services._process_one(self.reminders(status=S.DELIVERED).first().pk, at(3, 8, 31), run, channels.get_channels())
        self.assertEqual((run.skipped, run.delivered), (1, 0))

    def test_reminders_that_become_due_after_the_lecture_started_expire(self):
        session = self.schedule()
        run = self.process(at(3, 9, 30))
        self.assertEqual((run.expired, run.delivered), (6, 0))
        self.assertEqual(self.reminders(session=session, status=S.EXPIRED).count(), 6)

    def test_nothing_is_delivered_when_reminders_are_disabled(self):
        self.schedule()
        ReminderConfig.get()
        ReminderConfig.objects.filter(pk=1).update(reminders_enabled=False)
        run = self.process(at(3, 8, 30))
        self.assertEqual((run.status, run.delivered), (RunStatus.DISABLED, 0))
        self.assertFalse(self.reminders(status=S.DELIVERED).exists())
        ReminderConfig.objects.filter(pk=1).update(reminders_enabled=True)
        self.assertEqual(self.process(at(3, 8, 31)).delivered, 4)  # still pending, delivered once re-enabled

    def test_recipient_who_left_the_course_is_not_sent_a_reminder(self):
        self.schedule()
        Enrolment.objects.filter(student=self.student2).update(status=EnrolmentStatus.WITHDRAWN)
        run = self.process(at(3, 8, 30), sync=False)  # processing alone must still protect against stale reminders
        self.assertEqual((run.delivered, run.cancelled), (2, 2))
        self.assertFalse(self.reminders(recipient=self.stu2_user, status=S.DELIVERED).exists())

    def test_deactivated_interval_is_not_delivered(self):
        self.schedule()
        ReminderInterval.objects.filter(minutes_before=1440).update(is_active=False)
        run = self.process(at(3, 8, 30), sync=False)
        self.assertEqual((run.delivered, run.cancelled), (2, 2))

    @patch.object(services.logger, "exception")  # the failure is expected; keep test output clean
    def test_failed_delivery_is_recorded_retried_and_eventually_abandoned(self, _log):
        class Flaky(channels.DeliveryChannel):
            name = "flaky"
            broken = True

            def send(self, notification):
                if self.broken:
                    raise RuntimeError("gateway down")
        Flaky.broken = True
        channels.register_channel(Flaky)
        self.addCleanup(channels.CHANNEL_REGISTRY.pop, "flaky", None)
        self.schedule(now=at(3, 8, 30))  # two 15-minute reminders only
        with override_settings(REMINDER_CHANNELS=["flaky"]):
            run = self.process(at(3, 8, 50))
            self.assertEqual((run.failed, run.delivered, run.status), (2, 0, RunStatus.ERRORS))
            row = self.reminders(status=S.FAILED).first()
            self.assertIn("gateway down", row.status_detail)
            self.assertEqual(row.attempts, 1)
            Flaky.broken = False
            retry = self.process(at(3, 8, 51))  # retried automatically and now succeeds
            self.assertEqual((retry.delivered, retry.failed), (2, 0))
            self.assertEqual(self.reminders(status=S.DELIVERED).count(), 2)

    @patch.object(services.logger, "exception")  # the failure is expected; keep test output clean
    def test_failures_stop_after_max_attempts(self, _log):
        class Dead(channels.DeliveryChannel):
            name = "dead"

            def send(self, notification):
                raise RuntimeError("never works")
        channels.register_channel(Dead)
        self.addCleanup(channels.CHANNEL_REGISTRY.pop, "dead", None)
        self.schedule(now=at(3, 8, 30))
        with override_settings(REMINDER_CHANNELS=["dead"]):
            for minute in range(MAX_ATTEMPTS):
                self.assertEqual(self.process(at(3, 8, 50 + minute)).failed, 2)
            final = self.process(at(3, 8, 55))
        self.assertEqual((final.due_found, final.failed), (0, 0))
        self.assertEqual(self.reminders(status=S.FAILED).first().attempts, MAX_ATTEMPTS)

    def test_unknown_channel_stops_the_run(self):
        self.schedule()
        with override_settings(REMINDER_CHANNELS=["sms"]), self.assertRaises(ImproperlyConfigured):
            self.process(at(3, 8, 30))
        self.assertEqual(ReminderRun.objects.first().status, RunStatus.CRASHED)
        self.assertFalse(self.reminders(status=S.DELIVERED).exists())


class CommandTests(ReminderBase):
    def run_command(self, now, *args):
        out = StringIO()
        with frozen(now):
            call_command("process_reminders", *args, stdout=out)
        return out.getvalue()

    def test_command_delivers_and_reports(self):
        self.schedule()
        output = self.run_command(at(3, 8, 30))
        self.assertIn("delivered: 4", output)
        self.assertIn("in-app", output)
        self.assertEqual(ReminderRun.objects.count(), 1)
        self.assertEqual(ReminderRun.objects.get().trigger, "command")

    def test_command_is_safe_to_repeat(self):
        self.schedule()
        self.run_command(at(3, 8, 30))
        count = Notification.objects.count()
        output = self.run_command(at(3, 8, 31))
        self.assertIn("delivered: 0", output)
        self.assertEqual(Notification.objects.count(), count)

    def test_dry_run_changes_nothing(self):
        self.schedule()
        output = self.run_command(at(3, 8, 30), "--dry-run")
        self.assertIn("due now: 4", output)
        self.assertFalse(self.reminders(status=S.DELIVERED).exists())
        self.assertEqual(ReminderRun.objects.count(), 0)

    @patch.object(services.logger, "exception")  # the failure is expected; keep test output clean
    def test_command_exits_with_error_when_a_delivery_fails(self, _log):
        class Bad(channels.DeliveryChannel):
            name = "bad"

            def send(self, notification):
                raise RuntimeError("boom")
        channels.register_channel(Bad)
        self.addCleanup(channels.CHANNEL_REGISTRY.pop, "bad", None)
        self.schedule()
        with override_settings(REMINDER_CHANNELS=["bad"]), self.assertRaises(CommandError):
            self.run_command(at(3, 8, 30))


class InboxAndViewTests(ReminderBase):
    def deliver(self):
        session = self.schedule()
        self.process(at(3, 8, 30))
        return session

    def login(self, user):
        self.client.login(username=user.username, password=PW)

    def test_student_sees_only_own_delivered_notifications(self):
        self.deliver()
        self.login(self.stu_user)
        response = self.client.get(reverse("reminders:notifications"))
        shown = list(response.context["notifications"])
        self.assertEqual(len(shown), 2)  # 24h and 1h delivered; the pending 15-minute one is hidden
        self.assertTrue(all(n.recipient_id == self.stu_user.pk and n.status == S.DELIVERED for n in shown))
        self.assertContains(response, "Lecture reminder: BIT101")
        self.login(self.stu3_user)  # enrolled in nothing
        self.assertEqual(len(self.client.get(reverse("reminders:notifications")).context["notifications"]), 0)

    def test_mark_read_and_unread_count(self):
        self.deliver()
        self.login(self.stu_user)
        self.assertEqual(self.client.get(reverse("reminders:unread_count")).json(), {"unread": 2})
        n = services.inbox_for(self.stu_user).first()
        self.client.post(reverse("reminders:mark_read", args=[n.pk]))
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)
        self.assertEqual(self.client.get(reverse("reminders:unread_count")).json(), {"unread": 1})
        response = self.client.get(reverse("reminders:notifications") + "?show=unread")
        self.assertEqual(len(response.context["notifications"]), 1)
        self.client.post(reverse("reminders:mark_all_read"))
        self.assertEqual(services.unread_count(self.stu_user), 0)

    def test_student_cannot_read_or_mark_another_students_notification(self):
        self.deliver()
        theirs = services.inbox_for(self.stu2_user).first()
        self.login(self.stu_user)
        self.assertEqual(self.client.post(reverse("reminders:mark_read", args=[theirs.pk])).status_code, 404)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)
        self.client.post(reverse("reminders:mark_all_read"))
        self.assertEqual(services.unread_count(self.stu2_user), 2)

    def test_pending_notification_cannot_be_marked_read(self):
        self.deliver()
        pending = self.reminders(recipient=self.stu_user, status=S.PENDING).first()
        self.login(self.stu_user)
        self.assertEqual(self.client.post(reverse("reminders:mark_read", args=[pending.pk])).status_code, 404)

    def test_mark_read_requires_post_and_login_and_ignores_unsafe_next(self):
        self.deliver()
        n = services.inbox_for(self.stu_user).first()
        url = reverse("reminders:mark_read", args=[n.pk])
        self.assertEqual(self.client.post(url).status_code, 302)          # anonymous: sent to login
        self.assertIn("login", self.client.post(url)["Location"])
        self.login(self.stu_user)
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, {"next": "https://evil.example/steal"})
        self.assertEqual(response["Location"], reverse("reminders:notifications"))

    def test_unread_endpoint_requires_login(self):
        self.assertEqual(self.client.get(reverse("reminders:unread_count")).status_code, 302)

    def test_student_dashboard_and_navigation_show_unread_count(self):
        self.deliver()
        self.login(self.stu_user)
        response = self.client.get(reverse("accounts:dashboard_student"))
        self.assertEqual(response.context["unread_count"], 2)
        self.assertContains(response, "Unread notifications")
        self.assertContains(response, 'data-unread-url="')

    def test_lecturer_notification_page_is_empty_not_an_error(self):
        self.deliver()
        self.login(self.lec_user)
        response = self.client.get(reverse("reminders:notifications"))
        self.assertEqual((response.status_code, len(response.context["notifications"])), (200, 0))

    def test_rescheduled_reminder_is_marked_as_old_time(self):
        session = self.deliver()
        with frozen(at(3, 8, 30)):
            tt.reschedule_session(session, self.admin, start=at(6, 9), end=at(6, 11), venue=self.venue_a, reason="Moved")
        self.login(self.stu_user)
        response = self.client.get(reverse("reminders:notifications"))
        self.assertContains(response, "Old time: lecture was rescheduled")
        self.assertContains(response, "Schedule change")


class AdminViewTests(ReminderBase):
    ADMIN_URLS = ["reminders:overview", "reminders:queue", "reminders:run_list", "reminders:config_edit", "reminders:interval_add"]

    def test_only_administrators_open_reminder_management(self):
        for name in self.ADMIN_URLS:
            url = reverse(name)
            self.assertEqual(self.client.get(url).status_code, 302, name)
            for user in (self.stu_user, self.lec_user, self.researcher):
                self.client.login(username=user.username, password=PW)
                self.assertEqual(self.client.get(url).status_code, 403, (name, user.username))
            self.client.login(username=self.admin.username, password=PW)
            self.assertEqual(self.client.get(url).status_code, 200, name)
            self.client.logout()

    def test_run_now_processes_and_is_audited(self):
        self.client.login(username=self.admin.username, password=PW)
        self.assertEqual(self.client.get(reverse("reminders:run_now")).status_code, 405)
        response = self.client.post(reverse("reminders:run_now"), follow=True)
        run = ReminderRun.objects.get()
        self.assertEqual((run.trigger, run.triggered_by), ("admin", self.admin))
        self.assertTrue(AuditLog.objects.filter(action="reminders_processed", actor=self.admin).exists())
        self.assertContains(response, "Processed")

    def test_non_admin_cannot_run_processing(self):
        self.client.login(username=self.stu_user.username, password=PW)
        self.assertEqual(self.client.post(reverse("reminders:run_now")).status_code, 403)
        self.assertEqual(ReminderRun.objects.count(), 0)

    def test_admin_can_add_and_edit_intervals_with_validation(self):
        self.client.login(username=self.admin.username, password=PW)
        add = reverse("reminders:interval_add")
        self.client.post(add, {"minutes_before": 120, "label": "", "is_active": "on"})
        interval = ReminderInterval.objects.get(minutes_before=120)
        self.assertEqual(interval.display, "2 hours before")
        self.assertTrue(AuditLog.objects.filter(action="reminder_interval_created").exists())
        for bad in ("60", "0", "10081", ""):  # duplicate, too small, too large, empty
            response = self.client.post(add, {"minutes_before": bad, "is_active": "on"})
            self.assertEqual(response.status_code, 200, bad)
            self.assertTrue(response.context["form"].errors, bad)
        self.client.post(reverse("reminders:interval_edit", args=[interval.pk]), {"minutes_before": 120, "label": "Two hours"})
        interval.refresh_from_db()
        self.assertEqual((interval.label, interval.is_active), ("Two hours", False))

    def test_admin_can_switch_reminders_off(self):
        self.client.login(username=self.admin.username, password=PW)
        self.client.post(reverse("reminders:config_edit"), {})  # unticked checkbox = off
        config = ReminderConfig.get()
        self.assertFalse(config.reminders_enabled)
        self.assertEqual(config.updated_by, self.admin)
        self.assertTrue(AuditLog.objects.filter(action="reminder_settings_updated").exists())
        self.assertContains(self.client.get(reverse("reminders:overview")), "switched off")

    def test_queue_search_and_filters(self):
        self.schedule()
        self.process(at(3, 8, 30))
        self.client.login(username=self.admin.username, password=PW)
        url = reverse("reminders:queue")
        self.assertEqual(self.client.get(url).context["paginator"].count, 6)
        self.assertEqual(self.client.get(url, {"status": "delivered"}).context["paginator"].count, 4)
        self.assertEqual(self.client.get(url, {"q": "stu2"}).context["paginator"].count, 3)
        self.assertEqual(self.client.get(url, {"q": "NOPE999"}).context["paginator"].count, 0)

    def test_session_detail_shows_reminder_summary_to_lecturer_of_that_course_only(self):
        session = self.schedule()
        self.client.login(username=self.lec_user.username, password=PW)
        response = self.client.get(reverse("timetables:session_detail", args=[session.pk]))
        self.assertContains(response, "Reminders for this lecture")
        self.assertEqual(response.context["reminder_summary"]["Pending"], 6)
        self.client.login(username=self.lec2_user.username, password=PW)
        self.assertEqual(self.client.get(reverse("timetables:session_detail", args=[session.pk])).status_code, 404)
