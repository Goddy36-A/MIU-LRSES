from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.academics.models import Enrolment, EnrolmentStatus, StudentProfile, get_student_profile
from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.scope import offerings_for_staff
from apps.timetables.models import LectureSession, SessionStatus

from . import services
from .forms import AttendanceMarkForm, AttendanceRulesForm
from .models import AttendanceChange, AttendanceRules


def scoped_session(user, pk):
    """A lecture the user may record attendance for: administrators any, lecturers only their offerings (else 404)."""
    qs = LectureSession.objects.select_related("offering__course", "offering__semester", "venue", "lecturer__user")
    return get_object_or_404(qs.filter(offering__in=offerings_for_staff(user)), pk=pk)


class MarkAttendanceView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.LECTURER)
    template_name = "attendance/mark.html"

    def _form(self, session, data=None):
        return AttendanceMarkForm(data, session=session, enrolments=list(services.roster(session)))

    def get(self, request, pk):
        session = scoped_session(request.user, pk)
        return self.render(session, self._form(session))

    def post(self, request, pk):
        session = scoped_session(request.user, pk)
        form = self._form(session, request.POST)
        if form.is_valid():
            try:
                result = services.save_attendance(session, request.user, form.statuses(), reason=form.cleaned_data["reason"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"Attendance saved: {result['created']} recorded, {result['corrected']} corrected, "
                                          f"{result['unchanged']} unchanged.")
                return redirect("attendance:mark", pk=pk)
        return self.render(session, form)

    def render(self, session, form):
        try:
            services.check_session_open(session)
            closed_reason = ""
        except ValidationError as exc:
            closed_reason = exc.messages[0]
        history = AttendanceChange.objects.filter(record__session=session).select_related("record__student__user", "changed_by")
        return render(self.request, self.template_name, {
            "session": session, "form": form, "rows": form.bound_rows(), "closed_reason": closed_reason,
            "history": history[:50], "counts": services.session_counts(session)})


class MyAttendanceView(RoleRequiredMixin, TemplateView):
    """A student's own attendance (never anyone else's)."""

    allowed_roles = (Role.STUDENT,)
    template_name = "attendance/my_attendance.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = get_student_profile(self.request.user)
        ctx["missing_profile"] = profile is None
        if profile:
            ctx.update(services.student_report(profile), rules=AttendanceRules.get())
        return ctx


class StudentAttendanceReport(RoleRequiredMixin, TemplateView):
    """Student-level report for staff. A lecturer sees only the courses they teach."""

    allowed_roles = (Role.ADMIN, Role.LECTURER)
    template_name = "attendance/student_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        student = get_object_or_404(StudentProfile.objects.select_related("user", "programme"), pk=self.kwargs["pk"])
        allowed = offerings_for_staff(self.request.user)
        enrolments = Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED, offering__in=allowed)
        if self.request.user.role == Role.LECTURER and not enrolments.exists():
            from django.http import Http404
            raise Http404("No such student in your courses.")
        rules = AttendanceRules.get()
        enrolments = list(enrolments.select_related("offering__course", "offering__semester__academic_year"))
        ctx.update(student=student, rules=rules,
                   by_offering=[(e.offering, services.student_summary(student, offering=e.offering, rules=rules, enrolments=[e]))
                                for e in enrolments],
                   overall=services.student_summary(student, rules=rules, enrolments=enrolments))
        return ctx


class OfferingAttendanceReport(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.ADMIN, Role.LECTURER)
    template_name = "attendance/offering_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        offering = get_object_or_404(offerings_for_staff(self.request.user), pk=self.kwargs["pk"])
        report = services.offering_report(offering)
        rows = report["students"]
        ctx.update(offering=offering, **report,
                   chart_labels=[r["student"].registration_number for r in rows if r["summary"].rate is not None],
                   chart_values=[r["summary"].rate for r in rows if r["summary"].rate is not None])
        return ctx


class AttendanceRulesView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN,)

    def get(self, request):
        return self.render(AttendanceRulesForm(instance=AttendanceRules.get()))

    def post(self, request):
        rules = AttendanceRules.get()
        form = AttendanceRulesForm(request.POST, instance=rules)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            log_action("attendance_rules_updated", actor=request.user, target="attendance rules",
                       details=f"late_counts_as_attended={obj.late_counts_as_attended}, excused_policy={obj.excused_policy}",
                       request=request)
            messages.success(request, "Attendance calculation rules saved. Reports use them immediately.")
            return redirect("attendance:rules")
        return self.render(form)

    def render(self, form):
        return render(self.request, "crud/form.html", {
            "form": form, "title": "Attendance calculation rules", "submit_label": "Save rules",
            "cancel_url": reverse("accounts:dashboard_admin")})
