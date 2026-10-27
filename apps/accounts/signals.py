from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .audit import log_action
from .models import Role, User

ROLE_GROUPS = {
    Role.ADMIN: "System Administrator",
    Role.LECTURER: "Lecturer",
    Role.STUDENT: "Student",
    Role.RESEARCHER: "Researcher",
}

# Model permissions (for Django Admin) granted to each role group. Application pages enforce
# access by role in the views; these permissions only govern /django-admin/, which only
# administrators can open. Lecturers, students and researchers receive none.
ADMIN_ADMIN_APPS = ("academics", "timetables", "reminders")


def _admin_permissions():
    perms = Permission.objects.filter(
        content_type__app_label="accounts", codename__in=["add_user", "change_user", "view_user", "view_auditlog"])
    for app_label in ADMIN_ADMIN_APPS:
        for prefix in ("add_", "change_", "view_"):
            perms = perms | Permission.objects.filter(content_type__app_label=app_label, codename__startswith=prefix)
    return perms


@receiver(post_migrate)
def ensure_role_groups(sender, **kwargs):
    # Runs after every app's migrate step so permissions of later apps are picked up (idempotent).
    groups = {role: Group.objects.get_or_create(name=name)[0] for role, name in ROLE_GROUPS.items()}
    groups[Role.ADMIN].permissions.add(*_admin_permissions())


@receiver(post_save, sender=User)
def sync_role_group(sender, instance, raw=False, **kwargs):
    """Keep each user in exactly one role group, matching User.role."""
    if raw:
        return
    group, _ = Group.objects.get_or_create(name=ROLE_GROUPS[instance.role])
    stale = instance.groups.filter(name__in=ROLE_GROUPS.values()).exclude(pk=group.pk)
    if stale.exists():
        instance.groups.remove(*stale)
    instance.groups.add(group)


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_action("login", actor=user, target=user.username, request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log_action("logout", actor=user, target=user.username, request=request)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    # Record the attempted username only, never the password.
    log_action("login_failed", target=credentials.get("username", ""), request=request)
