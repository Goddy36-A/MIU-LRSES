from django.contrib import admin

from . import models


class _ReadMostly(admin.ModelAdmin):
    """Marks and submissions are recorded through the main application (audited); the admin site is view-only here."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "offering", "deadline", "max_marks", "weight_percent", "records_complete")
    list_filter = ("records_complete",)
    search_fields = ("title", "offering__course__code")


@admin.register(models.Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("title", "offering", "kind", "assessment_date", "max_marks", "weight_percent")
    list_filter = ("kind",)
    search_fields = ("title", "offering__course__code")


@admin.register(models.Submission)
class SubmissionAdmin(_ReadMostly):
    list_display = ("assignment", "student", "status", "submitted_at", "extended_deadline")
    list_filter = ("status",)


@admin.register(models.AssessmentResult)
class AssessmentResultAdmin(_ReadMostly):
    list_display = ("assessment", "student", "status")
    list_filter = ("status",)
