"""Phase 2 tests: academic records. All data below is synthetic test fixture data."""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import AuditLog, Role, User

from .models import (AcademicYear, Course, CourseOffering, Enrolment, EnrolmentStatus, LecturerProfile, Programme,
                     Semester, StudentProfile)

PW = "Sup3r-Secret-Test-pw"


def make_user(username, role, **kw):
    return User.objects.create_user(username=username, password=PW, role=role, email=f"{username}@example.test",
                                    first_name="Test", last_name=username.title(), **kw)


class AcademicFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("adm", Role.ADMIN)
        cls.researcher = make_user("res", Role.RESEARCHER)
        cls.lec_user = make_user("lec1", Role.LECTURER)
        cls.lec2_user = make_user("lec2", Role.LECTURER)
        cls.stu_user = make_user("stu1", Role.STUDENT)
        cls.stu2_user = make_user("stu2", Role.STUDENT)
        cls.programme = Programme.objects.create(code="BIT", name="Bachelor of IT")
        cls.programme2 = Programme.objects.create(code="BBA", name="Bachelor of Business")
        cls.year = AcademicYear.objects.create(name="2026/2027", start_date=date(2026, 8, 1), end_date=date(2027, 7, 31), is_current=True)
        cls.semester = Semester.objects.create(academic_year=cls.year, number=1, start_date=date(2026, 8, 3), end_date=date(2026, 12, 4), is_current=True)
        cls.course = Course.objects.create(code="BIT101", title="Intro to Computing", programme=cls.programme)
        cls.course2 = Course.objects.create(code="BIT102", title="Programming I", programme=cls.programme)
        cls.lecturer = LecturerProfile.objects.create(user=cls.lec_user, staff_number="L001")
        cls.lecturer2 = LecturerProfile.objects.create(user=cls.lec2_user, staff_number="L002")
        cls.student = StudentProfile.objects.create(user=cls.stu_user, registration_number="S001", programme=cls.programme)
        cls.student2 = StudentProfile.objects.create(user=cls.stu2_user, registration_number="S002", programme=cls.programme)
        cls.offering = CourseOffering.objects.create(course=cls.course, semester=cls.semester)
        cls.offering.lecturers.add(cls.lecturer)
        cls.offering2 = CourseOffering.objects.create(course=cls.course2, semester=cls.semester)
        cls.offering2.lecturers.add(cls.lecturer2)


class ModelRuleTests(AcademicFixtureMixin, TestCase):
    def test_only_one_current_academic_year(self):
        y2 = AcademicYear.objects.create(name="2027/2028", start_date=date(2027, 8, 1), end_date=date(2028, 7, 31), is_current=True)
        self.year.refresh_from_db()
        self.assertFalse(self.year.is_current)
        self.assertTrue(y2.is_current)
        self.assertEqual(AcademicYear.objects.filter(is_current=True).count(), 1)

    def test_only_one_current_semester(self):
        s2 = Semester.objects.create(academic_year=self.year, number=2, start_date=date(2027, 1, 11), end_date=date(2027, 5, 28), is_current=True)
        self.semester.refresh_from_db()
        self.assertFalse(self.semester.is_current)
        self.assertTrue(s2.is_current)

    def test_year_and_semester_date_validation(self):
        with self.assertRaises(ValidationError):
            AcademicYear(name="bad", start_date=date(2027, 1, 1), end_date=date(2026, 1, 1)).full_clean()
        outside = Semester(academic_year=self.year, number=2, start_date=date(2027, 6, 1), end_date=date(2027, 9, 1))
        with self.assertRaises(ValidationError) as ctx:
            outside.full_clean()
        self.assertIn("within the academic year", str(ctx.exception))

    def test_duplicate_semester_and_offering_and_enrolment_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Semester.objects.create(academic_year=self.year, number=1, start_date=date(2026, 8, 3), end_date=date(2026, 12, 4))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseOffering.objects.create(course=self.course, semester=self.semester)
        Enrolment.objects.create(student=self.student, offering=self.offering)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrolment.objects.create(student=self.student, offering=self.offering)

    def test_profiles_require_matching_role(self):
        with self.assertRaises(ValidationError):
            StudentProfile(user=self.lec2_user, registration_number="X1", programme=self.programme).full_clean()
        with self.assertRaises(ValidationError):
            LecturerProfile(user=self.stu2_user, staff_number="X2").full_clean()

    def test_programme_with_courses_is_protected_from_deletion(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.programme.delete()


class AccessControlTests(AcademicFixtureMixin, TestCase):
    ADMIN_URLS = [
        "academics:programme_list", "academics:programme_add", "academics:course_list", "academics:course_add",
        "academics:year_list", "academics:year_add", "academics:semester_list", "academics:semester_add",
        "academics:student_list", "academics:student_add", "academics:lecturer_list", "academics:lecturer_add",
        "academics:offering_list", "academics:offering_add", "academics:enrolment_list", "academics:enrolment_add",
    ]

    def test_anonymous_redirected_to_login(self):
        for name in self.ADMIN_URLS + ["academics:my_courses"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn("/login/", resp["Location"])

    def test_only_admin_reaches_management_pages(self):
        for username, expected in [("adm", 200), ("lec1", 403), ("stu1", 403), ("res", 403)]:
            self.client.login(username=username, password=PW)
            for name in self.ADMIN_URLS:
                self.assertEqual(self.client.get(reverse(name)).status_code, expected, f"{username} {name}")
            self.client.logout()

    def test_non_admin_cannot_post_changes(self):
        self.client.login(username="lec1", password=PW)
        resp = self.client.post(reverse("academics:programme_add"), {"code": "X", "name": "Y", "duration_years": 3})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Programme.objects.filter(code="X").exists())
        self.assertEqual(self.client.post(reverse("academics:offering_enrol", args=[self.offering.pk]),
                                          {"students": [self.student.pk]}).status_code, 403)

    def test_student_list_is_not_visible_to_students_or_researchers(self):
        for username in ("stu1", "res"):
            self.client.login(username=username, password=PW)
            self.assertEqual(self.client.get(reverse("academics:student_list")).status_code, 403)
            self.client.logout()

    def test_lecturer_sees_only_assigned_offering_detail(self):
        self.client.login(username="lec1", password=PW)
        self.assertEqual(self.client.get(reverse("academics:offering_detail", args=[self.offering.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("academics:offering_detail", args=[self.offering2.pk])).status_code, 404)

    def test_student_cannot_open_offering_detail(self):
        self.client.login(username="stu1", password=PW)
        self.assertEqual(self.client.get(reverse("academics:offering_detail", args=[self.offering.pk])).status_code, 403)

    def test_my_courses_shows_only_own_courses(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        Enrolment.objects.create(student=self.student2, offering=self.offering2)
        self.client.login(username="stu1", password=PW)
        offerings = list(self.client.get(reverse("academics:my_courses")).context["offerings"])
        self.assertEqual(offerings, [self.offering])
        self.client.login(username="lec2", password=PW)
        self.assertEqual(list(self.client.get(reverse("academics:my_courses")).context["offerings"]), [self.offering2])

    def test_withdrawn_enrolment_not_listed_for_student(self):
        Enrolment.objects.create(student=self.student, offering=self.offering, status=EnrolmentStatus.WITHDRAWN)
        self.client.login(username="stu1", password=PW)
        self.assertEqual(list(self.client.get(reverse("academics:my_courses")).context["offerings"]), [])

    def test_admin_role_can_open_django_admin_academic_models(self):
        # Verifies role-group permissions are synced to administrator users.
        self.client.login(username="adm", password=PW)
        self.assertEqual(self.client.get("/django-admin/academics/programme/").status_code, 200)
        self.client.login(username="lec1", password=PW)
        self.assertEqual(self.client.get("/django-admin/academics/programme/").status_code, 302)

    def test_role_change_moves_user_between_groups(self):
        u = make_user("mover", Role.STUDENT)
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Student"])
        u.role = Role.RESEARCHER
        u.save()
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Researcher"])


class ManagementTests(AcademicFixtureMixin, TestCase):
    def setUp(self):
        self.client.login(username="adm", password=PW)

    def test_create_programme_course_and_audit(self):
        self.client.post(reverse("academics:programme_add"), {"code": "BCS", "name": "Computer Science", "duration_years": 4, "is_active": "on"})
        p = Programme.objects.get(code="BCS")
        resp = self.client.post(reverse("academics:course_add"), {"code": "BCS101", "title": "Algorithms", "programme": p.pk,
                                                                  "year_of_study": 1, "credit_units": 4, "is_active": "on"})
        self.assertRedirects(resp, reverse("academics:course_list"))
        self.assertTrue(Course.objects.filter(code="BCS101").exists())
        self.assertTrue(AuditLog.objects.filter(action="programme_created", target__contains="BCS").exists())
        self.assertTrue(AuditLog.objects.filter(action="course_created").exists())

    def test_validation_messages_shown(self):
        resp = self.client.post(reverse("academics:programme_add"), {"code": "BIT", "name": "Dup", "duration_years": 9})
        self.assertContains(resp, "already exists")
        self.assertContains(resp, "less than or equal to 6")

    def test_semester_form_rejects_dates_outside_year(self):
        resp = self.client.post(reverse("academics:semester_add"), {"academic_year": self.year.pk, "number": 2,
                                                                    "start_date": "2027-08-05", "end_date": "2027-12-01"})
        self.assertContains(resp, "within the academic year")

    def test_register_student_creates_user_and_profile(self):
        data = {"username": "newstu", "first_name": "New", "last_name": "Student", "email": "newstu@example.test",
                "password1": "Valid-Pass-9931", "password2": "Valid-Pass-9931", "registration_number": "S900",
                "programme": self.programme.pk, "year_of_study": 2, "status": "active"}
        resp = self.client.post(reverse("academics:student_add"), data)
        self.assertRedirects(resp, reverse("academics:student_list"))
        user = User.objects.get(username="newstu")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertTrue(user.check_password("Valid-Pass-9931"))
        self.assertEqual(user.student_profile.registration_number, "S900")

    def test_register_student_is_atomic_on_duplicate_registration_number(self):
        data = {"username": "newstu", "first_name": "New", "last_name": "Student", "email": "newstu@example.test",
                "password1": "Valid-Pass-9931", "password2": "Valid-Pass-9931", "registration_number": "S001",
                "programme": self.programme.pk, "year_of_study": 1, "status": "active"}
        resp = self.client.post(reverse("academics:student_add"), data)
        self.assertContains(resp, "already exists")
        self.assertFalse(User.objects.filter(username="newstu").exists())

    def test_register_student_rejects_weak_password_and_duplicate_username(self):
        base = {"username": "stu1", "first_name": "A", "last_name": "B", "email": "ab@example.test", "password1": "12345678",
                "password2": "12345678", "registration_number": "S777", "programme": self.programme.pk, "year_of_study": 1, "status": "active"}
        resp = self.client.post(reverse("academics:student_add"), base)
        self.assertContains(resp, "already exists")
        base["username"] = "fresh"
        resp = self.client.post(reverse("academics:student_add"), base)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="fresh").exists())

    def test_edit_student_updates_profile_and_name_without_password_fields(self):
        url = reverse("academics:student_edit", args=[self.student.pk])
        form = self.client.get(url).context["form"]
        self.assertNotIn("password1", form.fields)
        self.assertNotIn("username", form.fields)
        resp = self.client.post(url, {"first_name": "Renamed", "last_name": "Person", "email": "stu1@example.test",
                                      "registration_number": "S001", "programme": self.programme2.pk, "year_of_study": 3, "status": "active"})
        self.assertRedirects(resp, reverse("academics:student_list"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.programme, self.programme2)
        self.assertEqual(self.student.user.first_name, "Renamed")

    def test_register_lecturer(self):
        data = {"username": "newlec", "first_name": "New", "last_name": "Lecturer", "email": "newlec@example.test",
                "password1": "Valid-Pass-9931", "password2": "Valid-Pass-9931", "staff_number": "L900", "department": "Computing"}
        self.assertRedirects(self.client.post(reverse("academics:lecturer_add"), data), reverse("academics:lecturer_list"))
        self.assertEqual(User.objects.get(username="newlec").role, Role.LECTURER)

    def test_offering_with_lecturers_and_duplicate_rejected(self):
        c3 = Course.objects.create(code="BIT103", title="Databases", programme=self.programme)
        data = {"course": c3.pk, "semester": self.semester.pk, "lecturers": [self.lecturer.pk, self.lecturer2.pk], "is_active": "on"}
        self.assertEqual(self.client.post(reverse("academics:offering_add"), data).status_code, 302)
        self.assertEqual(CourseOffering.objects.get(course=c3).lecturers.count(), 2)
        self.assertContains(self.client.post(reverse("academics:offering_add"), data), "already exists")

    def test_bulk_enrol_and_reactivate_withdrawn(self):
        Enrolment.objects.create(student=self.student2, offering=self.offering, status=EnrolmentStatus.WITHDRAWN)
        url = reverse("academics:offering_enrol", args=[self.offering.pk])
        self.client.post(url, {"students": [self.student.pk, self.student2.pk]})
        self.assertEqual(Enrolment.objects.filter(offering=self.offering, status=EnrolmentStatus.ENROLLED).count(), 2)
        self.assertEqual(Enrolment.objects.filter(offering=self.offering).count(), 2)  # no duplicates
        self.assertTrue(AuditLog.objects.filter(action="students_enrolled").exists())

    def test_bulk_enrol_excludes_inactive_students(self):
        StudentProfile.objects.filter(pk=self.student2.pk).update(status="suspended")
        resp = self.client.post(reverse("academics:offering_enrol", args=[self.offering.pk]), {"students": [self.student2.pk]})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Enrolment.objects.filter(student=self.student2).exists())

    def test_single_enrolment_duplicate_message(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        resp = self.client.post(reverse("academics:enrolment_add"), {"student": self.student.pk, "offering": self.offering.pk,
                                                                     "status": "enrolled", "enrolled_on": "2026-08-10"})
        self.assertContains(resp, "already exists")

    def test_search_filter_pagination(self):
        for i in range(20):
            u = make_user(f"bulk{i:02d}", Role.STUDENT)
            StudentProfile.objects.create(user=u, registration_number=f"B{i:03d}", programme=self.programme2, year_of_study=2)
        url = reverse("academics:student_list")
        self.assertEqual(len(self.client.get(url).context["rows"]), 15)
        self.assertEqual(len(self.client.get(url, {"page": 2}).context["rows"]), 7)  # 22 students
        self.assertEqual(len(self.client.get(url, {"q": "B007"}).context["rows"]), 1)
        self.assertEqual(self.client.get(url, {"programme": self.programme2.pk}).context["paginator"].count, 20)
        self.assertEqual(len(self.client.get(url, {"year": "2", "programme": self.programme.pk}).context["rows"]), 0)
        self.assertEqual(self.client.get(url, {"year": "not-a-number"}).status_code, 200)

    def test_all_list_pages_render_with_data(self):
        Enrolment.objects.create(student=self.student, offering=self.offering)
        for name in AccessControlTests.ADMIN_URLS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("academics:offering_detail", args=[self.offering.pk])), "S001")
