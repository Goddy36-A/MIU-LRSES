from django.contrib import admin

from . import models


class _ReadOnly(admin.ModelAdmin):
    """Questionnaire data are individual research data: read-only here, and visible only to superusers.
    Ordinary administrator accounts have no permission on these models. Changes go through the research pages."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Questionnaire)
class QuestionnaireAdmin(_ReadOnly):
    list_display = ("title", "status", "items_approved")


@admin.register(models.Question)
class QuestionAdmin(_ReadOnly):
    list_display = ("questionnaire", "order", "qtype", "construct")


@admin.register(models.Response)
class ResponseAdmin(_ReadOnly):
    list_display = ("id", "status", "submitted_at")
    exclude = ("assignment",)  # the participant link is not shown in Django Admin


@admin.register(models.Answer)
class AnswerAdmin(_ReadOnly):
    list_display = ("question", "likert_value", "answered_at")
    exclude = ("response", "text")
