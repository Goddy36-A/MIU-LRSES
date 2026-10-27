from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.academics.models import Enrolment, EnrolmentStatus, get_student_profile
from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudListView
from apps.core.scope import offerings_for_staff

from . import forms, services
from .models import Assessment, Assignment, Submission, SubmissionStatus

STAFF = (Role.ADMIN, Role.LECTURER)


def _roster(offering_id):
    return list(Enrolment.objects.filter(offering=offering_id, status=EnrolmentStatus.ENROLLED)
                .select_related("student__user").order_by("student__registration_number"))


def _scoped(model, user, pk):
    """An assignment/assessment of an offering this user manages (administrators: all; lecturers: their own, else 404)."""
    return get_object_or_404(model.objects.select_related("offering__course", "offering__semester")
                             .filter(offering__in=offerings_for_staff(user)), pk=pk)


# ---- Assignments (administrators and lecturers) ------------------------------------------------------------
class AssignmentList(CrudListView):
    allowed_roles = STAFF
    title = "Assignments"
    columns = [("Title", "title"), ("Course", "offering.course.code"),
               ("Deadline", lambda a: timezone.localtime(a.deadline).strftime("%a %d %b %Y %H:%M")),
               ("Max marks", "max_marks"), ("Records complete", "records_complete")]
    search_fields = ("title", "offering__course__code", "offering__course__title")

    @property
    def filters(self):
        return [("offering", "offering_id", "Course offering", [(str(o.pk), str(o)) for o in offerings_for_staff(self.request.user)])]

    add_url, edit_url, detail_url = "performance:assignment_add", "performance:assignment_edit", "performance:assignment_detail"

    def get_queryset(self):
        self.queryset = Assignment.objects.filter(offering__in=offerings_for_staff(self.request.user)).select_related("offering__course")
        return super().get_queryset()


class _ItemFormView(RoleRequiredMixin, View):
    allowed_roles = STAFF
    model = form_class = None
    entity = ""
    list_url = detail_url = ""

    def get_object(self, pk):
        return _scoped(self.model, self.request.user, pk) if pk else None

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        return self.render(self.form_class(instance=obj, user=request.user), obj)

    def post(self, request, pk=None):
        obj = self.get_object(pk)
        form = self.form_class(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            item = form.save(commit=False)
            if obj is None:
                item.created_by = request.user
            item.save()
            log_action(f"{self.entity}_{'updated' if obj else 'created'}", actor=request.user, target=str(item), request=request)
            messages.success(request, f"{self.entity.capitalize()} {'updated' if obj else 'created'}: {item}.")
            return redirect(self.detail_url, pk=item.pk)
        return self.render(form, obj)

    def render(self, form, obj):
        return render(self.request, "crud/form.html", {
            "form": form, "title": f"Edit {self.entity}" if obj else f"Add {self.entity}",
            "submit_label": "Save changes" if obj else f"Create {self.entity}",
            "cancel_url": reverse(self.detail_url, args=[obj.pk]) if obj else reverse(self.list_url)})


class AssignmentFormView(_ItemFormView):
    model, form_class, entity = Assignment, forms.AssignmentForm, "assignment"
    list_url, detail_url = "performance:assignment_list", "performance:assignment_detail"


class AssessmentFormView(_ItemFormView):
    model, form_class, entity = Assessment, forms.AssessmentForm, "assessment"
    list_url, detail_url = "performance:assessment_list", "performance:assessment_detail"


class AssignmentDetail(RoleRequiredMixin, TemplateView):
    allowed_roles = STAFF
    template_name = "performance/assignment_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assignment = _scoped(Assignment, self.request.user, self.kwargs["pk"])
        ctx.update(assignment=assignment, **services.assignment_report(assignment))
        return ctx


class AssignmentRecords(RoleRequiredMixin, View):
    """Record submissions, extensions and marks for every enrolled student on one page."""

    allowed_roles = STAFF
    template_name = "performance/assignment_records.html"

    def _form(self, assignment, data=None):
        return forms.SubmissionRecordsForm(data, assignment=assignment, enrolments=_roster(assignment.offering_id))

    def get(self, request, pk):
        assignment = _scoped(Assignment, request.user, pk)
        return self.render(assignment, self._form(assignment))

    def post(self, request, pk):
        assignment = _scoped(Assignment, request.user, pk)
        form = self._form(assignment, request.POST)
        if form.is_valid():
            try:
                result = services.save_submissions(assignment, request.user, form.records,
                                                   records_complete=form.cleaned_data["records_complete"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"Submission records saved: {result['created']} added, {result['updated']} updated.")
                return redirect("performance:assignment_detail", pk=pk)
        return self.render(assignment, form)

    def render(self, assignment, form):
        return render(self.request, self.template_name, {"assignment": assignment, "form": form, "rows": form.bound_rows()})


# ---- Assessments -------------------------------------------------------------------------------------------
class AssessmentList(CrudListView):
    allowed_roles = STAFF
    title = "Assessments"
    columns = [("Title", "title"), ("Course", "offering.course.code"), ("Type", "get_kind_display"),
               ("Date", "assessment_date"), ("Max marks", "max_marks"), ("Weight %", "weight_percent")]
    search_fields = ("title", "offering__course__code", "offering__course__title")

    @property
    def filters(self):
        return [("offering", "offering_id", "Course offering", [(str(o.pk), str(o)) for o in offerings_for_staff(self.request.user)])]

    add_url, edit_url, detail_url = "performance:assessment_add", "performance:assessment_edit", "performance:assessment_detail"

    def get_queryset(self):
        self.queryset = Assessment.objects.filter(offering__in=offerings_for_staff(self.request.user)).select_related("offering__course")
        return super().get_queryset()


class AssessmentDetail(RoleRequiredMixin, TemplateView):
    allowed_roles = STAFF
    template_name = "performance/assessment_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assessment = _scoped(Assessment, self.request.user, self.kwargs["pk"])
        results = {r.student_id: r for r in assessment.results.select_related("student__user")}
        rows = []
        for e in _roster(assessment.offering_id):
            r = results.get(e.student_id)
            rows.append({"student": e.student, "result": r, "percentage": services.pct(r.marks, assessment.max_marks) if r else None})
        ctx.update(assessment=assessment, rows=rows)
        return ctx


class AssessmentResults(RoleRequiredMixin, View):
    allowed_roles = STAFF
    template_name = "performance/assessment_results.html"

    def _form(self, assessment, data=None):
        return forms.ResultsForm(data, assessment=assessment, enrolments=_roster(assessment.offering_id))

    def get(self, request, pk):
        assessment = _scoped(Assessment, request.user, pk)
        return self.render(assessment, self._form(assessment))

    def post(self, request, pk):
        assessment = _scoped(Assessment, request.user, pk)
        form = self._form(assessment, request.POST)
        if form.is_valid():
            result = services.save_results(assessment, request.user, form.records)
            messages.success(request, f"Results saved: {result['created']} added, {result['updated']} updated.")
            return redirect("performance:assessment_detail", pk=pk)
        return self.render(assessment, form)

    def render(self, assessment, form):
        return render(self.request, self.template_name, {"assessment": assessment, "form": form, "rows": form.bound_rows()})


# ---- Reports -----------------------------------------------------------------------------------------------
class OfferingPerformanceReport(RoleRequiredMixin, TemplateView):
    allowed_roles = STAFF
    template_name = "performance/offering_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        offering = get_object_or_404(offerings_for_staff(self.request.user), pk=self.kwargs["pk"])
        ctx.update(offering=offering, **services.offering_performance_report(offering))
        return ctx


# ---- Students: own deadlines and results only --------------------------------------------------------------
class MyDeadlinesView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.STUDENT,)
    template_name = "performance/my_deadlines.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = get_student_profile(self.request.user)
        ctx["missing_profile"] = profile is None
        upcoming, past = [], []
        if profile:
            now = timezone.now()
            offering_ids = Enrolment.objects.filter(student=profile, status=EnrolmentStatus.ENROLLED).values_list("offering_id", flat=True)
            subs = {s.assignment_id: s for s in Submission.objects.filter(student=profile)}
            for a in Assignment.objects.filter(offering_id__in=list(offering_ids)).select_related("offering__course").order_by("deadline"):
                sub = subs.get(a.pk)
                deadline = sub.effective_deadline if sub else a.deadline
                if sub and sub.status == SubmissionStatus.SUBMITTED:
                    status = "Submitted late" if sub.is_late else "Submitted on time"
                elif sub and sub.status == SubmissionStatus.EXEMPT:
                    status = "Exempt"
                elif deadline > now:
                    status = "Open"
                else:
                    status = "No submission recorded"
                row = {"assignment": a, "deadline": deadline, "extended": bool(sub and sub.extended_deadline), "status": status}
                (upcoming if deadline > now else past).append(row)
        ctx.update(upcoming=upcoming, past=list(reversed(past)))
        return ctx


class MyResultsView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.STUDENT,)
    template_name = "performance/my_results.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = get_student_profile(self.request.user)
        ctx["missing_profile"] = profile is None
        ctx["courses"] = services.student_performance(profile) if profile else []
        ctx["punctuality"] = services.student_punctuality(profile) if profile else None
        return ctx
