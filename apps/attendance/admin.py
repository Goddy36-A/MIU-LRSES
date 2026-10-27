from django.contrib import admin

from . import models


@admin.register(models.AttendanceRules)
class AttendanceRulesAdmin(admin.ModelAdmin):
    list_display = ("__str__", "late_counts_as_attended", "excused_policy", "updated_at")

    def has_add_permission(self, request):
        return not models.AttendanceRules.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    """Read-only here: attendance is recorded and corrected through the main application so every change is audited."""

    list_display = ("session", "student", "status", "recorded_by", "updated_at")
    list_filter = ("status",)
    search_fields = ("student__registration_number", "session__offering__course__code")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.AttendanceChange)
class AttendanceChangeAdmin(admin.ModelAdmin):
    list_display = ("record", "old_status", "new_status", "changed_by", "changed_at")
    list_filter = ("new_status",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
