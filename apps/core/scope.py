"""Shared object-scope helpers so every app applies the same ownership rules."""
from apps.academics.models import CourseOffering, get_lecturer_profile
from apps.accounts.models import Role


def offerings_for_staff(user):
    """Offerings this user may manage: administrators all, a lecturer only those assigned to them,
    everyone else none. Used to scope attendance, assignments, assessments and reports on the server."""
    qs = CourseOffering.objects.select_related("course", "semester__academic_year")
    if user.role == Role.ADMIN:
        return qs
    if user.role == Role.LECTURER:
        profile = get_lecturer_profile(user)
        return qs.filter(lecturers=profile) if profile else qs.none()
    return qs.none()
