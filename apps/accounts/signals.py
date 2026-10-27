from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .audit import log_action
from .models import Role

ROLE_GROUPS = {
    Role.ADMIN: "System Administrator",
    Role.LECTURER: "Lecturer",
    Role.STUDENT: "Student",
    Role.RESEARCHER: "Researcher",
}

# Model permissions granted to each role group. Later phases extend this map.
# Researchers and lecturers get none on accounts models.
ROLE_PERMISSIONS = {
    Role.ADMIN: [("accounts", ["add_user", "change_user", "view_user", "view_auditlog"])],
}


@receiver(post_migrate)
def ensure_role_groups(sender, **kwargs):
    if sender.label != "accounts":
        return
    for role, name in ROLE_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        for app_label, codenames in ROLE_PERMISSIONS.get(role, []):
            perms = Permission.objects.filter(content_type__app_label=app_label, codename__in=codenames)
            group.permissions.add(*perms)


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
