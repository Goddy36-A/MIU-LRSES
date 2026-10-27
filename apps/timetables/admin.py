from django.contrib import admin

from . import models


@admin.register(models.Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "building", "capacity", "is_active")
    search_fields = ("name", "building")


@admin.register(models.LectureSession)
class LectureSessionAdmin(admin.ModelAdmin):
    list_display = ("offering", "start_at", "end_at", "venue", "lecturer", "status")
    list_filter = ("status", "venue")
    date_hierarchy = "start_at"
    # Schedule changes should go through the main application so history and (later) reminders stay correct.
    readonly_fields = ("status", "cancellation_reason", "created_by")

    def get_readonly_fields(self, request, obj=None):
        base = super().get_readonly_fields(request, obj)
        if obj:  # existing lectures: times/venue/lecturer change only via Reschedule in the main app
            return base + ("offering", "lecturer", "venue", "start_at", "end_at")
        return base


@admin.register(models.LectureChange)
class LectureChangeAdmin(admin.ModelAdmin):
    list_display = ("session", "change_type", "changed_by", "changed_at")
    list_filter = ("change_type",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
