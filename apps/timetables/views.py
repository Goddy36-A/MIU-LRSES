from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.academics.models import CourseOffering, Semester, get_lecturer_profile
from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView

from . import forms, services
from .models import LectureSession, SessionStatus, Venue


# ---- Venues (administrators) ----------------------------------------------
class VenueList(CrudListView):
    model = Venue
    title = "Lecture venues"
    columns = [("Name", "name"), ("Building", "building"), ("Capacity", "capacity"), ("Active", "is_active")]
    search_fields = ("name", "building")
    filters = [("active", "is_active", "Status", [("1", "Active"), ("0", "Inactive")])]
    add_url, edit_url = "timetables:venue_add", "timetables:venue_edit"


class VenueCreate(CrudCreateView):
    model, form_class, title, entity = Venue, forms.VenueForm, "Add venue", "venue"
    success_url = reverse_lazy("timetables:venue_list")


class VenueUpdate(CrudUpdateView):
    model, form_class, title, entity = Venue, forms.VenueForm, "Edit venue", "venue"
    success_url = reverse_lazy("timetables:venue_list")


# ---- Lectures (administrators and lecturers) ------------------------------
class SessionScopeMixin:
    """Administrators see every lecture; a lecturer only lectures of offerings assigned to them."""

    allowed_roles = (Role.ADMIN, Role.LECTURER)

    def scoped_sessions(self):
        user = self.request.user
        if user.role == Role.ADMIN:
            return LectureSession.objects.select_related("offering__course", "offering__semester", "venue", "lecturer__user")
        return services.sessions_for_lecturer(get_lecturer_profile(user))

    def lecturer_profile(self):
        return get_lecturer_profile(self.request.user) if self.request.user.role == Role.LECTURER else None


class SessionList(SessionScopeMixin, CrudListView):
    allowed_roles = (Role.ADMIN, Role.LECTURER)
    title = "Lectures"
    columns = [("Course", lambda s: s.offering.course.code),
               ("Date", lambda s: timezone.localtime(s.start_at).strftime("%a %d %b %Y")),
               ("Time", lambda s: f"{timezone.localtime(s.start_at):%H:%M}-{timezone.localtime(s.end_at):%H:%M}"),
               ("Venue", "venue.name"), ("Lecturer", "lecturer.user.display_name"), ("Status", "get_status_display")]
    search_fields = ("offering__course__code", "offering__course__title", "topic", "venue__name")
    filters = [("semester", "offering__semester_id", "Semester", lambda: [(str(s.pk), str(s)) for s in Semester.objects.select_related("academic_year")]),
               ("venue", "venue_id", "Venue", lambda: [(str(v.pk), v.name) for v in Venue.objects.all()]),
               ("status", "status", "Status", SessionStatus.choices),
               ("from", "start_at__date__gte", "From date", None),
               ("to", "start_at__date__lte", "To date", None)]
    add_url, edit_url, detail_url = "timetables:session_add", "timetables:session_edit", "timetables:session_detail"

    def get_queryset(self):
        self.queryset = self.scoped_sessions()
        return super().get_queryset()


class SessionCreate(SessionScopeMixin, RoleRequiredMixin, View):
    template_name = "timetables/session_form.html"

    def get(self, request):
        return self.render(forms.LectureSessionForm(user=request.user, lecturer_profile=self.lecturer_profile()))

    def post(self, request):
        form = forms.LectureSessionForm(request.POST, user=request.user, lecturer_profile=self.lecturer_profile())
        if form.is_valid():
            session = services.create_session(form.instance, request.user)
            messages.success(request, f"Lecture scheduled: {session}.")
            return redirect("timetables:session_detail", pk=session.pk)
        return self.render(form)

    def render(self, form):
        return render(self.request, self.template_name, {"form": form, "title": "Schedule a lecture", "submit_label": "Schedule lecture",
                                                         "cancel_url": reverse("timetables:session_list"), "show_conflict_hint": True})


class SessionObjectMixin(SessionScopeMixin):
    def get_session(self):
        return get_object_or_404(self.scoped_sessions(), pk=self.kwargs["pk"])


class SessionDetail(SessionObjectMixin, RoleRequiredMixin, TemplateView):
    template_name = "timetables/session_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.reminders.services import session_summary  # local import: reminders depends on timetables
        session = self.get_session()
        ctx.update(session=session, changes=session.changes.select_related("changed_by"),
                   cancel_form=forms.CancelForm(), can_modify=not session.is_cancelled,
                   reminder_summary=session_summary(session))
        return ctx


class SessionEdit(SessionObjectMixin, RoleRequiredMixin, View):
    def get(self, request, pk):
        session = self.get_session()
        return self.render(forms.LectureSessionForm(instance=session, user=request.user, lecturer_profile=self.lecturer_profile()), session)

    def post(self, request, pk):
        session = self.get_session()
        if session.is_cancelled:
            raise PermissionDenied("Cancelled lectures cannot be edited.")
        form = forms.LectureSessionForm(request.POST, instance=session, user=request.user, lecturer_profile=self.lecturer_profile())
        if form.is_valid():
            form.save()
            log_action("lecture_updated", actor=request.user, target=str(session), request=request)
            messages.success(request, "Lecture details updated.")
            return redirect("timetables:session_detail", pk=pk)
        return self.render(form, session)

    def render(self, form, session):
        return render(self.request, "timetables/session_form.html", {
            "form": form, "title": f"Edit lecture: {session}", "submit_label": "Save changes",
            "cancel_url": reverse("timetables:session_detail", args=[session.pk])})


class SessionReschedule(SessionObjectMixin, RoleRequiredMixin, View):
    def get(self, request, pk):
        session = self.get_session()
        if session.is_cancelled:
            messages.error(request, "A cancelled lecture cannot be rescheduled.")
            return redirect("timetables:session_detail", pk=pk)
        return self.render(forms.RescheduleForm(session=session, user=request.user), session)

    def post(self, request, pk):
        session = self.get_session()
        form = forms.RescheduleForm(request.POST, session=session, user=request.user)
        if session.is_cancelled:
            messages.error(request, "A cancelled lecture cannot be rescheduled.")
            return redirect("timetables:session_detail", pk=pk)
        if form.is_valid():
            try:
                form.save()
            except ValidationError as exc:  # state changed between validation and save
                form.add_error(None, exc.messages)
                return self.render(form, session)
            messages.success(request, "Lecture rescheduled. The change is recorded in its history.")
            return redirect("timetables:session_detail", pk=pk)
        return self.render(form, session)

    def render(self, form, session):
        return render(self.request, "timetables/session_form.html", {
            "form": form, "title": f"Reschedule: {session}", "submit_label": "Reschedule lecture",
            "cancel_url": reverse("timetables:session_detail", args=[session.pk])})


class SessionCancel(SessionObjectMixin, RoleRequiredMixin, View):
    def post(self, request, pk):
        session = self.get_session()
        form = forms.CancelForm(request.POST)
        if form.is_valid():
            try:
                services.cancel_session(session, request.user, reason=form.cleaned_data["reason"])
                messages.success(request, "Lecture cancelled.")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
        else:
            messages.error(request, "Please give a reason for cancelling the lecture.")
        return redirect("timetables:session_detail", pk=pk)


# ---- Student timetable ------------------------------------------------------
class MyTimetableView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.STUDENT,)
    template_name = "timetables/my_timetable.html"
    paginate_by = 30
    context_object_name = "sessions"

    def get_queryset(self):
        qs = services.sessions_for_student(self.request.user)
        self.when = "past" if self.request.GET.get("when") == "past" else "upcoming"
        now = timezone.now()
        if self.when == "past":
            return qs.filter(end_at__lt=now).order_by("-start_at")
        return qs.filter(end_at__gte=now).order_by("start_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.academics.models import get_student_profile
        ctx.update(when=self.when, missing_profile=get_student_profile(self.request.user) is None)
        return ctx
