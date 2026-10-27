from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.HomeRedirectView.as_view(), name="home"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only
    path("password/change/", auth_views.PasswordChangeView.as_view(success_url=reverse_lazy("accounts:password_change_done")), name="password_change"),
    path("password/change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("password/reset/", auth_views.PasswordResetView.as_view(success_url=reverse_lazy("accounts:password_reset_done")), name="password_reset"),
    path("password/reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(success_url=reverse_lazy("accounts:password_reset_complete")), name="password_reset_confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),

    path("dashboard/admin/", views.AdminDashboardView.as_view(), name="dashboard_admin"),
    path("dashboard/lecturer/", views.LecturerDashboardView.as_view(), name="dashboard_lecturer"),
    path("dashboard/student/", views.StudentDashboardView.as_view(), name="dashboard_student"),
    path("dashboard/researcher/", views.ResearcherDashboardView.as_view(), name="dashboard_researcher"),

    path("manage/users/", views.UserListView.as_view(), name="user_list"),
    path("manage/users/add/", views.UserCreateView.as_view(), name="user_add"),
    path("manage/users/<int:pk>/edit/", views.UserUpdateView.as_view(), name="user_edit"),
    path("manage/audit/", views.AuditLogListView.as_view(), name="audit_list"),
]
