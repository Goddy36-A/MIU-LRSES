from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.ReminderInterval)
class ReminderIntervalAdmin(admin.ModelAdmin):
    list_display = ("display", "minutes_before", "is_active")

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead: delivered reminders refer to the interval


@admin.register(models.ReminderConfig)
class ReminderConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "reminders_enabled", "updated_at")

    def has_add_permission(self, request):
        return not models.ReminderConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("recipient", "kind", "session", "scheduled_for", "status", "read_at")
    list_filter = ("kind", "status", "interval")
    search_fields = ("recipient__username", "session__offering__course__code")
    date_hierarchy = "scheduled_for"


@admin.register(models.ReminderRun)
class ReminderRunAdmin(ReadOnlyAdmin):
    list_display = ("started_at", "trigger", "status", "due_found", "delivered", "failed")
    list_filter = ("status", "trigger")
