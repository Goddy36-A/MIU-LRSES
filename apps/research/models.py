"""Research study models (Phase 5).

Everything here records what researchers *enter or what the system calculates from existing records*.
Nothing is pre-filled with findings. The planning figures (350 / 156 / 78 / 78 / 8 weeks) are only the
defaults of editable settings; they are not evidence of recruitment.
"""
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L: easy to read and to dictate
CODE_LENGTH = 6


class StudyStatus(models.TextChoices):
    """Set by the researcher. The system never advances it automatically and never infers it from dates."""

    PLANNING = "planning", "Planning"
    RECRUITING = "recruiting", "Recruiting participants"
    BASELINE = "baseline", "Baseline data collection"
    INTERVENTION = "intervention", "Intervention running"
    POST = "post", "Post-intervention data collection"
    ANALYSIS = "analysis", "Analysis"
    CLOSED = "closed", "Closed"


class EthicsStatus(models.TextChoices):
    NOT_RECORDED = "not_recorded", "Not recorded"
    PENDING = "pending", "Submitted / pending"
    APPROVED = "approved", "Approved (record the reference below)"


class Group(models.TextChoices):
    INTERVENTION = "intervention", "Intervention"
    CONTROL = "control", "Control"


class Period(models.TextChoices):
    BASELINE = "baseline", "Baseline"
    POST = "post_intervention", "Post-intervention"


class ResearchStudy(models.Model):
    """The study protocol settings. Planning figures are defaults taken from the research proposal and can be
    edited whenever the approved protocol changes."""

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=14, choices=StudyStatus.choices, default=StudyStatus.PLANNING)
    is_active = models.BooleanField(default=False, help_text="The study that the research pages work on. Only one study can be active.")
    ethics_status = models.CharField(
        max_length=14, choices=EthicsStatus.choices, default=EthicsStatus.NOT_RECORDED,
        help_text="Record only what is actually true. This software does not grant or imply ethical approval.")
    ethics_reference = models.CharField(max_length=120, blank=True, help_text="Approval reference number, if one has been issued.")

    population_size = models.PositiveIntegerField(default=350, validators=[MinValueValidator(1)],
                                                  help_text="Planning figure: eligible study population.")
    target_sample_size = models.PositiveIntegerField(default=156, validators=[MinValueValidator(1)],
                                                     help_text="Planning figure: proposed sample.")
    target_intervention = models.PositiveIntegerField(default=78, help_text="Planning figure: proposed intervention group size.")
    target_control = models.PositiveIntegerField(default=78, help_text="Planning figure: proposed control group size.")
    intervention_weeks = models.PositiveSmallIntegerField(default=8, validators=[MinValueValidator(1), MaxValueValidator(52)],
                                                          help_text="Length of the intervention period in weeks.")
    eligible_year_min = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(6)])
    eligible_year_max = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(6)])

    baseline_start = models.DateField(null=True, blank=True, help_text="First day of the baseline measurement window.")
    baseline_end = models.DateField(null=True, blank=True, help_text="Last day of the baseline measurement window.")
    intervention_start = models.DateField(null=True, blank=True, help_text="Leave blank until the intervention has actually been scheduled to start.")
    intervention_end = models.DateField(null=True, blank=True, help_text="Leave blank until known. If blank, the planned end (start + weeks) is used for the post-intervention window.")

    significance_level = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0.050"),
                                             validators=[MinValueValidator(Decimal("0.001")), MaxValueValidator(Decimal("0.200"))],
                                             help_text="Alpha level in the approved analysis plan (used by Phase 7).")
    protocol_notes = models.TextField(blank=True)
    analysis_plan_notes = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]
        verbose_name_plural = "research studies"

    def __str__(self):
        return self.title

    # ---- windows -------------------------------------------------------------------------------
    @property
    def planned_intervention_end(self):
        if not self.intervention_start:
            return None
        return self.intervention_start + timedelta(weeks=self.intervention_weeks) - timedelta(days=1)

    @property
    def post_window(self):
        """(start, end) dates of the post-intervention window, or None if the intervention start is not set."""
        if not self.intervention_start:
            return None
        return self.intervention_start, (self.intervention_end or self.planned_intervention_end)

    @property
    def baseline_window(self):
        if not (self.baseline_start and self.baseline_end):
            return None
        return self.baseline_start, self.baseline_end

    def window_for(self, period):
        return self.baseline_window if period == Period.BASELINE else self.post_window

    @property
    def restricts_control_reminders(self):
        """While a study is not closed, control-group participants do not receive intervention reminders."""
        return self.status != StudyStatus.CLOSED

    def clean(self):
        errors = {}
        if self.target_intervention + self.target_control != self.target_sample_size:
            errors["target_sample_size"] = "The intervention and control targets must add up to the proposed sample size."
        if self.target_sample_size > self.population_size:
            errors["target_sample_size"] = "The proposed sample cannot be larger than the study population."
        if self.eligible_year_min > self.eligible_year_max:
            errors["eligible_year_max"] = "The highest eligible year cannot be lower than the lowest."
        if self.baseline_start and self.baseline_end and self.baseline_end < self.baseline_start:
            errors["baseline_end"] = "The baseline window cannot end before it starts."
        if self.intervention_start and self.intervention_end and self.intervention_end < self.intervention_start:
            errors["intervention_end"] = "The intervention cannot end before it starts."
        if self.baseline_end and self.intervention_start and self.baseline_end >= self.intervention_start:
            errors["baseline_end"] = "The baseline window must end before the intervention starts."
        if self.ethics_status == EthicsStatus.APPROVED and not self.ethics_reference.strip():
            errors["ethics_reference"] = "Enter the approval reference if you record the study as approved."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                ResearchStudy.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
            super().save(*args, **kwargs)


class OutcomeKind(models.TextChoices):
    ATTENDANCE = "attendance_rate", "Lecture attendance rate"
    PUNCTUALITY = "punctuality_rate", "Assignment punctuality rate"
    ASSESSMENT = "assessment_score", "Academic assessment score"
    REMINDER = "reminder_interaction", "Reminder interaction"
    QUESTIONNAIRE = "questionnaire_score", "Questionnaire score"
    OTHER = "other", "Other numeric outcome"


CALCULABLE_KINDS = {OutcomeKind.ATTENDANCE, OutcomeKind.PUNCTUALITY, OutcomeKind.ASSESSMENT, OutcomeKind.REMINDER}


class OutcomeSource(models.TextChoices):
    MANUAL = "manual", "Entered by a researcher"
    CALCULATED = "calculated", "Calculated from system records"


class AppliesTo(models.TextChoices):
    ALL = "all", "All enrolled participants"
    INTERVENTION = "intervention", "Intervention group only"


class MeasuredAt(models.TextChoices):
    BOTH = "both", "Baseline and post-intervention"
    POST = "post", "Post-intervention only"


class OutcomeDefinition(models.Model):
    """What an outcome means and how it is obtained. Every Measurement points at one definition."""

    study = models.ForeignKey(ResearchStudy, on_delete=models.CASCADE, related_name="outcomes")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=24, choices=OutcomeKind.choices)
    source = models.CharField(max_length=10, choices=OutcomeSource.choices, default=OutcomeSource.MANUAL)
    definition = models.TextField(blank=True, help_text="How the value is defined and calculated, in words.")
    unit = models.CharField(max_length=20, default="percent", help_text="For example percent, score, count.")
    min_value = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    max_value = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("100"))
    applies_to = models.CharField(max_length=12, choices=AppliesTo.choices, default=AppliesTo.ALL)
    measured_at = models.CharField(max_length=4, choices=MeasuredAt.choices, default=MeasuredAt.BOTH)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["study", "code"], name="unique_outcome_code_per_study")]

    def clean(self):
        errors = {}
        if self.min_value is not None and self.max_value is not None and self.min_value >= self.max_value:
            errors["max_value"] = "The maximum must be greater than the minimum."
        if self.source == OutcomeSource.CALCULATED and self.kind not in CALCULABLE_KINDS:
            errors["source"] = "The system can only calculate attendance, punctuality, assessment and reminder-interaction outcomes."
        if errors:
            raise ValidationError(errors)

    def periods(self):
        return [Period.POST] if self.measured_at == MeasuredAt.POST else [Period.BASELINE, Period.POST]

    def __str__(self):
        return self.name


class Eligibility(models.TextChoices):
    PENDING = "pending", "Not yet assessed"
    ELIGIBLE = "eligible", "Eligible"
    INELIGIBLE = "ineligible", "Not eligible"


class ConsentStatus(models.TextChoices):
    PENDING = "pending", "Not yet asked"
    GIVEN = "given", "Consent given"
    DECLINED = "declined", "Declined"


class WithdrawalDataHandling(models.TextChoices):
    RETAIN = "retain", "Keep data collected before withdrawal"
    EXCLUDE = "exclude", "Exclude all of this participant's data"


def _new_code():
    return "P-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class Participant(models.Model):
    """A student registered in a study. Registration is an explicit researcher action; nobody is enrolled
    automatically. Research outputs use ``research_code``, never the student's name."""

    study = models.ForeignKey(ResearchStudy, on_delete=models.PROTECT, related_name="participants")
    student = models.ForeignKey("academics.StudentProfile", on_delete=models.PROTECT, related_name="research_participations")
    research_code = models.CharField(max_length=12, editable=False)

    eligibility = models.CharField(max_length=10, choices=Eligibility.choices, default=Eligibility.PENDING)
    eligibility_notes = models.TextField(blank=True, help_text="Why the participant is or is not eligible. Do not include names or contact details.")
    consent_status = models.CharField(max_length=10, choices=ConsentStatus.choices, default=ConsentStatus.PENDING)
    consent_date = models.DateField(null=True, blank=True)
    consent_reference = models.CharField(max_length=60, blank=True, help_text="Consent form number or similar. Do not enter the participant's name.")
    enrolled_on = models.DateField(null=True, blank=True, help_text="Date the participant was formally enrolled in the study.")
    group = models.CharField(max_length=12, choices=Group.choices, blank=True)

    withdrawn_on = models.DateField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)
    withdrawal_data_handling = models.CharField(max_length=8, choices=WithdrawalDataHandling.choices, blank=True)

    notes = models.TextField(blank=True, help_text="Research notes. Do not enter names, registration numbers or contact details.")
    registered_at = models.DateTimeField(auto_now_add=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["research_code"]
        constraints = [
            models.UniqueConstraint(fields=["study", "student"], name="unique_participant_per_study"),
            models.UniqueConstraint(fields=["study", "research_code"], name="unique_research_code_per_study"),
        ]

    def save(self, *args, **kwargs):
        if not self.research_code:
            for _ in range(50):
                code = _new_code()
                if not Participant.objects.filter(study_id=self.study_id, research_code=code).exists():
                    self.research_code = code
                    break
            else:  # pragma: no cover - 31**6 codes; effectively unreachable
                raise RuntimeError("Could not generate a unique research code.")
        super().save(*args, **kwargs)

    @property
    def is_withdrawn(self):
        return self.withdrawn_on is not None

    @property
    def is_enrolled(self):
        """Eligible, consented, formally enrolled and not withdrawn: the only participants whose data may be used."""
        return bool(self.enrolled_on and self.eligibility == Eligibility.ELIGIBLE
                    and self.consent_status == ConsentStatus.GIVEN and not self.is_withdrawn)

    @property
    def stage(self):
        if self.is_withdrawn:
            return "Withdrawn"
        if self.group and self.is_enrolled:
            return "Allocated"
        if self.is_enrolled:
            return "Enrolled"
        if self.eligibility == Eligibility.INELIGIBLE:
            return "Not eligible"
        if self.consent_status == ConsentStatus.DECLINED:
            return "Declined"
        return "Registered"

    @property
    def year_matches_criterion(self):
        return self.study.eligible_year_min <= self.student.year_of_study <= self.study.eligible_year_max

    def clean(self):
        errors = {}
        today = timezone.localdate()
        if self.consent_status == ConsentStatus.GIVEN and not self.consent_date:
            errors["consent_date"] = "Enter the date consent was given."
        if self.consent_date and self.consent_date > today:
            errors["consent_date"] = "The consent date cannot be in the future."
        if self.consent_status == ConsentStatus.PENDING and self.consent_date:
            errors["consent_date"] = "Remove the date, or change the consent status."
        if self.enrolled_on:
            if self.eligibility != Eligibility.ELIGIBLE:
                errors["enrolled_on"] = "Only a participant assessed as eligible can be enrolled."
            elif self.consent_status != ConsentStatus.GIVEN:
                errors["enrolled_on"] = "A participant cannot be enrolled before consent has been given."
            elif self.consent_date and self.enrolled_on < self.consent_date:
                errors["enrolled_on"] = "The enrolment date cannot be before the consent date."
            elif self.enrolled_on > today:
                errors["enrolled_on"] = "The enrolment date cannot be in the future."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.research_code


class ParticipantEvent(models.Model):
    """Append-only history of registration, eligibility, consent, enrolment and withdrawal decisions."""

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=30)
    detail = models.TextField(blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.participant}: {self.event}"


class AllocationMethod(models.TextChoices):
    MANUAL = "manual", "Assigned by the researcher according to the protocol"
    EXTERNAL = "external_randomisation", "Randomised outside this system (procedure documented below)"
    OTHER = "other", "Other (describe below)"


class Allocation(models.Model):
    """How and when a participant was placed in a group. Append-only: a re-allocation adds a row.

    The system does NOT randomise. A researcher states the group and documents the procedure used."""

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="allocations")
    group = models.CharField(max_length=12, choices=Group.choices)
    method = models.CharField(max_length=24, choices=AllocationMethod.choices)
    procedure = models.TextField(help_text="Describe exactly how this participant was allocated (for example the protocol step, "
                                           "list or random-number procedure used and who performed it).")
    allocation_date = models.DateField(default=timezone.localdate)
    is_reallocation = models.BooleanField(default=False)
    reallocation_reason = models.TextField(blank=True)
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    allocated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.participant} -> {self.get_group_display()}"


class MeasurementStatus(models.TextChoices):
    PLANNED = "planned", "Planned (not collected)"
    COLLECTED = "collected", "Collected"
    MISSING = "missing", "Missing (could not be collected)"
    NOT_APPLICABLE = "not_applicable", "Not applicable"


class MeasurementSource(models.TextChoices):
    MANUAL = "manual", "Entered by a researcher"
    SYSTEM = "system", "Calculated from system records"


class Measurement(models.Model):
    """One outcome for one participant in one period. At most one row per (participant, outcome, period).

    A row with status ``planned`` is an expected measurement that has not been collected; it carries no value.
    Observed values are never overwritten silently: every change writes a MeasurementRevision."""

    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="measurements")
    outcome = models.ForeignKey(OutcomeDefinition, on_delete=models.PROTECT, related_name="measurements")
    period = models.CharField(max_length=20, choices=Period.choices)
    status = models.CharField(max_length=14, choices=MeasurementStatus.choices, default=MeasurementStatus.PLANNED)
    value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    collected_on = models.DateField(null=True, blank=True, help_text="Date the data were collected.")
    source = models.CharField(max_length=8, choices=MeasurementSource.choices, blank=True)
    calculation_detail = models.TextField(blank=True, help_text="Inputs used when the system calculated the value.")
    missing_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Do not enter names or contact details.")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["participant__research_code", "outcome__name", "period"]
        constraints = [
            models.UniqueConstraint(fields=["participant", "outcome", "period"], name="unique_measurement_per_participant_outcome_period"),
            models.CheckConstraint(
                condition=(Q(status="collected", value__isnull=False, collected_on__isnull=False)
                           | (~Q(status="collected") & Q(value__isnull=True))),
                name="measurement_value_only_when_collected"),
        ]

    def __str__(self):
        return f"{self.participant} {self.outcome.code} {self.period}"


class MeasurementRevision(models.Model):
    """Append-only history of every recording and change of a measurement."""

    measurement = models.ForeignKey(Measurement, on_delete=models.CASCADE, related_name="revisions")
    old_status = models.CharField(max_length=14, blank=True)
    old_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_status = models.CharField(max_length=14)
    new_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=8, blank=True)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]
