from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView

from . import forms, services
from .models import (Notification, NotificationKind, NotificationStatus, ReminderConfig, ReminderInterval,
                     ReminderRun, RunStatus)


# ---- Recipient views: every signed-in user sees only their own delivered notifications ----------
class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "reminders/notification_list.html"
    paginate_by = 15
    context_object_name = "notifications"

    def get_queryset(self):
        self.show = "unread" if self.request.GET.get("show") == "unread" else "all"
        qs = services.inbox_for(self.request.user)
        return qs.filter(read_at__isnull=True) if self.show == "unread" else qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx.update(show=self.show, unread=services.unread_count(self.request.user), querystring=params.urlencode())
        return ctx


def _safe_next(request, default):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


class MarkReadView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        # Filtering on recipient makes another user's notification a 404, never readable or changeable.
        notification = get_object_or_404(services.inbox_for(request.user), pk=pk)
        notification.mark_read()
        return redirect(_safe_next(request, reverse("reminders:notifications")))


class MarkAllReadView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        n = services.inbox_for(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
        messages.success(request, f"{n} notification{'s' if n != 1 else ''} marked as read." if n else "No unread notifications.")
        return redirect(_safe_next(request, reverse("reminders:notifications")))


class UnreadCountView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        return JsonResponse({"unread": services.unread_count(request.user)})


# ---- Administrator views ---------------------------------------------------------------------------------
class OverviewView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.ADMIN,)
    template_name = "reminders/overview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = {r["status"]: r["n"] for r in Notification.objects.filter(kind=NotificationKind.REMINDER)
                  .order_by().values("status").annotate(n=Count("id"))}
        ctx.update(config=ReminderConfig.get(), intervals=ReminderInterval.objects.all(),
                   status_counts=[(label, counts.get(value, 0), value) for value, label in NotificationStatus.choices],
                   last_run=ReminderRun.objects.first(), recent_runs=ReminderRun.objects.all()[:5])
        return ctx


class ConfigUpdate(CrudUpdateView):
    model, form_class = ReminderConfig, forms.ReminderConfigForm
    title, entity = "Reminder settings", "reminder_settings"
    success_url = reverse_lazy("reminders:overview")

    def get_object(self, queryset=None):
        return ReminderConfig.get()

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)


class IntervalCreate(CrudCreateView):
    model, form_class = ReminderInterval, forms.ReminderIntervalForm
    title, entity = "Add reminder interval", "reminder_interval"
    success_url = reverse_lazy("reminders:overview")


class IntervalUpdate(CrudUpdateView):
    model, form_class = ReminderInterval, forms.ReminderIntervalForm
    title, entity = "Edit reminder interval", "reminder_interval"
    success_url = reverse_lazy("reminders:overview")


class QueueList(CrudListView):
    title = "Scheduled reminders and notices"
    subtitle = "Every reminder the engine has scheduled, with its processing status."
    model = Notification
    columns = [("Recipient", "recipient.display_name"), ("Type", "get_kind_display"),
               ("Lecture", lambda n: f"{n.session.offering.course.code} {timezone.localtime(n.session.start_at):%d %b %H:%M}"),
               ("Interval", lambda n: n.interval.display if n.interval_id else "-"),
               ("Due", lambda n: f"{timezone.localtime(n.scheduled_for):%d %b %Y %H:%M}"),
               ("Status", "get_status_display"), ("Read", lambda n: "Yes" if n.read_at else "No"),
               ("Detail", "status_detail")]
    search_fields = ("recipient__username", "recipient__first_name", "recipient__last_name", "session__offering__course__code")
    search_help = "Student name, username or course code"
    filters = [("status", "status", "Status", NotificationStatus.choices), ("kind", "kind", "Type", NotificationKind.choices),
               ("interval", "interval_id", "Interval", lambda: [(str(i.pk), i.display) for i in ReminderInterval.objects.all()]),
               ("from", "scheduled_for__date__gte", "Due from", None), ("to", "scheduled_for__date__lte", "Due to", None)]
    select_related = ("recipient", "session__offering__course", "interval")


class RunList(CrudListView):
    title = "Reminder processing runs"
    subtitle = "A record of every execution of process_reminders."
    model = ReminderRun
    columns = [("Started", lambda r: f"{timezone.localtime(r.started_at):%d %b %Y %H:%M:%S}"), ("By", lambda r: r.triggered_by.username if r.triggered_by_id else r.get_trigger_display()),
               ("Status", "get_status_display"), ("Due", "due_found"), ("Delivered", "delivered"), ("Expired", "expired"),
               ("Cancelled", "cancelled"), ("Failed", "failed"), ("Scheduled by sync", "sync_created"), ("Notes", "notes")]
    filters = [("status", "status", "Status", RunStatus.choices)]
    select_related = ("triggered_by",)


class RunNowView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN,)
    http_method_names = ["post"]

    def post(self, request):
        run = services.process_due_reminders(trigger="admin", user=request.user)
        log_action("reminders_processed", actor=request.user, target=f"run {run.pk}",
                   details=f"status={run.status} delivered={run.delivered} failed={run.failed}", request=request)
        if run.status == RunStatus.DISABLED:
            messages.warning(request, run.notes)
        elif run.failed:
            messages.error(request, f"Processed with errors: {run.delivered} delivered, {run.failed} failed. See the processing runs.")
        else:
            messages.success(request, f"Processed: {run.due_found} due, {run.delivered} delivered, "
                                      f"{run.expired} expired, {run.cancelled} cancelled.")
        return redirect("reminders:overview")
