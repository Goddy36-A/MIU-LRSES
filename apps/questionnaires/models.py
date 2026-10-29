"""Questionnaire models (Phase 6): questionnaires, items, assignment to participants, responses and answers.

Researchers write every item. The system contains no pre-written questionnaire content.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

LIKERT_LABELS = {1: "Strongly disagree", 2: "Disagree", 3: "Neither agree nor disagree", 4: "Agree", 5: "Strongly agree"}
LIKERT_CHOICES = list(LIKERT_LABELS.items())
MAX_TEXT_LENGTH = 2000


class QuestionnaireStatus(models.TextChoices):
    DRAFT = "draft", "Draft (items can be edited)"
    OPEN = "open", "Open (assigned participants can answer)"
    CLOSED = "closed", "Closed"


class QuestionType(models.TextChoices):
    LIKERT = "likert", "Five-point Likert scale"
    CHOICE = "choice", "Multiple choice (one answer)"
    TEXT = "text", "Optional free text"


class Construct(models.TextChoices):
    NONE = "", "Not a TAM construct"
    PU = "PU", "Perceived Usefulness (PU)"
    PEOU = "PEOU", "Perceived Ease of Use (PEOU)"
    BI = "BI", "Behavioural Intention (BI)"


TAM_CONSTRUCTS = ["PU", "PEOU", "BI"]


class Questionnaire(models.Model):
    study = models.ForeignKey("research.ResearchStudy", on_delete=models.PROTECT, related_name="questionnaires")
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True, help_text="Shown to participants above the questions.")
    research_question = models.TextField(blank=True, help_text="The research question or construct this questionnaire addresses.")
    period = models.CharField(max_length=20, blank=True, choices=[("", "Not tied to a period"), ("baseline", "Baseline"),
                                                                  ("post_intervention", "Post-intervention")],
                              help_text="Which measurement period the responses belong to.")
    status = models.CharField(max_length=8, choices=QuestionnaireStatus.choices, default=QuestionnaireStatus.DRAFT)
    items_approved = models.BooleanField(default=False, help_text="A researcher has reviewed the items and approved them for use.")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def items_editable(self):
        return self.status == QuestionnaireStatus.DRAFT

    def __str__(self):
        return self.title


class Question(models.Model):
    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField(default=1)
    text = models.TextField()
    qtype = models.CharField("Type", max_length=8, choices=QuestionType.choices, default=QuestionType.LIKERT)
    construct = models.CharField(max_length=4, blank=True, choices=Construct.choices, default="",
                                 help_text="For Likert items that measure a TAM construct.")
    required = models.BooleanField(default=True)
    reverse_scored = models.BooleanField(default=False, help_text="Negatively worded Likert item: its score is flipped (6 - value) when a construct score is calculated.")

    class Meta:
        ordering = ["order", "id"]

    def clean(self):
        errors = {}
        if self.construct and self.qtype != QuestionType.LIKERT:
            errors["construct"] = "Only Likert items can belong to a TAM construct."
        if self.reverse_scored and self.qtype != QuestionType.LIKERT:
            errors["reverse_scored"] = "Only Likert items can be reverse scored."
        if self.qtype == QuestionType.TEXT and self.required:
            errors["required"] = "Free-text questions are optional."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.order}. {self.text[:60]}"


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    order = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=200)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.label


class Assignment(models.Model):
    """A questionnaire given to one enrolled participant. Nobody is assigned automatically."""

    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.CASCADE, related_name="assignments")
    participant = models.ForeignKey("research.Participant", on_delete=models.PROTECT, related_name="questionnaire_assignments")
    due_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["participant__research_code"]
        constraints = [models.UniqueConstraint(fields=["questionnaire", "participant"], name="unique_assignment_per_participant")]

    def __str__(self):
        return f"{self.questionnaire} -> {self.participant}"


class ResponseStatus(models.TextChoices):
    DRAFT = "draft", "In progress"
    SUBMITTED = "submitted", "Submitted"


class Response(models.Model):
    """One participant's answers to one questionnaire. Once submitted it is locked."""

    assignment = models.OneToOneField(Assignment, on_delete=models.CASCADE, related_name="response")
    status = models.CharField(max_length=10, choices=ResponseStatus.choices, default=ResponseStatus.DRAFT)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(Q(status="submitted", submitted_at__isnull=False) | (~Q(status="submitted") & Q(submitted_at__isnull=True))),
            name="response_submitted_at_only_when_submitted")]

    @property
    def is_submitted(self):
        return self.status == ResponseStatus.SUBMITTED

    def __str__(self):
        return f"Response of {self.assignment.participant}"


class Answer(models.Model):
    response = models.ForeignKey(Response, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="answers")
    likert_value = models.PositiveSmallIntegerField(null=True, blank=True)
    option = models.ForeignKey(Option, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    text = models.TextField(blank=True)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["response", "question"], name="unique_answer_per_question"),
            models.CheckConstraint(condition=Q(likert_value__isnull=True) | Q(likert_value__gte=1, likert_value__lte=5),
                                   name="likert_value_between_1_and_5"),
        ]

    def __str__(self):
        return f"Answer to {self.question_id}"
