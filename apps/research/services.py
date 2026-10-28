"""Research business logic. Views only call these functions.

Principles (documented in docs/RESEARCH.md):
* Nobody is enrolled, consented, allocated or measured automatically. Each is an explicit, recorded researcher action.
* The system never randomises. Allocation is a researcher decision with a documented procedure.
* A measurement is either collected (has a value and a date), missing (has a reason), not applicable, or planned
  (expected but not yet collected). Nothing is ever filled in with an assumed value.
* Collected values are never silently overwritten: every change is stored as a MeasurementRevision.
* System-calculated outcomes (attendance, punctuality, assessment, reminder interaction) are only calculated for
  participants who are eligible, have given consent, are enrolled and have not withdrawn.
"""
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import EnrolmentStatus, Enrolment, StudentProfile, StudentStatus
from apps.accounts.audit import log_action
from apps.attendance import services as attendance_services
from apps.performance import services as performance_services
from apps.reminders.models import Notification, NotificationKind, NotificationStatus
from apps.reminders.services import cancel_pending_reminders_for

from .models import (Allocation, AllocationMethod, AppliesTo, ConsentStatus, Eligibility, Group, Measurement,
                     MeasurementRevision, MeasurementSource, MeasurementStatus, MeasuredAt, OutcomeDefinition,
                     OutcomeKind, OutcomeSource, Participant, ParticipantEvent, Period, ResearchStudy, StudyStatus)


def get_active_study():
    return ResearchStudy.objects.filter(is_active=True).first()


# ---- The control-group reminder rule ---------------------------------------------------------------------------
def exclude_control_group_from_reminders(students, session):
    """Recipient filter for the reminder engine: control-group participants do not receive intervention reminders.

    Applies from allocation until the participant withdraws or the study is closed. It affects *reminders only*;
    schedule-change notices (normal academic communication) are not filtered, so a control student is still told
    when a lecture is cancelled or moved. Students who are not participants are unaffected."""
    control = (Participant.objects.filter(group=Group.CONTROL, withdrawn_on__isnull=True)
               .exclude(study__status=StudyStatus.CLOSED).values("student_id"))
    return students.exclude(pk__in=control)


# ---- Overview ------------------------------------------------------------------------------------------------
def enrolled_participants(study):
    return Participant.objects.filter(study=study, enrolled_on__isnull=False, eligibility=Eligibility.ELIGIBLE,
                                      consent_status=ConsentStatus.GIVEN, withdrawn_on__isnull=True)


def study_overview(study):
    """Counts only. Safe to show to administrators (no individual records)."""
    people = Participant.objects.filter(study=study)
    enrolled = enrolled_participants(study)
    in_intervention = enrolled.filter(group=Group.INTERVENTION).count()
    in_control = enrolled.filter(group=Group.CONTROL).count()
    return {
        "registered": people.count(),
        "enrolled": enrolled.count(),
        "intervention": in_intervention,
        "control": in_control,
        "unallocated": enrolled.filter(group="").count(),
        "eligible": people.filter(eligibility=Eligibility.ELIGIBLE).count(),
        "ineligible": people.filter(eligibility=Eligibility.INELIGIBLE).count(),
        "eligibility_pending": people.filter(eligibility=Eligibility.PENDING).count(),
        "consent_given": people.filter(consent_status=ConsentStatus.GIVEN).count(),
        "consent_declined": people.filter(consent_status=ConsentStatus.DECLINED).count(),
        "consent_pending": people.filter(consent_status=ConsentStatus.PENDING).count(),
        "withdrawn": people.filter(withdrawn_on__isnull=False).count(),
        "target_sample": study.target_sample_size,
        "target_intervention": study.target_intervention,
        "target_control": study.target_control,
    }


# ---- Participants ----------------------------------------------------------------------------------------------
def _event(participant, event, detail, user):
    return ParticipantEvent.objects.create(participant=participant, event=event, detail=detail, by=user)


@transaction.atomic
def register_participant(study, student, user, *, eligibility=Eligibility.PENDING, eligibility_notes="", notes=""):
    """Register one student as a potential participant. This is not enrolment and does not give consent."""
    if student.status != StudentStatus.ACTIVE:
        raise ValidationError("Only students with an active status can be registered.")
    if Participant.objects.filter(study=study, student=student).exists():
        raise ValidationError("This student is already registered in this study.")
    participant = Participant.objects.create(study=study, student=student, eligibility=eligibility,
                                             eligibility_notes=eligibility_notes, notes=notes, registered_by=user)
    _event(participant, "registered", f"Registered; eligibility: {participant.get_eligibility_display()}.", user)
    log_action("participant_registered", actor=user, target=participant.research_code)
    return participant


def record_participant_update(participant, user, changed_fields):
    """Write the history entries for an already-saved edit of eligibility, consent or enrolment."""
    if "eligibility" in changed_fields:
        _event(participant, "eligibility_changed", f"Eligibility: {participant.get_eligibility_display()}.", user)
    if "consent_status" in changed_fields or "consent_date" in changed_fields:
        when = f" on {participant.consent_date:%d %b %Y}" if participant.consent_date else ""
        _event(participant, "consent_changed", f"Consent: {participant.get_consent_status_display()}{when}.", user)
    if "enrolled_on" in changed_fields:
        detail = f"Enrolled on {participant.enrolled_on:%d %b %Y}." if participant.enrolled_on else "Enrolment date removed."
        _event(participant, "enrolment_changed", detail, user)
    if changed_fields:
        log_action("participant_updated", actor=user, target=participant.research_code,
                   details="changed fields: " + ", ".join(sorted(changed_fields)))


def _post_measurements_exist(participant):
    return participant.measurements.filter(period=Period.POST, status=MeasurementStatus.COLLECTED).exists()


@transaction.atomic
def allocate_participant(participant, user, *, group, method, procedure, allocation_date=None, reason=""):
    """Place an enrolled participant in a group and document how. Re-allocation requires a reason and is blocked
    once any post-intervention value has been collected. The history is kept in Allocation rows."""
    participant = Participant.objects.select_for_update().get(pk=participant.pk)
    if group not in Group.values:
        raise ValidationError("Choose the intervention or the control group.")
    if method not in AllocationMethod.values:
        raise ValidationError("Choose how the participant was allocated.")
    if not (procedure or "").strip():
        raise ValidationError("Describe the allocation procedure: every allocation must be documented.")
    if participant.is_withdrawn:
        raise ValidationError("A withdrawn participant cannot be allocated.")
    if not participant.is_enrolled:
        raise ValidationError("Only an eligible, consenting, enrolled participant can be allocated to a group.")
    allocation_date = allocation_date or timezone.localdate()
    if allocation_date > timezone.localdate():
        raise ValidationError("The allocation date cannot be in the future.")
    is_realloc = bool(participant.group)
    if is_realloc:
        if participant.group == group:
            raise ValidationError(f"This participant is already in the {participant.get_group_display().lower()} group.")
        if not (reason or "").strip():
            raise ValidationError("Enter the reason for moving the participant to the other group.")
        if _post_measurements_exist(participant):
            raise ValidationError("Post-intervention data have already been collected, so the group can no longer be changed.")
    allocation = Allocation.objects.create(
        participant=participant, group=group, method=method, procedure=procedure.strip(), allocation_date=allocation_date,
        is_reallocation=is_realloc, reallocation_reason=(reason or "").strip(), allocated_by=user)
    participant.group = group
    participant.save(update_fields=["group", "updated_at"])
    if group == Group.CONTROL and participant.study.restricts_control_reminders:
        cancel_pending_reminders_for(participant.student.user, "Cancelled: control-group participants do not receive intervention reminders.")
    log_action("participant_reallocated" if is_realloc else "participant_allocated", actor=user, target=participant.research_code)
    return allocation


@transaction.atomic
def withdraw_participant(participant, user, *, withdrawn_on, data_handling, reason=""):
    participant = Participant.objects.select_for_update().get(pk=participant.pk)
    if participant.is_withdrawn:
        raise ValidationError("This participant has already withdrawn.")
    if withdrawn_on > timezone.localdate():
        raise ValidationError("The withdrawal date cannot be in the future.")
    if data_handling not in ("retain", "exclude"):
        raise ValidationError("State whether the data collected so far are kept or excluded.")
    participant.withdrawn_on = withdrawn_on
    participant.withdrawal_reason = (reason or "").strip()
    participant.withdrawal_data_handling = data_handling
    participant.save(update_fields=["withdrawn_on", "withdrawal_reason", "withdrawal_data_handling", "updated_at"])
    _event(participant, "withdrawn", f"Withdrawn on {withdrawn_on:%d %b %Y}; {participant.get_withdrawal_data_handling_display().lower()}.", user)
    log_action("participant_withdrawn", actor=user, target=participant.research_code)
    return participant


# ---- Outcome definitions -------------------------------------------------------------------------------------------
DEFAULT_OUTCOMES = [
    dict(code="attendance-rate", name="Lecture attendance rate", kind=OutcomeKind.ATTENDANCE,
         definition="Attended lectures / lectures with an attendance record, as a percentage, for lectures held in the measurement window. "
                    "Lectures with no attendance record are not counted as absences. Late and excused handling follows the attendance rules."),
    dict(code="punctuality-rate", name="Assignment punctuality rate", kind=OutcomeKind.PUNCTUALITY,
         definition="Assignments submitted on or before the (extended) deadline / assignments due and eligible, as a percentage, for assignments "
                    "due in the window. Only assignments whose submission records are marked complete are counted; exempt students are excluded."),
    dict(code="assessment-score", name="Academic assessment score", kind=OutcomeKind.ASSESSMENT,
         definition="Mean of the student's course percentages for marked assignments and assessments dated in the window. Each course percentage "
                    "uses the course's own weighting if weights were entered, otherwise a simple average. Unmarked items are never counted as zero."),
    dict(code="reminder-read-rate", name="Reminder read rate", kind=OutcomeKind.REMINDER, applies_to=AppliesTo.INTERVENTION, measured_at=MeasuredAt.POST,
         definition="Delivered lecture reminders that the student opened (marked read) / delivered lecture reminders, as a percentage, for reminders "
                    "delivered in the window. Intervention group only."),
]


def ensure_default_outcomes(study):
    """Create the four standard outcome definitions if missing. Editable afterwards; they are starting points
    to be checked against the approved protocol, not approved definitions."""
    created = 0
    for spec in DEFAULT_OUTCOMES:
        _obj, was_created = OutcomeDefinition.objects.get_or_create(
            study=study, code=spec["code"], defaults=dict(source=OutcomeSource.CALCULATED, unit="percent", **spec))
        created += was_created
    return created


# ---- Planning measurements ----------------------------------------------------------------------------------------
def _applicable(participant, outcome):
    return not (outcome.applies_to == AppliesTo.INTERVENTION and participant.group != Group.INTERVENTION)


@transaction.atomic
def plan_measurements(study, user):
    """Create 'planned' (expected, not collected) rows for every enrolled participant, active outcome and applicable
    period. Idempotent; existing rows are untouched. Intervention-only outcomes are planned only for participants
    already allocated to the intervention group."""
    created = 0
    outcomes = list(OutcomeDefinition.objects.filter(study=study, is_active=True))
    for participant in enrolled_participants(study):
        for outcome in outcomes:
            if not _applicable(participant, outcome):
                continue
            for period in outcome.periods():
                _row, was_created = Measurement.objects.get_or_create(participant=participant, outcome=outcome, period=period)
                created += was_created
    if created:
        log_action("measurements_planned", actor=user, target=study.title, details=f"{created} planned measurement(s) created")
    return created


# ---- Measurement state ---------------------------------------------------------------------------------------------
STATE_LABELS = {"planned": "Planned", "not_yet_collected": "Not yet collected (window ended)", "collected": "Collected",
                "missing": "Missing", "not_applicable": "Not applicable", "withdrawn": "Participant withdrawn"}


def display_state(measurement, today=None):
    """collected | missing | not_applicable | withdrawn | not_yet_collected | planned."""
    today = today or timezone.localdate()
    if measurement.status == MeasurementStatus.COLLECTED:
        return "collected"
    if measurement.participant.withdrawn_on:
        return "withdrawn"
    if measurement.status == MeasurementStatus.MISSING:
        return "missing"
    if measurement.status == MeasurementStatus.NOT_APPLICABLE:
        return "not_applicable"
    window = measurement.outcome.study.window_for(measurement.period)
    if window and window[1] and window[1] < today:
        return "not_yet_collected"
    return "planned"


# ---- Recording ------------------------------------------------------------------------------------------------------
@transaction.atomic
def record_measurement(measurement, user, *, status, value=None, collected_on=None, missing_reason="", notes="", reason="",
                       source=MeasurementSource.MANUAL, calculation_detail="", today=None):
    """Record or correct one measurement. Returns True if anything changed.

    Changing an observed value (or its status) requires a reason, and every change adds a MeasurementRevision."""
    today = today or timezone.localdate()
    m = Measurement.objects.select_for_update().select_related("participant__study", "outcome").get(pk=measurement.pk)
    p, outcome, study = m.participant, m.outcome, m.participant.study
    reason, missing_reason, notes = (reason or "").strip(), (missing_reason or "").strip(), (notes or "").strip()

    if status not in MeasurementStatus.values or status == MeasurementStatus.PLANNED:
        raise ValidationError("Choose collected, missing or not applicable.")
    if p.is_withdrawn:
        raise ValidationError("This participant has withdrawn; no further data can be recorded.")
    if not p.is_enrolled:
        raise ValidationError("Data can only be recorded for eligible, consenting, enrolled participants.")
    if not _applicable(p, outcome) and status != MeasurementStatus.NOT_APPLICABLE:
        raise ValidationError("This outcome applies to the intervention group only.")
    if m.status == MeasurementStatus.COLLECTED and status != MeasurementStatus.COLLECTED and not reason:
        raise ValidationError("Enter a reason for changing a collected measurement.")

    if status == MeasurementStatus.COLLECTED:
        if value is None:
            raise ValidationError("Enter the measured value.")
        value = Decimal(value)
        if not (outcome.min_value <= value <= outcome.max_value):
            raise ValidationError(f"The value must be between {outcome.min_value:f} and {outcome.max_value:f} for this outcome.")
        if collected_on is None:
            raise ValidationError("Enter the date the data were collected.")
        if collected_on > today:
            raise ValidationError("The collection date cannot be in the future.")
        if m.period == Period.POST:
            if not study.intervention_start:
                raise ValidationError("Record the intervention start date in the study settings before recording post-intervention data.")
            if collected_on < study.intervention_start:
                raise ValidationError("Post-intervention data cannot be collected before the intervention start date.")
        missing_reason = ""
    else:
        if not missing_reason:
            raise ValidationError("Explain why the measurement is missing or not applicable.")
        value, collected_on, source, calculation_detail = None, None, "", ""

    unchanged = (m.status == status and m.value == value and m.collected_on == collected_on
                 and m.missing_reason == missing_reason and m.notes == notes)
    if unchanged:
        return False
    if m.status == MeasurementStatus.COLLECTED and (m.value != value or m.status != status) and not reason:
        raise ValidationError("Enter a reason for correcting a collected value. The original value is kept in the history.")

    MeasurementRevision.objects.create(
        measurement=m, old_status="" if m.status == MeasurementStatus.PLANNED else m.status, old_value=m.value,
        new_status=status, new_value=value, source=source, reason=reason, changed_by=user)
    was_collected = m.status == MeasurementStatus.COLLECTED
    m.status, m.value, m.collected_on, m.source = status, value, collected_on, source
    m.missing_reason, m.notes, m.calculation_detail, m.recorded_by = missing_reason, notes, calculation_detail, user
    m.save()
    log_action("measurement_corrected" if was_collected else "measurement_recorded", actor=user,
               target=f"{p.research_code} {outcome.code} {m.period}")
    return True


# ---- Calculations from system records -----------------------------------------------------------------------------------
class NotCalculable(ValidationError):
    """Raised when there are not enough valid records to calculate an outcome. The system never guesses a value."""


def _bounds(window):
    start, end = window
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz))


def _dec(value):
    return Decimal(str(value))


def _calc_attendance(student, start, end):
    s = attendance_services.student_summary(student, start=start, end=end)
    if s.rate is None:
        raise NotCalculable(f"No attendance records fall in the window ({s.held} lecture(s) held, {s.recorded} recorded). "
                            "Lectures without a record are not counted as absences.")
    detail = (f"Lectures held: {s.held}; recorded: {s.recorded} (present {s.present}, late {s.late}, absent {s.absent}, "
              f"excused {s.excused}); not recorded: {s.unrecorded}. Attended {s.attended} / denominator {s.denominator}. "
              f"Late counts as attended: {s.rules.late_counts_as_attended}; excused policy: {s.rules.excused_policy}.")
    return _dec(s.rate), detail


def _calc_punctuality(student, start, end):
    s = performance_services.student_punctuality(student, start=start, end=end)
    if s.rate is None:
        raise NotCalculable("No assignments with complete submission records fell due in the window for this student "
                            f"({s.assignments_awaiting_records} awaiting complete records, {s.exempt} exempt, {s.not_due} not yet due).")
    detail = (f"On time {s.on_time}, late {s.late}, not submitted {s.missing}; exempt {s.exempt} (excluded); "
              f"assignments counted {s.assignments_counted}; awaiting complete records {s.assignments_awaiting_records}.")
    return _dec(s.rate), detail


def _calc_assessment(student, start, end):
    per_course, parts = [], []
    for e in (Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED).select_related("offering__course")):
        items = performance_services._items_for(student, e.offering, start=start, end=end)
        value, method, _covered = performance_services.course_percentage(items)
        if value is not None:
            per_course.append(_dec(value))
            parts.append(f"{e.offering.course.code}: {value}% ({method}, {len(items)} marked item(s))")
    if not per_course:
        raise NotCalculable("No marked assignments or dated assessments fall in the window for this student.")
    mean = (sum(per_course) / len(per_course)).quantize(Decimal("0.01"))
    return mean, "Mean of course percentages: " + "; ".join(parts) + "."


def _calc_reminder(student, start, end):
    qs = Notification.objects.filter(recipient=student.user, kind=NotificationKind.REMINDER, status=NotificationStatus.DELIVERED,
                                     delivered_at__gte=start, delivered_at__lt=end)
    total = qs.count()
    if not total:
        raise NotCalculable("No lecture reminders were delivered to this participant in the window.")
    read = qs.filter(read_at__isnull=False).count()
    return _dec(attendance_services.percent(read, total)), f"Reminders delivered: {total}; opened (marked read): {read}."


_CALCULATORS = {OutcomeKind.ATTENDANCE: _calc_attendance, OutcomeKind.PUNCTUALITY: _calc_punctuality,
                OutcomeKind.ASSESSMENT: _calc_assessment, OutcomeKind.REMINDER: _calc_reminder}


def calculate_outcome(participant, outcome, period, *, today=None):
    """Return (value, detail) for one participant/outcome/period from existing system records, or raise ValidationError."""
    today = today or timezone.localdate()
    if outcome.source != OutcomeSource.CALCULATED or outcome.kind not in _CALCULATORS:
        raise ValidationError("This outcome is entered by researchers; it is not calculated by the system.")
    if not participant.is_enrolled:
        raise ValidationError("Records are only used for eligible, consenting, enrolled participants who have not withdrawn.")
    if not _applicable(participant, outcome):
        raise ValidationError("This outcome applies to the intervention group only.")
    window = participant.study.window_for(period)
    if window is None:
        raise ValidationError("Set the " + ("baseline window dates" if period == Period.BASELINE else "intervention start date")
                              + " in the study settings first.")
    if window[1] >= today:
        raise ValidationError(f"The {Period(period).label.lower()} window has not finished (it ends on {window[1]:%d %b %Y}). "
                              "Calculate after it has ended so the value does not rest on partial data.")
    start, end = _bounds(window)
    return _CALCULATORS[outcome.kind](participant.student, start, end)


def calculate_measurement(measurement, user, *, today=None):
    """Calculate and store one measurement from system records. Returns True if the stored measurement changed."""
    today = today or timezone.localdate()
    m = Measurement.objects.select_related("participant__student__user", "participant__study", "outcome").get(pk=measurement.pk)
    value, detail = calculate_outcome(m.participant, m.outcome, m.period, today=today)
    reason = "Recalculated from system records." if m.status == MeasurementStatus.COLLECTED else ""
    return record_measurement(m, user, status=MeasurementStatus.COLLECTED, value=value, collected_on=today,
                              source=MeasurementSource.SYSTEM, calculation_detail=detail, notes=m.notes, reason=reason, today=today)


def calculate_all(study, user, *, today=None):
    """Calculate every planned or missing system outcome that can be calculated. Collected values are not touched.
    Returns (calculated, skipped_counter): skipped reasons are counted so nothing fails silently."""
    today = today or timezone.localdate()
    calculated, skipped = 0, Counter()
    rows = (Measurement.objects.filter(participant__in=enrolled_participants(study), outcome__is_active=True,
                                       outcome__source=OutcomeSource.CALCULATED,
                                       status__in=[MeasurementStatus.PLANNED, MeasurementStatus.MISSING])
            .select_related("participant__student__user", "participant__study", "outcome"))
    for m in rows:
        try:
            calculated += calculate_measurement(m, user, today=today)
        except ValidationError as exc:
            skipped[exc.messages[0].split(" (")[0].split(" for this")[0][:90]] += 1
    return calculated, skipped


# ---- Completeness ---------------------------------------------------------------------------------------------------------
def completeness(study, *, today=None):
    """Per outcome, period and group: how many measurements are in each state. Counts every planned row; a
    participant with no row yet is reported as 'no row' so gaps in planning are visible, not hidden."""
    today = today or timezone.localdate()
    participants = list(Participant.objects.filter(study=study).exclude(enrolled_on__isnull=True))
    rows = []
    for outcome in OutcomeDefinition.objects.filter(study=study, is_active=True):
        for period in outcome.periods():
            existing = {m.participant_id: m for m in Measurement.objects.filter(outcome=outcome, period=period)
                        .select_related("participant", "outcome__study")}
            for group, label in [(Group.INTERVENTION, "Intervention"), (Group.CONTROL, "Control"), ("", "Not yet allocated")]:
                members = [p for p in participants if p.group == group and _applicable(p, outcome)]
                counts = Counter()
                for p in members:
                    m = existing.get(p.pk)
                    counts[display_state(m, today) if m else ("withdrawn" if p.withdrawn_on else "no_row")] += 1
                if members:
                    n = len(members) - counts["withdrawn"]
                    rows.append({"outcome": outcome, "period": Period(period).label, "group": label, "total": len(members),
                                 "counts": {k: counts.get(k, 0) for k in ["collected", "planned", "not_yet_collected", "missing",
                                                                         "not_applicable", "withdrawn", "no_row"]},
                                 "completeness": attendance_services.percent(counts["collected"], n) if n else None})
    return rows
