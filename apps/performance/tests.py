"""Phase 4 tests: assignments, submissions, punctuality, assessments, marks, permissions.
Test fixtures only; none of it represents real students or marks."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus
from apps.academics.tests import AcademicFixtureMixin, PW
from apps.accounts.models import AuditLog

from . import services
from .models import Assessment, AssessmentResult, Assignment, Submission

D = Decimal


class PerfFixtureMixin(AcademicFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.long_ago = timezone.localdate() - timedelta(days=90)
        cls.enrol1 = Enrolment.objects.create(student=cls.student, offering=cls.offering, enrolled_on=cls.long_ago)
        cls.enrol2 = Enrolment.objects.create(student=cls.student2, offering=cls.offering, enrolled_on=cls.long_ago)
        cls.now = timezone.now()

    def assignment(self, days=-5, complete=True, offering=None, **kw):
        return Assignment.objects.create(offering=offering or self.offering, title=kw.pop("title", "Assignment 1"),
                                         deadline=self.now + timedelta(days=days), records_complete=complete, **kw)

    def submit(self, assignment, student, hours_after_deadline=None, status="submitted", **kw):
        at = assignment.deadline + timedelta(hours=hours_after_deadline) if hours_after_deadline is not None else None
        return Submission.objects.create(assignment=assignment, student=student, status=status, submitted_at=at, **kw)

    def login(self, user):
        self.client.login(username=user.username, password=PW)


class SubmissionModelTests(PerfFixtureMixin, TestCase):
    def test_validation_rules(self):
        a = self.assignment(max_marks=D("50"))
        bad = [
            Submission(assignment=a, student=self.student, status="submitted"),                                  # no time
            Submission(assignment=a, student=self.student, status="not_submitted", submitted_at=self.now),        # time without submit
            Submission(assignment=a, student=self.student, status="submitted", submitted_at=self.now, marks=D("51")),  # over max
            Submission(assignment=a, student=self.student, status="not_submitted", marks=D("10")),               # marks w/o submit
            Submission(assignment=a, student=self.student, status="not_submitted", extended_deadline=a.deadline - timedelta(days=1)),
        ]
        for sub in bad:
            with self.assertRaises(ValidationError):
                sub.clean()
        Submission(assignment=a, student=self.student, status="submitted", submitted_at=self.now, marks=D("50")).clean()

    def test_one_submission_per_student_and_assignment(self):
        a = self.assignment()
        self.submit(a, self.student, 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.submit(a, self.student, 1)

    def test_is_late_and_effective_deadline(self):
        a = self.assignment()
        on_time, late = self.submit(a, self.student, -1), self.submit(a, self.student2, 2)
        self.assertFalse(on_time.is_late)
        self.assertTrue(late.is_late)
        late.extended_deadline = a.deadline + timedelta(days=1)
        self.assertEqual(late.effective_deadline, late.extended_deadline)
        self.assertFalse(late.is_late)

    def test_result_validation(self):
        t = Assessment.objects.create(offering=self.offering, title="Test 1", max_marks=D("20"))
        with self.assertRaises(ValidationError):
            AssessmentResult(assessment=t, student=self.student, status="marked").clean()
        with self.assertRaises(ValidationError):
            AssessmentResult(assessment=t, student=self.student, status="marked", marks=D("21")).clean()
        with self.assertRaises(ValidationError):
            AssessmentResult(assessment=t, student=self.student, status="absent", marks=D("5")).clean()
        AssessmentResult(assessment=t, student=self.student, status="marked", marks=D("20")).clean()
        AssessmentResult(assessment=t, student=self.student, status="absent").clean()


class PunctualityTests(PerfFixtureMixin, TestCase):
    def test_classification_and_rate(self):
        a = self.assignment()
        self.submit(a, self.student, -2)            # on time
        report = services.assignment_report(a)
        classes = {r["student"].pk: r["cls"] for r in report["rows"]}
        self.assertEqual(classes[self.student.pk], services.ON_TIME)
        self.assertEqual(classes[self.student2.pk], services.MISSING)  # no submission, records complete, deadline passed
        s = report["summary"]
        self.assertEqual((s.on_time, s.late, s.missing, s.eligible, s.rate), (1, 0, 1, 2, 50.0))

    def test_submission_exactly_at_deadline_is_on_time(self):
        a = self.assignment()
        self.submit(a, self.student, 0)
        self.assertEqual(services.classify(a, a.submissions.get(), self.now), services.ON_TIME)

    def test_late_submission(self):
        a = self.assignment()
        self.submit(a, self.student, 3)
        self.assertEqual(services.classify(a, a.submissions.get(), self.now), services.LATE)

    def test_extension_turns_late_into_on_time(self):
        a = self.assignment()
        self.submit(a, self.student, 3, extended_deadline=a.deadline + timedelta(days=1))
        self.assertEqual(services.classify(a, a.submissions.get(), self.now), services.ON_TIME)

    def test_exempt_students_are_excluded(self):
        a = self.assignment()
        self.submit(a, self.student, -1)
        self.submit(a, self.student2, status="exempt")
        s = services.assignment_report(a)["summary"]
        self.assertEqual((s.on_time, s.exempt, s.eligible, s.rate), (1, 1, 1, 100.0))

    def test_not_yet_due_is_excluded_including_extensions(self):
        future = self.assignment(days=3, title="Future")
        self.assertEqual(services.assignment_report(future)["summary"].eligible, 0)
        a = self.assignment(days=-1, title="Extended")
        self.submit(a, self.student, status="not_submitted", extended_deadline=a.deadline + timedelta(days=5))
        classes = {r["student"].pk: r["cls"] for r in services.assignment_report(a)["rows"]}
        self.assertEqual(classes[self.student.pk], services.NOT_DUE)
        self.assertEqual(classes[self.student2.pk], services.MISSING)

    def test_incomplete_records_are_not_counted_against_students(self):
        a = self.assignment(complete=False)
        self.assertEqual(services.assignment_report(a)["summary"].eligible, 0)
        summary = services.student_punctuality(self.student)
        self.assertEqual((summary.eligible, summary.rate, summary.assignments_awaiting_records), (0, None, 1))

    def test_withdrawn_and_late_enrolled_students_excluded(self):
        a = self.assignment()
        self.enrol2.status = EnrolmentStatus.WITHDRAWN
        self.enrol2.save()
        self.assertEqual([r["student"].pk for r in services.assignment_report(a)["rows"]], [self.student.pk])
        self.enrol1.enrolled_on = timezone.localdate()  # enrolled after the deadline passed
        self.enrol1.save()
        self.assertEqual(services.assignment_report(a)["rows"], [])

    def test_student_punctuality_across_assignments(self):
        a1, a2, a3 = self.assignment(title="A1"), self.assignment(days=-3, title="A2"), self.assignment(days=-1, title="A3")
        self.submit(a1, self.student, -1)
        self.submit(a2, self.student, 5)
        summary = services.student_punctuality(self.student)
        self.assertEqual((summary.on_time, summary.late, summary.missing, summary.rate), (1, 1, 1, 33.3))
        self.assertEqual(summary.assignments_counted, 3)
        windowed = services.student_punctuality(self.student, start=self.now - timedelta(days=4))
        self.assertEqual(windowed.eligible, 2)
        self.assertEqual(services.student_punctuality(self.student, offering=self.offering2).eligible, 0)


class PerformanceCalculationTests(PerfFixtureMixin, TestCase):
    def test_percentage_rounding(self):
        self.assertEqual(services.pct(D("17"), D("20")), 85.0)
        self.assertEqual(services.pct(D("1"), D("3")), 33.3)
        self.assertEqual(services.pct(D("2"), D("3")), 66.7)
        self.assertIsNone(services.pct(None, D("10")))

    def test_simple_average_when_no_weights(self):
        t1 = Assessment.objects.create(offering=self.offering, title="T1", max_marks=D("20"))
        t2 = Assessment.objects.create(offering=self.offering, title="T2", max_marks=D("50"))
        AssessmentResult.objects.create(assessment=t1, student=self.student, marks=D("10"))   # 50%
        AssessmentResult.objects.create(assessment=t2, student=self.student, marks=D("40"))   # 80%
        perf = services.student_offering_performance(self.student, self.offering)
        self.assertEqual((perf["percentage"], perf["method"], perf["marked_items"]), (65.0, "simple average", 2))

    def test_weighted_when_weights_set(self):
        a = self.assignment(max_marks=D("10"), weight_percent=D("20"))
        self.submit(a, self.student, -1, marks=D("5"))                                          # 50% x 20
        exam = Assessment.objects.create(offering=self.offering, title="Exam", kind="exam", max_marks=D("100"), weight_percent=D("60"))
        AssessmentResult.objects.create(assessment=exam, student=self.student, marks=D("80"))   # 80% x 60
        unweighted = Assessment.objects.create(offering=self.offering, title="Quiz", max_marks=D("10"))
        AssessmentResult.objects.create(assessment=unweighted, student=self.student, marks=D("10"))  # ignored when weights exist
        perf = services.student_offering_performance(self.student, self.offering)
        # (20*50 + 60*80) / 80 = 72.5
        self.assertEqual((perf["percentage"], perf["method"], perf["weight_covered"]), (72.5, "weighted", 80.0))

    def test_missing_absent_and_exempt_are_not_zero(self):
        t1 = Assessment.objects.create(offering=self.offering, title="T1", max_marks=D("10"))
        t2 = Assessment.objects.create(offering=self.offering, title="T2", max_marks=D("10"))
        t3 = Assessment.objects.create(offering=self.offering, title="T3", max_marks=D("10"))
        AssessmentResult.objects.create(assessment=t1, student=self.student, marks=D("8"))
        AssessmentResult.objects.create(assessment=t2, student=self.student, status="absent")
        AssessmentResult.objects.create(assessment=t3, student=self.student, status="exempt")
        perf = services.student_offering_performance(self.student, self.offering)
        self.assertEqual((perf["percentage"], perf["marked_items"]), (80.0, 1))
        none = services.student_offering_performance(self.student2, self.offering)
        self.assertEqual((none["percentage"], none["method"]), (None, "none"))

    def test_assignment_marks_only_count_when_submitted(self):
        a = self.assignment(max_marks=D("10"))
        self.submit(a, self.student, -1, marks=D("9"))
        self.assertEqual(services.student_offering_performance(self.student, self.offering)["percentage"], 90.0)

    def test_offering_report_statistics(self):
        t = Assessment.objects.create(offering=self.offering, title="T", max_marks=D("100"))
        AssessmentResult.objects.create(assessment=t, student=self.student, marks=D("45"))
        AssessmentResult.objects.create(assessment=t, student=self.student2, marks=D("85"))
        report = services.offering_performance_report(self.offering)
        self.assertEqual((report["enrolled"], report["with_marks"]), (2, 2))
        self.assertEqual((report["stats"]["mean"], report["stats"]["median"], report["stats"]["min"], report["stats"]["max"]), (65.0, 65.0, 45.0, 85.0))
        self.assertEqual(report["distribution"], [0, 1, 0, 0, 0, 1])
        self.assertEqual(sum(report["distribution"]), 2)

    def test_offering_report_without_marks_has_no_statistics(self):
        report = services.offering_performance_report(self.offering)
        self.assertIsNone(report["stats"])
        self.assertEqual(report["with_marks"], 0)


class PerformancePermissionTests(PerfFixtureMixin, TestCase):
    def setUp(self):
        self.assignment_obj = self.assignment()
        self.assessment_obj = Assessment.objects.create(offering=self.offering, title="Test 1", max_marks=D("20"))

    def staff_urls(self):
        a, t = self.assignment_obj.pk, self.assessment_obj.pk
        return [reverse("performance:assignment_list"), reverse("performance:assignment_add"),
                reverse("performance:assignment_detail", args=[a]), reverse("performance:assignment_edit", args=[a]),
                reverse("performance:assignment_records", args=[a]), reverse("performance:assessment_list"),
                reverse("performance:assessment_add"), reverse("performance:assessment_detail", args=[t]),
                reverse("performance:assessment_edit", args=[t]), reverse("performance:assessment_results", args=[t]),
                reverse("performance:offering_report", args=[self.offering.pk])]

    def test_anonymous_redirected(self):
        for url in self.staff_urls() + [reverse("performance:my_deadlines"), reverse("performance:my_results")]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/login", resp["Location"])

    def test_students_and_researchers_cannot_use_staff_pages(self):
        for user in (self.stu_user, self.researcher):
            self.login(user)
            for url in self.staff_urls():
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))
            self.client.logout()

    def test_staff_cannot_use_student_pages(self):
        for user in (self.lec_user, self.admin, self.researcher):
            self.login(user)
            for name in ("my_deadlines", "my_results"):
                self.assertEqual(self.client.get(reverse(f"performance:{name}")).status_code, 403)
            self.client.logout()

    def test_other_lecturer_gets_404(self):
        self.login(self.lec2_user)
        for url in self.staff_urls()[2:5] + self.staff_urls()[7:]:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        resp = self.client.post(reverse("performance:assignment_records", args=[self.assignment_obj.pk]),
                                {f"status_{self.student.pk}": "submitted"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Submission.objects.count(), 0)

    def test_lecturer_lists_show_only_own_items(self):
        other = self.assignment(offering=self.offering2, title="Other course")
        self.login(self.lec_user)
        resp = self.client.get(reverse("performance:assignment_list"))
        titles = [row["obj"].title for row in resp.context["rows"]]
        self.assertEqual(titles, ["Assignment 1"])
        self.client.logout()
        self.login(self.admin)
        self.assertEqual(len(self.client.get(reverse("performance:assignment_list")).context["rows"]), 2)

    def test_lecturer_can_only_create_for_own_offering(self):
        self.login(self.lec_user)
        url = reverse("performance:assignment_add")
        data = {"title": "New", "instructions": "x", "deadline": "2026-12-01T10:00", "max_marks": "100"}
        resp = self.client.post(url, dict(data, offering=self.offering2.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Assignment.objects.filter(title="New").exists())
        resp = self.client.post(url, dict(data, offering=self.offering.pk))
        self.assertEqual(resp.status_code, 302)
        created = Assignment.objects.get(title="New")
        self.assertEqual(created.created_by, self.lec_user)
        self.assertTrue(AuditLog.objects.filter(action="assignment_created").exists())

    def test_deadline_is_entered_in_kampala_time(self):
        self.login(self.lec_user)
        self.client.post(reverse("performance:assignment_add"), {"offering": self.offering.pk, "title": "Tz", "deadline": "2026-12-01T10:00", "max_marks": "100"})
        self.assertEqual(Assignment.objects.get(title="Tz").deadline.isoformat(), "2026-12-01T07:00:00+00:00")  # UTC+3

    def test_offering_cannot_be_changed_when_editing(self):
        self.login(self.lec_user)
        resp = self.client.post(reverse("performance:assignment_edit", args=[self.assignment_obj.pk]),
                                {"offering": self.offering2.pk, "title": "Renamed", "deadline": "2026-12-01T10:00", "max_marks": "100"})
        self.assertEqual(resp.status_code, 302)
        self.assignment_obj.refresh_from_db()
        self.assertEqual((self.assignment_obj.title, self.assignment_obj.offering), ("Renamed", self.offering))

    def test_students_see_only_their_own_results(self):
        AssessmentResult.objects.create(assessment=self.assessment_obj, student=self.student, marks=D("15"))
        AssessmentResult.objects.create(assessment=self.assessment_obj, student=self.student2, marks=D("7"))
        self.login(self.stu_user)
        resp = self.client.get(reverse("performance:my_results"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "15.00 / 20.00")
        self.assertNotContains(resp, "7.00 / 20.00")  # the other student's marks
        self.assertEqual(resp.context["courses"][0][1]["percentage"], 75.0)

    def test_student_results_exclude_courses_they_are_not_enrolled_in(self):
        t = Assessment.objects.create(offering=self.offering2, title="Other test", max_marks=D("10"))
        AssessmentResult.objects.create(assessment=t, student=self.student, marks=D("9"))  # data exists but student not enrolled
        self.login(self.stu_user)
        resp = self.client.get(reverse("performance:my_results"))
        self.assertEqual([o.pk for o, _ in resp.context["courses"]], [self.offering.pk])

    def test_student_deadlines_page(self):
        self.assignment(days=5, title="Upcoming one")
        self.submit(self.assignment_obj, self.student, 4)  # late
        self.login(self.stu_user)
        resp = self.client.get(reverse("performance:my_deadlines"))
        self.assertEqual([r["assignment"].title for r in resp.context["upcoming"]], ["Upcoming one"])
        self.assertEqual(resp.context["upcoming"][0]["status"], "Open")
        self.assertEqual(resp.context["past"][0]["status"], "Submitted late")
        self.client.logout()
        self.login(self.stu2_user)
        self.assertEqual(self.client.get(reverse("performance:my_deadlines")).context["past"][0]["status"], "No submission recorded")


class RecordEntryTests(PerfFixtureMixin, TestCase):
    def setUp(self):
        self.a = self.assignment(complete=False, max_marks=D("20"))
        self.url = reverse("performance:assignment_records", args=[self.a.pk])
        self.login(self.lec_user)

    def row(self, student, **vals):
        return {f"{k}_{student.pk}": v for k, v in vals.items()}

    def test_save_submissions_marks_and_complete_flag(self):
        data = {"records_complete": "on", **self.row(self.student, status="submitted", submitted_at="2026-01-01T10:00", marks="15"),
                **self.row(self.student2, status="exempt")}
        resp = self.client.post(self.url, data)
        self.assertRedirects(resp, reverse("performance:assignment_detail", args=[self.a.pk]))
        sub = Submission.objects.get(student=self.student)
        self.assertEqual((sub.status, sub.marks, sub.recorded_by), ("submitted", D("15"), self.lec_user))
        self.assertEqual(Submission.objects.get(student=self.student2).status, "exempt")
        self.a.refresh_from_db()
        self.assertTrue(self.a.records_complete)
        entry = AuditLog.objects.filter(action="submissions_saved").latest("timestamp")
        self.assertIn("mark changes", entry.details)

    def test_invalid_rows_rejected_and_nothing_saved(self):
        for bad in (self.row(self.student, status="submitted", marks="25", submitted_at="2026-01-01T10:00"),   # over max
                    self.row(self.student, status="submitted"),                                                  # no time
                    self.row(self.student, status="", marks="5"),                                               # marks without status
                    self.row(self.student, status="not_submitted", submitted_at="2026-01-01T10:00")):
            resp = self.client.post(self.url, bad)
            self.assertEqual(resp.status_code, 200, bad)
        self.assertEqual(Submission.objects.count(), 0)

    def test_blank_row_leaves_existing_record_untouched(self):
        self.submit(self.a, self.student, -1, marks=D("12"))
        self.client.post(self.url, self.row(self.student, status=""))
        self.assertEqual(Submission.objects.get(student=self.student).marks, D("12"))

    def test_updating_marks_is_audited(self):
        self.submit(self.a, self.student, -1, marks=D("12"))
        self.client.post(self.url, self.row(self.student, status="submitted", submitted_at="2026-01-01T10:00", marks="14"))
        self.assertEqual(Submission.objects.get(student=self.student).marks, D("14"))
        entry = AuditLog.objects.filter(action="submissions_saved").latest("timestamp")
        self.assertIn("12.00 -> 14", entry.details)

    def test_assessment_results_entry(self):
        t = Assessment.objects.create(offering=self.offering, title="Quiz", max_marks=D("10"))
        url = reverse("performance:assessment_results", args=[t.pk])
        resp = self.client.post(url, {**self.row(self.student, status="marked", marks="7.5"), **self.row(self.student2, status="absent")})
        self.assertRedirects(resp, reverse("performance:assessment_detail", args=[t.pk]))
        self.assertEqual(AssessmentResult.objects.get(student=self.student).marks, D("7.5"))
        self.assertEqual(AssessmentResult.objects.get(student=self.student2).marks, None)
        self.assertEqual(self.client.post(url, self.row(self.student, status="marked", marks="11")).status_code, 200)
        self.assertEqual(AssessmentResult.objects.get(student=self.student).marks, D("7.5"))
        self.assertTrue(AuditLog.objects.filter(action="results_saved").exists())

    def test_assessment_detail_and_reports_render(self):
        t = Assessment.objects.create(offering=self.offering, title="Quiz", max_marks=D("10"))
        AssessmentResult.objects.create(assessment=t, student=self.student, marks=D("7"))
        self.assertEqual(self.client.get(reverse("performance:assessment_detail", args=[t.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("performance:assignment_detail", args=[self.a.pk])).status_code, 200)
        resp = self.client.get(reverse("performance:offering_report", args=[self.offering.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["stats"]["mean"], 70.0)


class PageRenderTests(PerfFixtureMixin, TestCase):
    """Every new page renders (HTTP 200) for the roles allowed to open it, including empty states."""

    def test_staff_pages_render_for_lecturer_and_admin(self):
        a = self.assignment()
        t = Assessment.objects.create(offering=self.offering, title="Test 1", max_marks=D("20"))
        self.submit(a, self.student, -1, marks=D("10"))
        AssessmentResult.objects.create(assessment=t, student=self.student, marks=D("12"))
        urls = [reverse("performance:assignment_list"), reverse("performance:assignment_add"),
                reverse("performance:assignment_detail", args=[a.pk]), reverse("performance:assignment_edit", args=[a.pk]),
                reverse("performance:assignment_records", args=[a.pk]), reverse("performance:assessment_list"),
                reverse("performance:assessment_add"), reverse("performance:assessment_detail", args=[t.pk]),
                reverse("performance:assessment_edit", args=[t.pk]), reverse("performance:assessment_results", args=[t.pk]),
                reverse("performance:offering_report", args=[self.offering.pk]),
                reverse("attendance:offering_report", args=[self.offering.pk]),
                reverse("academics:offering_detail", args=[self.offering.pk])]
        for user in (self.lec_user, self.admin):
            self.login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 200, (user.username, url))
            self.client.logout()

    def test_student_pages_render_with_and_without_data(self):
        self.login(self.stu_user)
        for url in (reverse("performance:my_deadlines"), reverse("performance:my_results"), reverse("attendance:my_attendance"),
                    reverse("accounts:dashboard_student")):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_django_admin_lists_new_models_for_administrators_only(self):
        self.login(self.admin)
        for name in ("attendance_attendancerecord", "attendance_attendancechange", "attendance_attendancerules",
                     "performance_assignment", "performance_assessment", "performance_submission", "performance_assessmentresult"):
            self.assertEqual(self.client.get(reverse(f"admin:{name}_changelist")).status_code, 200, name)
        self.client.logout()
        self.login(self.lec_user)
        self.assertNotEqual(self.client.get(reverse("admin:performance_assignment_changelist")).status_code, 200)
