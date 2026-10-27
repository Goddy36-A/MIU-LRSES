from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from .audit import log_action
from .forms import UserCreateForm, UserUpdateForm
from .models import AuditLog, Role, User
from .permissions import RoleRequiredMixin

ROLE_DASHBOARD = {
    Role.ADMIN: "accounts:dashboard_admin",
    Role.LECTURER: "accounts:dashboard_lecturer",
    Role.STUDENT: "accounts:dashboard_student",
    Role.RESEARCHER: "accounts:dashboard_researcher",
}


def permission_denied_view(request, exception=None):
    return render(request, "errors/403.html", status=403)


class HomeRedirectView(LoginRequiredMixin, View):
    """Send each signed-in user to the dashboard for their role."""

    def get(self, request):
        return redirect(ROLE_DASHBOARD[request.user.role])


class AdminDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.ADMIN,)
    template_name = "accounts/dashboard_admin.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = {row["role"]: row["n"] for row in User.objects.values("role").annotate(n=Count("id"))}
        ctx["role_counts"] = [(label, counts.get(value, 0)) for value, label in Role.choices]
        ctx["chart_labels"] = [label for label, _ in ctx["role_counts"]]
        ctx["chart_values"] = [n for _, n in ctx["role_counts"]]
        ctx["total_users"] = sum(ctx["chart_values"])
        ctx["active_users"] = User.objects.filter(is_active=True).count()
        ctx["recent_audit"] = AuditLog.objects.select_related("actor")[:8]
        return ctx


class LecturerDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.LECTURER,)
    template_name = "accounts/dashboard_lecturer.html"


class StudentDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.STUDENT,)
    template_name = "accounts/dashboard_student.html"


class ResearcherDashboardView(RoleRequiredMixin, TemplateView):
    allowed_roles = (Role.RESEARCHER,)
    template_name = "accounts/dashboard_researcher.html"


# ---- User management (system administrators only) -------------------------

class UserListView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.ADMIN,)
    model = User
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 15

    def get_queryset(self):
        qs = User.objects.all()
        q = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "")
        status = self.request.GET.get("status", "")
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q)
                           | Q(last_name__icontains=q) | Q(email__icontains=q))
        if role in Role.values:
            qs = qs.filter(role=role)
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx.update(q=self.request.GET.get("q", ""), role_filter=self.request.GET.get("role", ""),
                   status_filter=self.request.GET.get("status", ""), roles=Role.choices,
                   querystring=params.urlencode())
        return ctx


class UserCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (Role.ADMIN,)
    model = User
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action("user_created", actor=self.request.user, target=self.object.username,
                   details=f"role={self.object.role}", request=self.request)
        messages.success(self.request, f"Account '{self.object.username}' created as {self.object.get_role_display()}.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title="Add user", submit_label="Create user")
        return ctx


class UserUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = (Role.ADMIN,)
    model = User
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def form_valid(self, form):
        # Prevent an administrator from locking themselves out.
        if self.object.pk == self.request.user.pk:
            if form.cleaned_data["role"] != Role.ADMIN or not form.cleaned_data["is_active"]:
                form.add_error(None, "You cannot remove your own administrator role or deactivate your own account.")
                return self.form_invalid(form)
        changed = ", ".join(form.changed_data)
        response = super().form_valid(form)
        log_action("user_updated", actor=self.request.user, target=self.object.username,
                   details=f"changed fields: {changed or 'none'}", request=self.request)
        messages.success(self.request, f"Account '{self.object.username}' updated.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title=f"Edit {self.object.username}", submit_label="Save changes")
        return ctx


class AuditLogListView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.ADMIN,)
    model = AuditLog
    template_name = "accounts/audit_list.html"
    context_object_name = "entries"
    paginate_by = 25

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        action = self.request.GET.get("action", "").strip()
        if action:
            qs = qs.filter(action=action)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["actions"] = AuditLog.objects.order_by().values_list("action", flat=True).distinct()
        ctx["action_filter"] = self.request.GET.get("action", "")
        return ctx
