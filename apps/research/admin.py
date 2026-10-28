from django.contrib import admin

from . import models


@admin.register(models.ResearchStudy)
class ResearchStudyAdmin(admin.ModelAdmin):
    """Protocol settings. Administrators may configure these; they cannot see participant data (see below)."""

    list_display = ("title", "status", "is_active", "target_sample_size", "intervention_weeks")


class _ReadOnly(admin.ModelAdmin):
    """Participant-level research data are read-only in Django Admin and visible only to superusers: ordinary
    administrator accounts get no permission on these models. Changes go through the research pages so they are audited."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.OutcomeDefinition)
class OutcomeAdmin(_ReadOnly):
    list_display = ("name", "study", "kind", "source")


@admin.register(models.Participant)
class ParticipantAdmin(_ReadOnly):
    list_display = ("research_code", "study", "eligibility", "consent_status", "group")
    exclude = ("student",)  # the identity link is not shown in Django Admin


@admin.register(models.Allocation)
class AllocationAdmin(_ReadOnly):
    list_display = ("participant", "group", "method", "allocation_date")


@admin.register(models.Measurement)
class MeasurementAdmin(_ReadOnly):
    list_display = ("participant", "outcome", "period", "status")


@admin.register(models.MeasurementRevision)
class MeasurementRevisionAdmin(_ReadOnly):
    list_display = ("measurement", "old_status", "new_status", "changed_at")


@admin.register(models.ParticipantEvent)
class ParticipantEventAdmin(_ReadOnly):
    list_display = ("participant", "event", "at")
