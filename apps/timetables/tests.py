"""Phase 2 tests: venues, lecture scheduling, conflicts, rescheduling, cancelling, timetables.
All data below is synthetic test fixture data."""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Enrolment
from apps.academics.tests import AcademicFixtureMixin, PW
from apps.accounts.models import AuditLog

from . import services
from .models import ChangeType, LectureChange, LectureSession, SessionStatus, Venue
from .signals import lecture_changed


def at(day, hour, minute=0):
    """Aware datetime in Africa/Kampala on 2026-11-<day>."""
    return timezone.make_aware(datetime(2026, 11, day, hour, minute))


class TimetableFixtureMixin(AcademicFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.venue_a = Venue.objects.create(name="Hall A", building="Main", capacity=100)
        cls.venue_b = Venue.objects.create(name="Lab 1", building="ICT", capacity=40)

    def make_session(self, offering=None, lecturer=None, venue=None, start=None, end=None, **kw):
        offering = offering or self.offering
        lecturer = lecturer or offering.lecturers.first()
        return LectureSession.objects.create(offering=offering, lecturer=lecturer, venue=venue or self.venue_a,
                                             start_at=start or at(10, 9), end_at=end or at(10, 11), **kw)


class ConflictTests(TimetableFixtureMixin, TestCase):
    def conflicts(self, **over):
        args = dict(offering=self.offering, lecturer=self.lecturer, venue=self.venue_b, start=at(10, 10), end=at(10, 12))
        args.update(over)
        return services.find_conflicts(**args)

    def test_no_conflict_on_empty_timetable(self):
        self.assertEqual(self.conflicts(), [])

    def test_lecturer_conflict(self):
        self.make_session()
        msgs = self.conflicts(offering=self.offering, venue=self.venue_b)
        self.assertTrue(any(m.startswith("Lecturer conflict") for m in msgs), msgs)

    def test_venue_conflict(self):
        self.make_session()
        msgs = self.conflicts(offering=self.offering2, lecturer=self.lecturer2, venue=self.venue_a)
        self.assertEqual([m.split(":")[0] for m in msgs], ["Venue conflict"])

    def test_same_offering_conflict(self):
        self.offering.lecturers.add(self.lecturer2)
        self.make_session()
        msgs = self.conflicts(lecturer=self.lecturer2, venue=self.venue_b)
        self.assertEqual([m.split(":")[0] for m in msgs], ["Timetable conflict"])

    def test_shared_student_conflict(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        Enrolment.objects.create(student=self.student, offering=self.offering2)
        Enrolment.objects.create(student=self.student2, offering=self.offering2)
        self.make_session()
        msgs = self.conflicts(offering=self.offering2, lecturer=self.lecturer2, venue=self.venue_b)
        self.assertEqual(len(msgs), 1)
        self.assertIn("1 enrolled student(s)", msgs[0])

    def test_no_student_conflict_without_shared_students(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        Enrolment.objects.create(student=self.student2, offering=self.offering2)
        self.make_session()
        self.assertEqual(self.conflicts(offering=self.offering2, lecturer=self.lecturer2, venue=self.venue_b), [])

    def test_back_to_back_lectures_allowed(self):
        self.make_session(start=at(10, 9), end=at(10, 11))
        self.assertEqual(self.conflicts(venue=self.venue_a, start=at(10, 11), end=at(10, 13)), [])
        self.assertEqual(self.conflicts(venue=self.venue_a, start=at(10, 7), end=at(10, 9)), [])

    def test_partial_and_containing_overlaps_detected(self):
        self.make_session(start=at(10, 9), end=at(10, 11))
        for start, end in [(at(10, 8), at(10, 10)), (at(10, 10), at(10, 12)), (at(10, 9, 30), at(10, 10)), (at(10, 8), at(10, 12))]:
            self.assertTrue(self.conflicts(venue=self.venue_a, start=start, end=end), (start, end))

    def test_cancelled_lectures_do_not_conflict(self):
        self.make_session(status=SessionStatus.CANCELLED)
        self.assertEqual(self.conflicts(venue=self.venue_a), [])

    def test_exclude_own_pk(self):
        s = self.make_session()
        self.assertEqual(self.conflicts(venue=self.venue_a, start=at(10, 9), end=at(10, 11), exclude_pk=s.pk), [])


class SessionModelTests(TimetableFixtureMixin, TestCase):
    def build(self, **over):
        data = dict(offering=self.offering, lecturer=self.lecturer, venue=self.venue_a, start_at=at(12, 9), end_at=at(12, 11))
        data.update(over)
        return LectureSession(**data)

    def test_valid_session_passes(self):
        self.build().full_clean()

    def test_end_before_start_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(end_at=at(12, 8)).full_clean()
        self.assertIn("End time must be after", str(ctx.exception))

    def test_too_long_rejected(self):
        with self.assertRaises(ValidationError):
            self.build(end_at=at(12, 20)).full_clean()

    def test_lecturer_must_be_assigned_to_offering(self):
        with self.assertRaises(ValidationError) as ctx:
            self.build(lecturer=self.lecturer2).full_clean()
        self.assertIn("not assigned", str(ctx.exception))

    def test_inactive_venue_and_offering_rejected(self):
        self.venue_b.is_active = False
        self.venue_b.save()
        with self.assertRaises(ValidationError):
            self.build(venue=self.venue_b).full_clean()
        self.offering.is_active = False
        self.offering.save()
        with self.assertRaises(ValidationError):
            self.build().full_clean()

    def test_conflict_blocks_creation_via_validation(self):
        self.make_session(start=at(12, 9), end=at(12, 11))
        with self.assertRaises(ValidationError) as ctx:
            self.build(start_at=at(12, 10), end_at=at(12, 12)).full_clean()
        self.assertTrue(any("conflict" in m for m in ctx.exception.messages))

    def test_times_are_aware_and_shown_in_kampala(self):
        s = self.make_session(start=at(10, 9), end=at(10, 11))
        s.refresh_from_db()
        self.assertTrue(timezone.is_aware(s.start_at))
        self.assertEqual(s.start_at.hour, 6)  # 09:00 EAT (UTC+3) is 06:00 UTC
        self.assertEqual(timezone.localtime(s.start_at).hour, 9)


class ServiceTests(TimetableFixtureMixin, TestCase):
    def test_create_session_records_history_audit_and_signal(self):
        received = []
        handler = lambda sender, session, change, **kw: received.append((session.pk, change.change_type))
        lecture_changed.connect(handler)
        self.addCleanup(lecture_changed.disconnect, handler)
        s = LectureSession(offering=self.offering, lecturer=self.lecturer, venue=self.venue_a, start_at=at(10, 9), end_at=at(10, 11))
        s.full_clean()
        services.create_session(s, self.admin)
        self.assertEqual(s.changes.get().change_type, ChangeType.CREATED)
        self.assertEqual(received, [(s.pk, ChangeType.CREATED)])
        self.assertTrue(AuditLog.objects.filter(action="lecture_created").exists())

    def test_reschedule_updates_session_and_keeps_history(self):
        s = self.make_session()
        received = []
        handler = lambda sender, session, change, **kw: received.append(change.change_type)
        lecture_changed.connect(handler)
        self.addCleanup(lecture_changed.disconnect, handler)
        services.reschedule_session(s, self.admin, start=at(11, 14), end=at(11, 16), venue=self.venue_b, reason="Public holiday")
        s.refresh_from_db()
        self.assertEqual((s.start_at, s.venue), (at(11, 14), self.venue_b))
        change = s.changes.get(change_type=ChangeType.RESCHEDULED)
        self.assertEqual((change.old_start_at, change.new_start_at, change.old_venue, change.new_venue),
                         (at(10, 9), at(11, 14), "Hall A", "Lab 1"))
        self.assertEqual(change.reason, "Public holiday")
        self.assertEqual(change.changed_by, self.admin)
        self.assertEqual(received, [ChangeType.RESCHEDULED])
        self.assertTrue(AuditLog.objects.filter(action="lecture_rescheduled").exists())

    def test_reschedule_into_conflict_changes_nothing(self):
        other = self.make_session(offering=self.offering2, venue=self.venue_b, start=at(11, 14), end=at(11, 16))
        s = self.make_session()
        with self.assertRaises(ValidationError):
            services.reschedule_session(s, self.admin, start=at(11, 15), end=at(11, 17), venue=self.venue_b, reason="x")
        s.refresh_from_db()
        self.assertEqual(s.start_at, at(10, 9))
        self.assertFalse(s.changes.filter(change_type=ChangeType.RESCHEDULED).exists())
        self.assertIsNotNone(other.pk)

    def test_reschedule_noop_and_invalid_times_rejected(self):
        s = self.make_session()
        with self.assertRaisesMessage(ValidationError, "Nothing changed"):
            services.reschedule_session(s, self.admin, start=at(10, 9), end=at(10, 11), venue=self.venue_a, reason="x")
        with self.assertRaises(ValidationError):
            services.reschedule_session(s, self.admin, start=at(11, 12), end=at(11, 10), venue=self.venue_a, reason="x")

    def test_cancel_session(self):
        s = self.make_session()
        services.cancel_session(s, self.admin, reason="Lecturer unwell")
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.CANCELLED)
        self.assertEqual(s.cancellation_reason, "Lecturer unwell")
        self.assertEqual(s.changes.filter(change_type=ChangeType.CANCELLED).count(), 1)
        with self.assertRaises(ValidationError):
            services.cancel_session(s, self.admin, reason="again")

    def test_cancelled_session_cannot_be_rescheduled_and_frees_the_slot(self):
        s = self.make_session()
        services.cancel_session(s, self.admin, reason="x")
        with self.assertRaises(ValidationError):
            services.reschedule_session(s, self.admin, start=at(11, 9), end=at(11, 11), venue=self.venue_a, reason="x")
        self.make_session(offering=self.offering2, venue=self.venue_a)  # same slot now free


class SessionPermissionTests(TimetableFixtureMixin, TestCase):
    def setUp(self):
        self.s1 = self.make_session()                                  # lecturer 1's offering
        self.s2 = self.make_session(offering=self.offering2, venue=self.venue_b)  # lecturer 2's offering

    def test_anonymous_redirected(self):
        for name, args in [("timetables:session_list", []), ("timetables:session_add", []), ("timetables:my_timetable", []),
                           ("timetables:venue_list", []), ("timetables:session_detail", [self.s1.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 302, name)

    def test_students_and_researchers_blocked_from_lecture_management(self):
        for username in ("stu1", "res"):
            self.client.login(username=username, password=PW)
            for name, args in [("timetables:session_list", []), ("timetables:session_add", []), ("timetables:venue_list", []),
                               ("timetables:session_detail", [self.s1.pk]), ("timetables:session_reschedule", [self.s1.pk])]:
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, f"{username} {name}")
            self.assertEqual(self.client.post(reverse("timetables:session_cancel", args=[self.s1.pk]), {"reason": "x"}).status_code, 403)
            self.client.logout()

    def test_lecturer_cannot_manage_venues(self):
        self.client.login(username="lec1", password=PW)
        self.assertEqual(self.client.get(reverse("timetables:venue_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("timetables:venue_add")).status_code, 403)

    def test_lecturer_sees_and_manages_only_own_lectures(self):
        self.client.login(username="lec1", password=PW)
        listed = [r["obj"] for r in self.client.get(reverse("timetables:session_list")).context["rows"]]
        self.assertEqual(listed, [self.s1])
        self.assertEqual(self.client.get(reverse("timetables:session_detail", args=[self.s1.pk])).status_code, 200)
        for name in ("session_detail", "session_edit", "session_reschedule"):
            self.assertEqual(self.client.get(reverse(f"timetables:{name}", args=[self.s2.pk])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse("timetables:session_cancel", args=[self.s2.pk]), {"reason": "x"}).status_code, 404)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.status, SessionStatus.SCHEDULED)

    def test_admin_sees_all_lectures(self):
        self.client.login(username="adm", password=PW)
        self.assertEqual(len(self.client.get(reverse("timetables:session_list")).context["rows"]), 2)

    def test_lecturer_schedules_only_own_offerings_as_themselves(self):
        self.client.login(username="lec1", password=PW)
        form = self.client.get(reverse("timetables:session_add")).context["form"]
        self.assertEqual(list(form.fields["offering"].queryset), [self.offering])
        self.assertNotIn("lecturer", form.fields)
        bad = self.client.post(reverse("timetables:session_add"), {"offering": self.offering2.pk, "venue": self.venue_a.pk,
                                                                   "start_at": "2026-11-20T09:00", "end_at": "2026-11-20T11:00"})
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(LectureSession.objects.count(), 2)
        ok = self.client.post(reverse("timetables:session_add"), {"offering": self.offering.pk, "venue": self.venue_a.pk,
                                                                  "start_at": "2026-11-20T09:00", "end_at": "2026-11-20T11:00", "topic": "Week 1"})
        new = LectureSession.objects.get(topic="Week 1")
        self.assertRedirects(ok, reverse("timetables:session_detail", args=[new.pk]))
        self.assertEqual(new.lecturer, self.lecturer)
        self.assertEqual(new.start_at, at(20, 9))  # form input interpreted as Africa/Kampala
        self.assertEqual(new.created_by, self.lec_user)

    def test_conflict_message_shown_in_form(self):
        self.client.login(username="adm", password=PW)
        resp = self.client.post(reverse("timetables:session_add"), {
            "offering": self.offering.pk, "lecturer": self.lecturer.pk, "venue": self.venue_a.pk,
            "start_at": "2026-11-10T10:00", "end_at": "2026-11-10T12:00"})
        self.assertContains(resp, "Lecturer conflict")
        self.assertContains(resp, "Venue conflict")
        self.assertEqual(LectureSession.objects.count(), 2)

    def test_reschedule_and_cancel_through_views(self):
        self.client.login(username="lec1", password=PW)
        url = reverse("timetables:session_reschedule", args=[self.s1.pk])
        resp = self.client.post(url, {"start_at": "2026-11-12T14:00", "end_at": "2026-11-12T16:00", "venue": self.venue_a.pk, "reason": "Clash"})
        self.assertRedirects(resp, reverse("timetables:session_detail", args=[self.s1.pk]))
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.start_at, at(12, 14))
        self.assertContains(self.client.get(url, follow=True), "Reschedule")
        self.client.post(reverse("timetables:session_cancel", args=[self.s1.pk]), {"reason": "Strike"})
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.is_cancelled)
        self.assertEqual(self.client.get(url).status_code, 302)  # cancelled lectures cannot be rescheduled
        self.assertEqual(self.client.post(reverse("timetables:session_edit", args=[self.s1.pk]), {"topic": "x"}).status_code, 403)

    def test_cancel_requires_reason(self):
        self.client.login(username="adm", password=PW)
        self.client.post(reverse("timetables:session_cancel", args=[self.s1.pk]), {"reason": ""})
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.is_cancelled)

    def test_edit_topic_not_blocked_by_later_conflicts(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        self.s2.venue = self.venue_b
        LectureSession.objects.filter(pk=self.s2.pk).update(start_at=at(10, 10), end_at=at(10, 12))
        Enrolment.objects.create(student=self.student, offering=self.offering2)  # now a student clash exists
        self.client.login(username="adm", password=PW)
        resp = self.client.post(reverse("timetables:session_edit", args=[self.s1.pk]), {"topic": "Updated topic"})
        self.assertEqual(resp.status_code, 302)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.topic, "Updated topic")

    def test_filters_and_pagination(self):
        for i in range(20):
            self.make_session(offering=self.offering2, lecturer=self.lecturer2, venue=self.venue_b,
                              start=at(11, 7) + timedelta(days=i), end=at(11, 8) + timedelta(days=i))
        self.client.login(username="adm", password=PW)
        url = reverse("timetables:session_list")
        self.assertEqual(len(self.client.get(url).context["rows"]), 15)
        self.assertEqual(len(self.client.get(url, {"venue": self.venue_a.pk}).context["rows"]), 1)
        self.assertEqual(len(self.client.get(url, {"from": "2026-11-20", "to": "2026-11-21"}).context["rows"]), 2)
        self.assertEqual(self.client.get(url, {"from": "garbage"}).status_code, 200)
        self.assertEqual(len(self.client.get(url, {"status": "cancelled"}).context["rows"]), 0)


class StudentTimetableTests(TimetableFixtureMixin, TestCase):
    def test_student_sees_only_own_enrolled_lectures(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        Enrolment.objects.create(student=self.student2, offering=self.offering2)
        mine = self.make_session(start=timezone.now() + timedelta(days=1), end=timezone.now() + timedelta(days=1, hours=2))
        other = self.make_session(offering=self.offering2, venue=self.venue_b, start=timezone.now() + timedelta(days=1),
                                  end=timezone.now() + timedelta(days=1, hours=2))
        self.client.login(username="stu1", password=PW)
        sessions = list(self.client.get(reverse("timetables:my_timetable")).context["sessions"])
        self.assertEqual(sessions, [mine])
        self.assertNotIn(other, sessions)
        resp = self.client.get(reverse("timetables:session_detail", args=[mine.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_upcoming_vs_past_and_cancelled_shown(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        now = timezone.now()
        past = self.make_session(start=now - timedelta(days=3), end=now - timedelta(days=3) + timedelta(hours=2))
        future = self.make_session(start=now + timedelta(days=2), end=now + timedelta(days=2, hours=2))
        cancelled = self.make_session(start=now + timedelta(days=4), end=now + timedelta(days=4, hours=2), status=SessionStatus.CANCELLED)
        self.client.login(username="stu1", password=PW)
        url = reverse("timetables:my_timetable")
        self.assertEqual(list(self.client.get(url).context["sessions"]), [future, cancelled])
        self.assertContains(self.client.get(url), "Cancelled")
        self.assertEqual(list(self.client.get(url, {"when": "past"}).context["sessions"]), [past])

    def test_withdrawn_enrolment_hides_lectures(self):
        Enrolment.objects.create(student=self.student, offering=self.offering, status="withdrawn")
        self.make_session(start=timezone.now() + timedelta(days=1), end=timezone.now() + timedelta(days=1, hours=1))
        self.client.login(username="stu1", password=PW)
        self.assertEqual(list(self.client.get(reverse("timetables:my_timetable")).context["sessions"]), [])

    def test_student_without_profile_sees_notice(self):
        from apps.accounts.models import Role
        from apps.academics.tests import make_user
        make_user("noprofile", Role.STUDENT)
        self.client.login(username="noprofile", password=PW)
        self.assertContains(self.client.get(reverse("timetables:my_timetable")), "profile has not been set up")

    def test_dashboards_show_real_lectures(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        self.make_session(start=timezone.now() + timedelta(days=1), end=timezone.now() + timedelta(days=1, hours=2), topic="Dash topic")
        self.client.login(username="stu1", password=PW)
        self.assertEqual(len(self.client.get(reverse("accounts:dashboard_student")).context["upcoming"]), 1)
        self.client.login(username="lec1", password=PW)
        ctx = self.client.get(reverse("accounts:dashboard_lecturer")).context
        self.assertEqual((len(ctx["upcoming"]), ctx["offering_count"]), (1, 1))
        self.client.login(username="adm", password=PW)
        self.assertIn(("Upcoming lectures", 1), self.client.get(reverse("accounts:dashboard_admin")).context["academic_counts"])


class VenueTests(TimetableFixtureMixin, TestCase):
    def test_admin_manages_venues(self):
        self.client.login(username="adm", password=PW)
        self.assertRedirects(self.client.post(reverse("timetables:venue_add"), {"name": "Room 9", "capacity": 25, "is_active": "on"}),
                             reverse("timetables:venue_list"))
        self.assertContains(self.client.post(reverse("timetables:venue_add"), {"name": "Room 9", "capacity": 25}), "already exists")
        self.assertEqual(len(self.client.get(reverse("timetables:venue_list"), {"q": "Room"}).context["rows"]), 1)
