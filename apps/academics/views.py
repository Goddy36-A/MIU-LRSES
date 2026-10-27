from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView

from . import forms
from .models import (AcademicYear, Course, CourseOffering, Enrolment, EnrolmentStatus, LecturerProfile, Programme,
                     Semester, StudentProfile, StudentStatus, get_lecturer_profile, get_student_profile)

YEARS = [(str(i), f"Year {i}") for i in range(1, 7)]
YES_NO = [("1", "Yes"), ("0", "No")]


def _choices(model, label=str):
    return lambda: [(str(o.pk), label(o)) for o in model.objects.all()]


# ---- Programmes ------------------------------------------------------------
class ProgrammeList(CrudListView):
    model = Programme
    title = "Programmes"
    columns = [("Code", "code"), ("Name", "name"), ("Years", "duration_years"), ("Active", "is_active")]
    search_fields = ("code", "name")
    filters = [("active", "is_active", "Status", [("1", "Active"), ("0", "Inactive")])]
    add_url, edit_url = "academics:programme_add", "academics:programme_edit"


class ProgrammeCreate(CrudCreateView):
    model, form_class, title, entity = Programme, forms.ProgrammeForm, "Add programme", "programme"
    success_url = reverse_lazy("academics:programme_list")


class ProgrammeUpdate(CrudUpdateView):
    model, form_class, title, entity = Programme, forms.ProgrammeForm, "Edit programme", "programme"
    success_url = reverse_lazy("academics:programme_list")


# ---- Courses ---------------------------------------------------------------
class CourseList(CrudListView):
    model = Course
    title = "Courses"
    columns = [("Code", "code"), ("Title", "title"), ("Programme", "programme.code"), ("Year", "year_of_study"),
               ("Credits", "credit_units"), ("Active", "is_active")]
    search_fields = ("code", "title")
    select_related = ("programme",)
    filters = [("programme", "programme_id", "Programme", _choices(Programme, lambda p: p.code)),
               ("year", "year_of_study", "Year of study", YEARS),
               ("active", "is_active", "Status", [("1", "Active"), ("0", "Inactive")])]
    add_url, edit_url = "academics:course_add", "academics:course_edit"


class CourseCreate(CrudCreateView):
    model, form_class, title, entity = Course, forms.CourseForm, "Add course", "course"
    success_url = reverse_lazy("academics:course_list")


class CourseUpdate(CrudUpdateView):
    model, form_class, title, entity = Course, forms.CourseForm, "Edit course", "course"
    success_url = reverse_lazy("academics:course_list")


# ---- Academic years and semesters -----------------------------------------
class YearList(CrudListView):
    model = AcademicYear
    title = "Academic years"
    columns = [("Name", "name"), ("Starts", "start_date"), ("Ends", "end_date"), ("Current", "is_current")]
    search_fields = ("name",)
    add_url, edit_url = "academics:year_add", "academics:year_edit"


class YearCreate(CrudCreateView):
    model, form_class, title, entity = AcademicYear, forms.AcademicYearForm, "Add academic year", "academic_year"
    success_url = reverse_lazy("academics:year_list")


class YearUpdate(CrudUpdateView):
    model, form_class, title, entity = AcademicYear, forms.AcademicYearForm, "Edit academic year", "academic_year"
    success_url = reverse_lazy("academics:year_list")


class SemesterList(CrudListView):
    model = Semester
    title = "Semesters"
    columns = [("Semester", lambda s: str(s)), ("Starts", "start_date"), ("Ends", "end_date"), ("Current", "is_current")]
    select_related = ("academic_year",)
    filters = [("year", "academic_year_id", "Academic year", _choices(AcademicYear))]
    add_url, edit_url = "academics:semester_add", "academics:semester_edit"


class SemesterCreate(CrudCreateView):
    model, form_class, title, entity = Semester, forms.SemesterForm, "Add semester", "semester"
    success_url = reverse_lazy("academics:semester_list")


class SemesterUpdate(CrudUpdateView):
    model, form_class, title, entity = Semester, forms.SemesterForm, "Edit semester", "semester"
    success_url = reverse_lazy("academics:semester_list")


# ---- Students and lecturers ------------------------------------------------
class StudentList(CrudListView):
    model = StudentProfile
    title = "Students"
    columns = [("Reg. number", "registration_number"), ("Name", "user.display_name"), ("Email", "user.email"),
               ("Programme", "programme.code"), ("Year", "year_of_study"), ("Status", "get_status_display")]
    search_fields = ("registration_number", "user__username", "user__first_name", "user__last_name", "user__email")
    search_help = "Registration number, name, username or email"
    select_related = ("user", "programme")
    filters = [("programme", "programme_id", "Programme", _choices(Programme, lambda p: p.code)),
               ("year", "year_of_study", "Year of study", YEARS),
               ("status", "status", "Status", StudentStatus.choices)]
    add_url, edit_url = "academics:student_add", "academics:student_edit"


class StudentCreate(CrudCreateView):
    model, form_class, title, entity = StudentProfile, forms.StudentRegistrationForm, "Register student", "student"
    success_url = reverse_lazy("academics:student_list")
    submit_label = "Register student"


class StudentUpdate(CrudUpdateView):
    model, form_class, title, entity = StudentProfile, forms.StudentRegistrationForm, "Edit student", "student"
    success_url = reverse_lazy("academics:student_list")


class LecturerList(CrudListView):
    model = LecturerProfile
    title = "Lecturers"
    columns = [("Staff number", "staff_number"), ("Name", "user.display_name"), ("Email", "user.email"),
               ("Department", "department")]
    search_fields = ("staff_number", "user__username", "user__first_name", "user__last_name", "department")
    select_related = ("user",)
    add_url, edit_url = "academics:lecturer_add", "academics:lecturer_edit"


class LecturerCreate(CrudCreateView):
    model, form_class, title, entity = LecturerProfile, forms.LecturerRegistrationForm, "Register lecturer", "lecturer"
    success_url = reverse_lazy("academics:lecturer_list")
    submit_label = "Register lecturer"


class LecturerUpdate(CrudUpdateView):
    model, form_class, title, entity = LecturerProfile, forms.LecturerRegistrationForm, "Edit lecturer", "lecturer"
    success_url = reverse_lazy("academics:lecturer_list")


# ---- Course offerings and enrolment ---------------------------------------
class OfferingList(CrudListView):
    model = CourseOffering
    title = "Course offerings"
    subtitle = "A course taught in a semester. Open one to see its lecturers, students and lectures."
    columns = [("Course", lambda o: f"{o.course.code} - {o.course.title}"), ("Semester", lambda o: str(o.semester)),
               ("Lecturers", lambda o: ", ".join(l.user.display_name() for l in o.lecturers.all()) or None),
               ("Students", lambda o: o.enrolled_total), ("Active", "is_active")]
    search_fields = ("course__code", "course__title")
    select_related = ("course", "semester__academic_year")
    filters = [("semester", "semester_id", "Semester", _choices(Semester)),
               ("active", "is_active", "Status", [("1", "Active"), ("0", "Inactive")])]
    add_url, edit_url, detail_url = "academics:offering_add", "academics:offering_edit", "academics:offering_detail"

    def get_queryset(self):
        return (super().get_queryset().prefetch_related("lecturers__user")
                .annotate(enrolled_total=Count("enrolments", filter=Q(enrolments__status=EnrolmentStatus.ENROLLED)))
                .order_by("-semester__start_date", "course__code"))


class OfferingCreate(CrudCreateView):
    model, form_class, title, entity = CourseOffering, forms.CourseOfferingForm, "Add course offering", "course_offering"
    success_url = reverse_lazy("academics:offering_list")


class OfferingUpdate(CrudUpdateView):
    model, form_class, title, entity = CourseOffering, forms.CourseOfferingForm, "Edit course offering", "course_offering"
    success_url = reverse_lazy("academics:offering_list")


class OfferingDetail(RoleRequiredMixin, TemplateView):
    """Roster and lectures for one offering. Admin sees all; a lecturer only their assigned offerings."""

    allowed_roles = (Role.ADMIN, Role.LECTURER)
    template_name = "academics/offering_detail.html"

    def get_offering(self):
        qs = CourseOffering.objects.select_related("course__programme", "semester__academic_year")
        if self.request.user.role == Role.LECTURER:
            profile = get_lecturer_profile(self.request.user)
            qs = qs.filter(lecturers=profile) if profile else qs.none()
        return get_object_or_404(qs, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        offering = self.get_offering()
        ctx.update(
            offering=offering,
            lecturers=offering.lecturers.select_related("user"),
            enrolments=offering.enrolments.select_related("student__user", "student__programme"),
            sessions=offering.sessions.select_related("venue", "lecturer__user").order_by("start_at")[:50],
            bulk_form=forms.BulkEnrolForm(offering=offering) if self.request.user.role == Role.ADMIN else None,
            is_admin=self.request.user.role == Role.ADMIN,
        )
        return ctx


class BulkEnrolView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN,)

    def post(self, request, pk):
        offering = get_object_or_404(CourseOffering, pk=pk)
        form = forms.BulkEnrolForm(request.POST, offering=offering)
        if form.is_valid():
            count = form.save()
            log_action("students_enrolled", actor=request.user, target=str(offering), details=f"{count} student(s)", request=request)
            messages.success(request, f"{count} student(s) enrolled in {offering}.")
        else:
            messages.error(request, "Select at least one valid student to enrol.")
        return redirect("academics:offering_detail", pk=pk)


class EnrolmentList(CrudListView):
    model = Enrolment
    title = "Enrolments"
    columns = [("Student", lambda e: f"{e.student.registration_number} - {e.student.user.display_name()}"),
               ("Offering", lambda e: str(e.offering)), ("Status", "get_status_display"), ("Enrolled on", "enrolled_on")]
    search_fields = ("student__registration_number", "student__user__last_name", "student__user__first_name", "offering__course__code")
    select_related = ("student__user", "offering__course", "offering__semester__academic_year")
    filters = [("offering", "offering_id", "Offering", _choices(CourseOffering)),
               ("status", "status", "Status", EnrolmentStatus.choices)]
    add_url, edit_url = "academics:enrolment_add", "academics:enrolment_edit"


class EnrolmentCreate(CrudCreateView):
    model, form_class, title, entity = Enrolment, forms.EnrolmentForm, "Add enrolment", "enrolment"
    success_url = reverse_lazy("academics:enrolment_list")


class EnrolmentUpdate(CrudUpdateView):
    model, form_class, title, entity = Enrolment, forms.EnrolmentForm, "Edit enrolment", "enrolment"
    success_url = reverse_lazy("academics:enrolment_list")


# ---- Personal course lists --------------------------------------------------
class MyCoursesView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.STUDENT, Role.LECTURER)
    template_name = "academics/my_courses.html"
    context_object_name = "offerings"
    paginate_by = 15

    def get_queryset(self):
        base = CourseOffering.objects.select_related("course", "semester__academic_year").prefetch_related("lecturers__user")
        if self.request.user.role == Role.STUDENT:
            profile = get_student_profile(self.request.user)
            return base.filter(enrolments__student=profile, enrolments__status=EnrolmentStatus.ENROLLED) if profile else base.none()
        profile = get_lecturer_profile(self.request.user)
        return base.filter(lecturers=profile) if profile else base.none()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["is_lecturer"] = user.role == Role.LECTURER
        profile = get_lecturer_profile(user) if ctx["is_lecturer"] else get_student_profile(user)
        ctx["missing_profile"] = profile is None
        return ctx
