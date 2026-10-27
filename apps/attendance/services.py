"""Attendance business logic: recording, correcting and calculating rates.

Calculation rules (see docs/ATTENDANCE_PERFORMANCE.md):
  * A lecture is "held" when it is scheduled (not cancelled) and has started.
  * A lecture counts for a student only if the student was enrolled on that date (enrolment date on or before
    the lecture date) and the enrolment is not withdrawn.
  * Only lectures WITH an attendance record enter the rate. A held lecture with no record is "not recorded";
    it is never treated as an absence.
  * attended   = present (+ late if configured) (+ excused if the policy is "count as attended")
  * denominator = present + late + absent (+ excused if the policy is "attended" or "absent")
  * rate = attended / denominator x 100, or None when the denominator is zero.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus
from apps.accounts.audit import log_action
from apps.timetables.models import LectureSession, SessionStatus

from .models import AttendanceChange, AttendanceRecord, AttendanceRules, AttendanceStatus, ExcusedPolicy


def percent(numerator, denominator):
    """Percentage rounded half-up to 1 decimal place, or None when the denominator is zero."""
    if not denominator:
        return None
    value = Decimal(numerator) * 100 / Decimal(denominator)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass
class AttendanceSummary:
    held: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    rules: AttendanceRules = field(default=None, repr=False)

    @property
    def recorded(self):
        return self.present + self.late + self.absent + self.excused

    @property
    def unrecorded(self):
        return max(self.held - self.recorded, 0)

    @property
    def attended(self):
        n = self.present
        if self.rules.late_counts_as_attended:
            n += self.late
        if self.rules.excused_policy == ExcusedPolicy.ATTENDED:
            n += self.excused
        return n

    @property
    def denominator(self):
        n = self.present + self.late + self.absent
        if self.rules.excused_policy in (ExcusedPolicy.ATTENDED, ExcusedPolicy.ABSENT):
            n += self.excused
        return n

    @property
    def rate(self):
        return percent(self.attended, self.denominator)

    def add(self, status):
        setattr(self, status, getattr(self, status) + 1)


def roster(session):
    """Students who should appear on the register: currently enrolled in the lecture's offering."""
    return (Enrolment.objects.filter(offering=session.offering_id, status=EnrolmentStatus.ENROLLED)
            .select_related("student__user", "student__programme").order_by("student__registration_number"))


def check_session_open(session, now=None):
    now = now or timezone.now()
    if session.status == SessionStatus.CANCELLED:
        raise ValidationError("Attendance cannot be recorded for a cancelled lecture.")
    if session.start_at > now:
        raise ValidationError("Attendance can only be recorded once the lecture has started.")


@transaction.atomic
def save_attendance(session, user, statuses, *, reason="", now=None):
    """Record or correct attendance for one lecture.

    statuses maps student id -> status value, or "" for "leave unrecorded / unchanged".
    Changing an existing record is a correction: a reason is required and an AttendanceChange row is written.
    Returns {"created": n, "corrected": n, "unchanged": n}.
    """
    check_session_open(session, now)
    reason = (reason or "").strip()
    valid = set(AttendanceStatus.values)
    on_roster = {e.student_id for e in roster(session)}
    existing = {r.student_id: r for r in AttendanceRecord.objects.select_for_update().filter(session=session)}
    result = {"created": 0, "corrected": 0, "unchanged": 0}

    pending = []
    for student_id, status in statuses.items():
        if not status:
            continue
        if status not in valid:
            raise ValidationError(f"Unknown attendance status: {status}.")
        if student_id not in on_roster and student_id not in existing:
            raise ValidationError("A student who is not enrolled in this course cannot be given an attendance record.")
        pending.append((student_id, status))
    if any(student_id in existing and existing[student_id].status != status for student_id, status in pending) and not reason:
        raise ValidationError("Enter a reason for the correction: some students already have a different recorded status.")

    for student_id, status in pending:
        record = existing.get(student_id)
        if record is None:
            record = AttendanceRecord.objects.create(session=session, student_id=student_id, status=status,
                                                     recorded_by=user, updated_by=user)
            AttendanceChange.objects.create(record=record, old_status="", new_status=status, changed_by=user)
            result["created"] += 1
        elif record.status != status:
            AttendanceChange.objects.create(record=record, old_status=record.status, new_status=status,
                                            reason=reason, changed_by=user)
            record.status, record.updated_by = status, user
            record.save(update_fields=["status", "updated_by", "updated_at"])
            result["corrected"] += 1
        else:
            result["unchanged"] += 1
    if result["created"] or result["corrected"]:
        log_action("attendance_recorded" if not result["corrected"] else "attendance_corrected", actor=user,
                   target=str(session), details=f"{result['created']} recorded, {result['corrected']} corrected"
                                                + (f". Reason: {reason}" if result["corrected"] else ""))
    return result


def session_counts(session):
    """Attendance counts for one lecture (does not need the rules: raw counts)."""
    counts = {s: 0 for s in AttendanceStatus.values}
    for rec in AttendanceRecord.objects.filter(session=session).values_list("status", flat=True):
        counts[rec] += 1
    counts["recorded"] = sum(counts.values())
    counts["roster"] = roster(session).count()
    counts["not_recorded"] = max(counts["roster"] - counts["recorded"], 0)
    return counts


def _held_sessions(offering_ids, *, as_of=None, start=None, end=None):
    qs = LectureSession.objects.filter(offering_id__in=offering_ids, status=SessionStatus.SCHEDULED,
                                       start_at__lte=as_of or timezone.now())
    if start:
        qs = qs.filter(start_at__gte=start)
    if end:
        qs = qs.filter(start_at__lt=end)
    return qs.select_related("offering__course", "venue").order_by("start_at")


def student_summary(student, *, offering=None, as_of=None, start=None, end=None, rules=None, enrolments=None):
    """AttendanceSummary for one student, optionally limited to one offering and/or a time window [start, end)."""
    rules = rules or AttendanceRules.get()
    if enrolments is None:
        enrolments = Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED)
        if offering is not None:
            enrolments = enrolments.filter(offering=offering)
    enrolled_on = {e.offering_id: e.enrolled_on for e in enrolments}
    summary = AttendanceSummary(rules=rules)
    if not enrolled_on:
        return summary
    sessions = [s for s in _held_sessions(list(enrolled_on), as_of=as_of, start=start, end=end)
                if s.local_date >= enrolled_on[s.offering_id]]
    summary.held = len(sessions)
    statuses = dict(AttendanceRecord.objects.filter(student=student, session__in=sessions).values_list("session_id", "status"))
    for s in sessions:
        if s.pk in statuses:
            summary.add(statuses[s.pk])
    return summary


def student_report(student, *, as_of=None):
    """Overall and per-offering attendance for one student, plus their individual records."""
    rules = AttendanceRules.get()
    enrolments = list(Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED)
                      .select_related("offering__course", "offering__semester__academic_year"))
    by_offering = [(e.offering, student_summary(student, offering=e.offering, as_of=as_of, rules=rules, enrolments=[e]))
                   for e in enrolments]
    overall = student_summary(student, as_of=as_of, rules=rules, enrolments=enrolments)
    records = (AttendanceRecord.objects.filter(student=student, session__status=SessionStatus.SCHEDULED)
               .select_related("session__offering__course", "session__venue").order_by("-session__start_at"))
    return {"overall": overall, "by_offering": by_offering, "records": records}


def offering_report(offering, *, as_of=None):
    """Course-level report: one row per enrolled student and one per held lecture, plus an overall summary."""
    rules = AttendanceRules.get()
    as_of = as_of or timezone.now()
    enrolments = list(Enrolment.objects.filter(offering=offering, status=EnrolmentStatus.ENROLLED)
                      .select_related("student__user").order_by("student__registration_number"))
    sessions = list(_held_sessions([offering.pk], as_of=as_of))
    records = {}
    for sid, stid, status in AttendanceRecord.objects.filter(session__in=sessions).values_list("session_id", "student_id", "status"):
        records[(sid, stid)] = status

    student_rows, overall = [], AttendanceSummary(rules=rules)
    for e in enrolments:
        summary = AttendanceSummary(rules=rules)
        for s in sessions:
            if s.local_date < e.enrolled_on:
                continue
            summary.held += 1
            status = records.get((s.pk, e.student_id))
            if status:
                summary.add(status)
                overall.add(status)
        overall.held += summary.held
        student_rows.append({"student": e.student, "summary": summary})

    session_rows = []
    for s in sessions:
        summary = AttendanceSummary(rules=rules)
        for e in enrolments:
            if s.local_date < e.enrolled_on:
                continue
            summary.held += 1
            status = records.get((s.pk, e.student_id))
            if status:
                summary.add(status)
        session_rows.append({"session": s, "summary": summary})
    return {"rules": rules, "students": student_rows, "sessions": session_rows, "overall": overall}


def sessions_awaiting_attendance(offering_ids, *, now=None):
    """Held lectures of the given offerings that have no attendance record at all (useful reminder for lecturers)."""
    return (_held_sessions(offering_ids, as_of=now).filter(attendance_records__isnull=True)
            .filter(offering__enrolments__status=EnrolmentStatus.ENROLLED).distinct())
