from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "System administrator"
    LECTURER = "lecturer", "Lecturer"
    STUDENT = "student", "Student"
    RESEARCHER = "researcher", "Researcher"


class MiuUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Custom user with exactly one primary role.

    Roles are deliberately exclusive: a researcher does not inherit
    administrator rights (and vice versa). Data-level permissions are
    enforced per role in each app's views.
    """

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)

    objects = MiuUserManager()

    class Meta:
        ordering = ["username"]

    def save(self, *args, **kwargs):
        # Django superusers are always system administrators; the staff flag
        # (access to /django-admin/) follows the administrator role only.
        if self.is_superuser:
            self.role = Role.ADMIN
        self.is_staff = self.is_superuser or self.role == Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_system_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_lecturer(self):
        return self.role == Role.LECTURER

    @property
    def is_student(self):
        return self.role == Role.STUDENT

    @property
    def is_researcher(self):
        return self.role == Role.RESEARCHER

    def display_name(self):
        return self.get_full_name() or self.username

    def __str__(self):
        return f"{self.display_name()} ({self.get_role_display()})"


class AuditLog(models.Model):
    """Append-only record of important administrative and security events."""

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    actor_label = models.CharField(max_length=150, blank=True, help_text="Username kept even if the account is deleted.")
    action = models.CharField(max_length=60, db_index=True)
    target = models.CharField(max_length=255, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.action} {self.target}"
