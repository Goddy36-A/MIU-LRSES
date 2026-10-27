from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MARK_VALIDATORS = [MinValueValidator(Decimal("0"))]
WEIGHT_VALIDATORS = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


class Assignment(models.Model):
    """Coursework with a deadline. Submissions (and optional marks) are recorded per student."""

    offering = models.ForeignKey("academics.CourseOffering", on_delete=models.PROTECT, related_name="assignments")
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    deadline = models.DateTimeField(db_index=True)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("100"),
                                    validators=[MinValueValidator(Decimal("0.01"))])
    weight_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=WEIGHT_VALIDATORS,
        help_text="Optional share of the course mark, 0-100. Leave blank if this course does not weight items.")
    records_complete = models.BooleanField(
        default=False, verbose_name="Submission records are complete",
        help_text="Tick when every student's submission has been recorded. Until then this assignment is left out of "
                  "punctuality rates, so students whose records were simply not entered are not counted as late.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-deadline"]

    def __str__(self):
        return f"{self.offering.course.code}: {self.title}"


class SubmissionStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    NOT_SUBMITTED = "not_submitted", "Not submitted"
    EXEMPT = "exempt", "Exempt"


class Submission(models.Model):
    """A student's submission record for an assignment (one per student and assignment).

    A student with no record at all is simply "no record yet". An extension is stored as extended_deadline."""

    assignment = models.ForeignKey(Assignment, on_delete=models.PROTECT, related_name="submissions")
    student = models.ForeignKey("academics.StudentProfile", on_delete=models.PROTECT, related_name="submissions")
    status = models.CharField(max_length=14, choices=SubmissionStatus.choices)
    submitted_at = models.DateTimeField(null=True, blank=True)
    extended_deadline = models.DateTimeField(null=True, blank=True, help_text="Individual extension granted to this student.")
    marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=MARK_VALIDATORS)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["assignment", "student__registration_number"]
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="unique_submission_per_student")]

    @property
    def effective_deadline(self):
        return self.extended_deadline or self.assignment.deadline

    @property
    def is_late(self):
        return bool(self.status == SubmissionStatus.SUBMITTED and self.submitted_at
                    and self.submitted_at > self.effective_deadline)

    def clean(self):
        errors = {}
        if self.status == SubmissionStatus.SUBMITTED and not self.submitted_at:
            errors["submitted_at"] = "Enter the submission time for a submitted assignment."
        if self.status != SubmissionStatus.SUBMITTED and self.submitted_at:
            errors["submitted_at"] = "Only a submitted assignment can have a submission time."
        if self.extended_deadline and self.assignment_id and self.extended_deadline <= self.assignment.deadline:
            errors["extended_deadline"] = "An extension must be later than the original deadline."
        if self.marks is not None:
            if self.status != SubmissionStatus.SUBMITTED:
                errors["marks"] = "Marks can only be entered for a submitted assignment."
            elif self.assignment_id and self.marks > self.assignment.max_marks:
                errors["marks"] = f"Marks cannot exceed the maximum ({self.assignment.max_marks})."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.student.registration_number} - {self.assignment}"


class AssessmentKind(models.TextChoices):
    TEST = "test", "Test"
    EXAM = "exam", "Examination"
    PRACTICAL = "practical", "Practical"
    OTHER = "other", "Other"


class Assessment(models.Model):
    """A test, examination or other assessed item with marks (no submission deadline)."""

    offering = models.ForeignKey("academics.CourseOffering", on_delete=models.PROTECT, related_name="assessments")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=AssessmentKind.choices, default=AssessmentKind.TEST)
    assessment_date = models.DateField(null=True, blank=True)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("100"),
                                    validators=[MinValueValidator(Decimal("0.01"))])
    weight_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=WEIGHT_VALIDATORS,
        help_text="Optional share of the course mark, 0-100. Leave blank if this course does not weight items.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assessment_date", "-created_at"]

    def __str__(self):
        return f"{self.offering.course.code}: {self.title}"


class ResultStatus(models.TextChoices):
    MARKED = "marked", "Marked"
    ABSENT = "absent", "Did not sit"
    EXEMPT = "exempt", "Exempt"


class AssessmentResult(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="results")
    student = models.ForeignKey("academics.StudentProfile", on_delete=models.PROTECT, related_name="assessment_results")
    status = models.CharField(max_length=8, choices=ResultStatus.choices, default=ResultStatus.MARKED)
    marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=MARK_VALIDATORS)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["assessment", "student__registration_number"]
        constraints = [models.UniqueConstraint(fields=["assessment", "student"], name="unique_result_per_student")]

    def clean(self):
        errors = {}
        if self.status == ResultStatus.MARKED:
            if self.marks is None:
                errors["marks"] = "Enter the marks for a marked result."
            elif self.assessment_id and self.marks > self.assessment.max_marks:
                errors["marks"] = f"Marks cannot exceed the maximum ({self.assessment.max_marks})."
        elif self.marks is not None:
            errors["marks"] = "Marks can only be entered for a marked result."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.student.registration_number} - {self.assessment}"
