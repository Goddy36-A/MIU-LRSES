"""Phase 4 tests: attendance recording, corrections, rate calculations, permissions.
All data below is synthetic test fixture data."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus, StudentProfile
from apps.academics.tests import PW, make_user
from apps.accounts.models import AuditLog, Role
from apps.timetables.models import LectureSession, SessionStatus
from apps.timetables.tests import TimetableFixtureMixin

from . import services
from .models import AttendanceChange, AttendanceRecord, AttendanceRules, AttendanceStatus, ExcusedPolicy


class AttendanceFixtureMixin(TimetableFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.enrol1 = Enrolment.objects.create(student=cls.student, offering=cls.offering, enrolled_on=timezone.localdate() - timedelta(days=60))
        cls.enrol2 = Enrolment.objects.create(student=cls.student2, offering=cls.offering, enrolled_on=timezone.localdate() - timedelta(days=60))

    def past_session(self, days_ago=1, offering=None, **kw):
        start = (timezone.now() - timedelta(days=days_ago)).replace(microsecond=0)
        return self.make_session(offering=offering, start=start, end=start + timedelta(hours=2), **kw)

    def login(self, user):
        self.client.login(username=user.username, password=PW)


class RecordingTests(AttendanceFixtureMixin, TestCase):
    def test_record_statuses_creates_records_history_and_audit(self):
        s = self.past_session()
        result = services.save_attendance(s, self.lec_user, {self.student.pk: "present", self.student2.pk: "late"})
        self.assertEqual(result, {"created": 2, "corrected": 0, "unchanged": 0})
        rec = AttendanceRecord.objects.get(session=s, student=self.student)
        self.assertEqual((rec.status, rec.recorded_by), ("present", self.lec_user))
        self.assertEqual(AttendanceChange.objects.filter(record__session=s).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="attendance_recorded").exists())

    def test_all_four_statuses_available(self):
        self.assertEqual(set(AttendanceStatus.values), {"present", "absent", "late", "excused"})

    def test_blank_status_creates_no_record(self):
        s = self.past_session()
        services.save_attendance(s, self.lec_user, {self.student.pk: "", self.student2.pk: "absent"})
        self.assertFalse(AttendanceRecord.objects.filter(session=s, student=self.student).exists())

    def test_duplicate_record_rejected_at_database_level(self):
        s = self.past_session()
        AttendanceRecord.objects.create(session=s, student=self.student, status="present")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord.objects.create(session=s, student=self.student, status="absent")

    def test_saving_same_values_again_does_not_duplicate(self):
        s = self.past_session()
        services.save_attendance(s, self.lec_user, {self.student.pk: "present"})
        result = services.save_attendance(s, self.lec_user, {self.student.pk: "present"})
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(AttendanceRecord.objects.filter(session=s).count(), 1)
        self.assertEqual(AttendanceChange.objects.count(), 1)

    def test_correction_requires_reason_and_keeps_audit_trail(self):
        s = self.past_session()
        services.save_attendance(s, self.lec_user, {self.student.pk: "absent"})
        with self.assertRaises(ValidationError):
            services.save_attendance(s, self.lec_user, {self.student.pk: "excused"})
        self.assertEqual(AttendanceRecord.objects.get(session=s).status, "absent")  # nothing changed
        result = services.save_attendance(s, self.admin, {self.student.pk: "excused"}, reason="Medical note received")
        self.assertEqual(result["corrected"], 1)
        change = AttendanceChange.objects.filter(record__session=s).first()
        self.assertEqual((change.old_status, change.new_status, change.reason, change.changed_by),
                         ("absent", "excused", "Medical note received", self.admin))
        self.assertTrue(change.is_correction)
        self.assertEqual(AttendanceChange.objects.filter(record__session=s).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="attendance_corrected").exists())

    def test_cannot_record_future_or_cancelled_lecture(self):
        future = self.make_session(start=timezone.now() + timedelta(days=2), end=timezone.now() + timedelta(days=2, hours=2))
        with self.assertRaises(ValidationError):
            services.save_attendance(future, self.lec_user, {self.student.pk: "present"})
        past = self.past_session()
        past.status = SessionStatus.CANCELLED
        past.save()
        with self.assertRaises(ValidationError):
            services.save_attendance(past, self.lec_user, {self.student.pk: "present"})

    def test_unknown_status_and_non_enrolled_student_rejected(self):
        s = self.past_session()
        with self.assertRaises(ValidationError):
            services.save_attendance(s, self.lec_user, {self.student.pk: "teleported"})
        outsider = StudentProfile.objects.create(user=make_user("stu3", Role.STUDENT), registration_number="S003", programme=self.programme)
        with self.assertRaises(ValidationError):
            services.save_attendance(s, self.lec_user, {outsider.pk: "present"})
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_failed_save_is_atomic(self):
        s = self.past_session()
        with self.assertRaises(ValidationError):
            services.save_attendance(s, self.lec_user, {self.student.pk: "present", self.student2.pk: "bogus"})
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_roster_excludes_withdrawn_students(self):
        self.enrol2.status = EnrolmentStatus.WITHDRAWN
        self.enrol2.save()
        s = self.past_session()
        self.assertEqual([e.student_id for e in services.roster(s)], [self.student.pk])


class RateCalculationTests(AttendanceFixtureMixin, TestCase):
    def setUp(self):
        self.sessions = [self.past_session(days_ago=d) for d in (5, 4, 3, 2)]

    def record(self, statuses):
        for s, status in zip(self.sessions, statuses):
            if status:
                AttendanceRecord.objects.create(session=s, student=self.student, status=status)

    def test_default_rules(self):
        self.record(["present", "late", "absent", "excused"])
        summary = services.student_summary(self.student)
        self.assertEqual((summary.held, summary.recorded, summary.unrecorded), (4, 4, 0))
        # late counts as attended; excused excluded: attended 2 of denominator 3 -> 66.7
        self.assertEqual((summary.attended, summary.denominator, summary.rate), (2, 3, 66.7))

    def test_missing_records_are_not_absences(self):
        self.record(["present", None, None, "present"])
        summary = services.student_summary(self.student)
        self.assertEqual((summary.held, summary.recorded, summary.unrecorded), (4, 2, 2))
        self.assertEqual(summary.rate, 100.0)

    def test_rate_is_none_without_any_record(self):
        summary = services.student_summary(self.student)
        self.assertEqual((summary.held, summary.rate), (4, None))

    def test_late_not_counted_as_attended_when_configured(self):
        rules = AttendanceRules.get()
        rules.late_counts_as_attended = False
        rules.save()
        self.record(["present", "late", "absent", None])
        self.assertEqual(services.student_summary(self.student).rate, 33.3)

    def test_excused_policies(self):
        self.record(["present", "excused", "absent", None])
        rules = AttendanceRules.get()
        for policy, expected in ((ExcusedPolicy.EXCLUDE, 50.0), (ExcusedPolicy.ATTENDED, 66.7), (ExcusedPolicy.ABSENT, 33.3)):
            rules.excused_policy = policy
            rules.save()
            self.assertEqual(services.student_summary(self.student).rate, expected, policy)

    def test_cancelled_and_future_lectures_are_not_held(self):
        self.sessions[0].status = SessionStatus.CANCELLED
        self.sessions[0].save()
        self.make_session(start=timezone.now() + timedelta(days=3), end=timezone.now() + timedelta(days=3, hours=2))
        self.assertEqual(services.student_summary(self.student).held, 3)

    def test_lectures_before_enrolment_do_not_count(self):
        self.enrol1.enrolled_on = timezone.localdate() - timedelta(days=3)
        self.enrol1.save()
        self.assertEqual(services.student_summary(self.student).held, 2)  # lectures 3 and 2 days ago; the 3-day-old one falls on the enrolment date

    def test_withdrawn_enrolment_excluded(self):
        self.enrol1.status = EnrolmentStatus.WITHDRAWN
        self.enrol1.save()
        self.assertEqual(services.student_summary(self.student).held, 0)

    def test_time_window(self):
        window_start = timezone.now() - timedelta(days=3, hours=12)
        self.assertEqual(services.student_summary(self.student, start=window_start).held, 2)
        self.assertEqual(services.student_summary(self.student, end=window_start).held, 2)

    def test_percent_helper(self):
        self.assertIsNone(services.percent(1, 0))
        self.assertEqual(services.percent(1, 3), 33.3)
        self.assertEqual(services.percent(2, 3), 66.7)
        self.assertEqual(services.percent(1, 8), 12.5)

    def test_offering_report(self):
        self.record(["present", "present", "absent", None])
        AttendanceRecord.objects.create(session=self.sessions[0], student=self.student2, status="absent")
        report = services.offering_report(self.offering)
        rows = {r["student"].pk: r["summary"] for r in report["students"]}
        self.assertEqual(rows[self.student.pk].rate, 66.7)
        self.assertEqual(rows[self.student2.pk].rate, 0.0)
        self.assertEqual(len(report["sessions"]), 4)
        self.assertEqual(report["overall"].held, 8)
        self.assertEqual(report["overall"].recorded, 4)

    def test_student_report_by_offering(self):
        self.record(["present", "present", None, None])
        report = services.student_report(self.student)
        self.assertEqual(len(report["by_offering"]), 1)
        self.assertEqual(report["overall"].rate, 100.0)
        self.assertEqual(report["records"].count(), 2)


class AttendancePermissionTests(AttendanceFixtureMixin, TestCase):
    def setUp(self):
        self.session = self.past_session()
        self.mark_url = reverse("attendance:mark", args=[self.session.pk])

    def test_anonymous_redirected_to_login(self):
        for url in (self.mark_url, reverse("attendance:my_attendance"), reverse("attendance:rules"),
                    reverse("attendance:offering_report", args=[self.offering.pk]),
                    reverse("attendance:student_report", args=[self.student.pk])):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/login", resp["Location"])

    def test_student_and_researcher_cannot_mark_or_see_reports(self):
        for user in (self.stu_user, self.researcher):
            self.login(user)
            for url in (self.mark_url, reverse("attendance:offering_report", args=[self.offering.pk]),
                        reverse("attendance:student_report", args=[self.student.pk]), reverse("attendance:rules")):
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))
            self.assertEqual(self.client.post(self.mark_url, {f"status_{self.student.pk}": "present"}).status_code, 403)
            self.client.logout()
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_lecturer_cannot_touch_another_lecturers_course(self):
        self.login(self.lec2_user)
        self.assertEqual(self.client.get(self.mark_url).status_code, 404)
        self.assertEqual(self.client.post(self.mark_url, {f"status_{self.student.pk}": "present"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("attendance:offering_report", args=[self.offering.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("attendance:student_report", args=[self.student.pk])).status_code, 404)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_assigned_lecturer_can_record_via_the_page(self):
        self.login(self.lec_user)
        self.assertEqual(self.client.get(self.mark_url).status_code, 200)
        resp = self.client.post(self.mark_url, {f"status_{self.student.pk}": "present", f"status_{self.student2.pk}": "absent", "reason": ""})
        self.assertRedirects(resp, self.mark_url)
        self.assertEqual(AttendanceRecord.objects.filter(session=self.session).count(), 2)
        self.assertEqual(self.client.get(self.mark_url).status_code, 200)

    def test_correcting_via_the_page_needs_a_reason(self):
        self.login(self.lec_user)
        self.client.post(self.mark_url, {f"status_{self.student.pk}": "absent"})
        resp = self.client.post(self.mark_url, {f"status_{self.student.pk}": "present", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter a reason for the correction")
        self.assertEqual(AttendanceRecord.objects.get(session=self.session, student=self.student).status, "absent")
        resp = self.client.post(self.mark_url, {f"status_{self.student.pk}": "present", "reason": "Marked wrong student"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(AttendanceRecord.objects.get(session=self.session, student=self.student).status, "present")

    def test_invalid_status_value_in_post_rejected(self):
        self.login(self.lec_user)
        resp = self.client.post(self.mark_url, {f"status_{self.student.pk}": "hacked"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_admin_can_record_and_view_any_report(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.mark_url).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:offering_report", args=[self.offering2.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance:student_report", args=[self.student.pk])).status_code, 200)

    def test_student_sees_only_their_own_attendance(self):
        AttendanceRecord.objects.create(session=self.session, student=self.student, status="present")
        AttendanceRecord.objects.create(session=self.session, student=self.student2, status="absent")
        self.login(self.stu_user)
        resp = self.client.get(reverse("attendance:my_attendance"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r.student_id for r in resp.context["records"]], [self.student.pk])
        self.assertEqual(resp.context["overall"].rate, 100.0)

    def test_lecturer_report_for_own_course_works(self):
        self.login(self.lec_user)
        resp = self.client.get(reverse("attendance:offering_report", args=[self.offering.pk]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("attendance:student_report", args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_only_admin_edits_rules(self):
        self.login(self.lec_user)
        self.assertEqual(self.client.get(reverse("attendance:rules")).status_code, 403)
        self.client.logout()
        self.login(self.admin)
        resp = self.client.post(reverse("attendance:rules"), {"excused_policy": "absent"})  # unchecked box = late not attended
        self.assertEqual(resp.status_code, 302)
        rules = AttendanceRules.get()
        self.assertEqual((rules.excused_policy, rules.late_counts_as_attended, rules.updated_by), ("absent", False, self.admin))
        self.assertTrue(AuditLog.objects.filter(action="attendance_rules_updated").exists())

    def test_lecture_detail_links_to_attendance(self):
        self.login(self.lec_user)
        resp = self.client.get(reverse("timetables:session_detail", args=[self.session.pk]))
        self.assertContains(resp, self.mark_url)
