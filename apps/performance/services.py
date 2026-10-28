"""Assignment punctuality and academic performance calculations.

Rules (documented in docs/ATTENDANCE_PERFORMANCE.md):

PUNCTUALITY (per assignment, per enrolled student)
  * Only assignments whose submission records are marked complete enter punctuality rates.
  * Eligible students: enrolled (not withdrawn) and enrolled on or before the deadline date.
  * Effective deadline = the student's extension if one was granted, otherwise the assignment deadline.
  * Exempt students are excluded. A student whose effective deadline has not yet passed is excluded ("not yet due").
  * On time = submitted at or before the effective deadline. Late = submitted after it.
    Missing = effective deadline passed and no submission (counts against punctuality because the records are complete).
  * Punctuality rate = on time / (on time + late + missing) x 100.

PERFORMANCE
  * Percentage of an item = marks / maximum marks x 100.
  * Missing marks are never treated as zero. "Did not sit", "exempt" and unmarked items are left out and counted separately.
  * Course percentage: if any marked item has a weight, only weighted items are used, as a weighted mean
    (sum(weight x percentage) / sum(weight)); the weight covered so far is reported. If no marked item has a weight,
    it is the simple mean of item percentages. Grading bands and letter grades are NOT assumed; only percentages are reported.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus
from apps.attendance.services import percent

from .models import Assessment, AssessmentResult, Assignment, ResultStatus, Submission, SubmissionStatus

ON_TIME, LATE, MISSING, EXEMPT, NOT_DUE = "on_time", "late", "missing", "exempt", "not_due"
CLASS_LABELS = {ON_TIME: "On time", LATE: "Late", MISSING: "Not submitted", EXEMPT: "Exempt", NOT_DUE: "Not yet due"}


def pct(marks, max_marks):
    """Percentage of marks, rounded half-up to 1 decimal place."""
    if marks is None or not max_marks:
        return None
    return float((Decimal(marks) * 100 / Decimal(max_marks)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def classify(assignment, submission, as_of):
    """Punctuality class of one eligible student for one assignment."""
    if submission is not None and submission.status == SubmissionStatus.EXEMPT:
        return EXEMPT
    deadline = submission.effective_deadline if submission is not None else assignment.deadline
    if deadline > as_of:
        return NOT_DUE
    if submission is not None and submission.status == SubmissionStatus.SUBMITTED and submission.submitted_at:
        return ON_TIME if submission.submitted_at <= deadline else LATE
    return MISSING


@dataclass
class PunctualitySummary:
    on_time: int = 0
    late: int = 0
    missing: int = 0
    exempt: int = 0
    not_due: int = 0
    assignments_counted: int = 0
    assignments_awaiting_records: int = 0

    @property
    def eligible(self):
        return self.on_time + self.late + self.missing

    @property
    def rate(self):
        return percent(self.on_time, self.eligible)

    def add(self, cls):
        setattr(self, cls, getattr(self, cls) + 1)


def _eligible_enrolments(assignment):
    return [e for e in Enrolment.objects.filter(offering=assignment.offering_id, status=EnrolmentStatus.ENROLLED)
            .select_related("student__user").order_by("student__registration_number")
            if e.enrolled_on <= timezone.localtime(assignment.deadline).date()]


def assignment_report(assignment, *, as_of=None):
    """Per-student classification and summary for one assignment."""
    as_of = as_of or timezone.now()
    subs = {s.student_id: s for s in assignment.submissions.all()}
    rows, summary = [], PunctualitySummary()
    for e in _eligible_enrolments(assignment):
        sub = subs.get(e.student_id)
        cls = classify(assignment, sub, as_of)
        rows.append({"student": e.student, "submission": sub, "cls": cls, "label": CLASS_LABELS[cls],
                     "percentage": pct(sub.marks, assignment.max_marks) if sub else None})
        if assignment.records_complete:
            summary.add(cls)
    if assignment.records_complete:
        summary.assignments_counted = 1
    else:
        summary.assignments_awaiting_records = 1
    return {"rows": rows, "summary": summary}


def student_punctuality(student, *, offering=None, as_of=None, start=None, end=None):
    """Punctuality summary for one student across assignments (due between start and end, if given)."""
    as_of = as_of or timezone.now()
    enrolments = Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED)
    if offering is not None:
        enrolments = enrolments.filter(offering=offering)
    enrolled_on = {e.offering_id: e.enrolled_on for e in enrolments}
    summary = PunctualitySummary()
    if not enrolled_on:
        return summary
    assignments = Assignment.objects.filter(offering_id__in=list(enrolled_on))
    if start:
        assignments = assignments.filter(deadline__gte=start)
    if end:
        assignments = assignments.filter(deadline__lt=end)
    subs = {s.assignment_id: s for s in Submission.objects.filter(student=student, assignment__in=assignments)}
    for a in assignments:
        if timezone.localtime(a.deadline).date() < enrolled_on[a.offering_id]:
            continue
        if not a.records_complete:
            summary.assignments_awaiting_records += 1
            continue
        summary.assignments_counted += 1
        summary.add(classify(a, subs.get(a.pk), as_of))
    return summary


def _items_for(student, offering, *, start=None, end=None):
    """Marked items for one student in one offering as dicts of title, kind, marks, max, percentage, weight.

    Optional window [start, end) of aware datetimes: assignments are placed by their deadline and assessments by
    their assessment date (an assessment without a date cannot be placed in a window and is left out)."""
    items = []
    subs = Submission.objects.filter(student=student, assignment__offering=offering, status=SubmissionStatus.SUBMITTED,
                                     marks__isnull=False).select_related("assignment")
    results = AssessmentResult.objects.filter(student=student, assessment__offering=offering, status=ResultStatus.MARKED,
                                              marks__isnull=False).select_related("assessment")
    if start is not None:
        subs = subs.filter(assignment__deadline__gte=start)
        results = results.filter(assessment__assessment_date__gte=timezone.localtime(start).date())
    if end is not None:
        subs = subs.filter(assignment__deadline__lt=end)
        results = results.filter(assessment__assessment_date__lt=timezone.localtime(end).date())
    for s in subs:
        a = s.assignment
        items.append({"title": a.title, "kind": "Assignment", "marks": s.marks, "max": a.max_marks,
                      "percentage": pct(s.marks, a.max_marks), "weight": a.weight_percent})
    for r in results:
        a = r.assessment
        items.append({"title": a.title, "kind": a.get_kind_display(), "marks": r.marks, "max": a.max_marks,
                      "percentage": pct(r.marks, a.max_marks), "weight": a.weight_percent})
    return items


def course_percentage(items):
    """(percentage, method, weight_covered) for marked items; percentage is None when there are none."""
    if not items:
        return None, "none", None
    weighted = [i for i in items if i["weight"]]
    if weighted:
        total = sum(Decimal(i["weight"]) for i in weighted)
        value = sum(Decimal(i["weight"]) * Decimal(str(i["percentage"])) for i in weighted) / total
        return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)), "weighted", float(total)
    value = sum(Decimal(str(i["percentage"])) for i in items) / len(items)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)), "simple average", None


def student_offering_performance(student, offering):
    items = _items_for(student, offering)
    value, method, covered = course_percentage(items)
    return {"items": items, "percentage": value, "method": method, "weight_covered": covered, "marked_items": len(items)}


def student_performance(student):
    """Per-offering performance for a student's own results page (enrolled offerings only)."""
    out = []
    for e in (Enrolment.objects.filter(student=student, status=EnrolmentStatus.ENROLLED)
              .select_related("offering__course", "offering__semester__academic_year")):
        out.append((e.offering, student_offering_performance(student, e.offering)))
    return out


BANDS = [(0, 39), (40, 49), (50, 59), (60, 69), (70, 79), (80, 100)]


def offering_performance_report(offering, *, as_of=None):
    """Course-level report: one row per enrolled student, class statistics and a score distribution."""
    as_of = as_of or timezone.now()
    rows, values = [], []
    for e in (Enrolment.objects.filter(offering=offering, status=EnrolmentStatus.ENROLLED)
              .select_related("student__user").order_by("student__registration_number")):
        perf = student_offering_performance(e.student, offering)
        punct = student_punctuality(e.student, offering=offering, as_of=as_of)
        rows.append({"student": e.student, "performance": perf, "punctuality": punct})
        if perf["percentage"] is not None:
            values.append(perf["percentage"])
    stats = None
    if values:
        stats = {"n": len(values), "mean": round(sum(values) / len(values), 1), "median": round(median(values), 1),
                 "min": min(values), "max": max(values)}
    distribution = [sum(1 for v in values if lo <= v <= hi) if hi == 100 else sum(1 for v in values if lo <= v < hi + 1)
                    for lo, hi in BANDS]
    labels = [f"{lo}-{hi}%" for lo, hi in BANDS]
    all_assignments = list(offering.assignments.all())
    punct_total = PunctualitySummary()
    for a in all_assignments:
        s = assignment_report(a, as_of=as_of)["summary"]
        for f in ("on_time", "late", "missing", "exempt", "not_due", "assignments_counted", "assignments_awaiting_records"):
            setattr(punct_total, f, getattr(punct_total, f) + getattr(s, f))
    return {"rows": rows, "stats": stats, "distribution": distribution, "band_labels": labels,
            "enrolled": len(rows), "with_marks": len(values), "punctuality": punct_total}


# ---- Saving records (transactional, audited) ---------------------------------------------------------------
from django.db import transaction  # noqa: E402

from apps.accounts.audit import log_action  # noqa: E402


def _mark_text(value):
    return "-" if value is None else str(value)


@transaction.atomic
def save_submissions(assignment, user, rows, *, records_complete):
    """rows: student_id -> dict(status, submitted_at, extended_deadline, marks). A blank status means
    "leave as it is" (an existing record is never deleted by leaving a row blank)."""
    existing = {s.student_id: s for s in Submission.objects.select_for_update().filter(assignment=assignment)}
    created = updated = 0
    mark_changes = []
    for student_id, data in rows.items():
        if not data["status"]:
            continue
        sub = existing.get(student_id)
        fields = dict(status=data["status"], submitted_at=data["submitted_at"] if data["status"] == SubmissionStatus.SUBMITTED else None,
                      extended_deadline=data["extended_deadline"], marks=data["marks"] if data["status"] == SubmissionStatus.SUBMITTED else None)
        if sub is None:
            Submission.objects.create(assignment=assignment, student_id=student_id, recorded_by=user, **fields)
            created += 1
            if fields["marks"] is not None:
                mark_changes.append(f"{student_id}: - -> {fields['marks']}")
        elif any(getattr(sub, k) != v for k, v in fields.items()):
            if sub.marks != fields["marks"]:
                mark_changes.append(f"{student_id}: {_mark_text(sub.marks)} -> {_mark_text(fields['marks'])}")
            for k, v in fields.items():
                setattr(sub, k, v)
            sub.recorded_by = user
            sub.save()
            updated += 1
    if assignment.records_complete != records_complete:
        assignment.records_complete = records_complete
        assignment.save(update_fields=["records_complete"])
    log_action("submissions_saved", actor=user, target=str(assignment),
               details=f"{created} created, {updated} updated; records_complete={records_complete}"
                       + (f"; mark changes (student id): {'; '.join(mark_changes)}" if mark_changes else ""))
    return {"created": created, "updated": updated}


@transaction.atomic
def save_results(assessment, user, rows):
    """rows: student_id -> dict(status, marks). A blank status leaves the student unrecorded/unchanged."""
    existing = {r.student_id: r for r in AssessmentResult.objects.select_for_update().filter(assessment=assessment)}
    created = updated = 0
    changes = []
    for student_id, data in rows.items():
        if not data["status"]:
            continue
        marks = data["marks"] if data["status"] == ResultStatus.MARKED else None
        res = existing.get(student_id)
        if res is None:
            AssessmentResult.objects.create(assessment=assessment, student_id=student_id, status=data["status"],
                                            marks=marks, recorded_by=user)
            created += 1
            changes.append(f"{student_id}: - -> {_mark_text(marks)}")
        elif res.status != data["status"] or res.marks != marks:
            changes.append(f"{student_id}: {res.status}/{_mark_text(res.marks)} -> {data['status']}/{_mark_text(marks)}")
            res.status, res.marks, res.recorded_by = data["status"], marks, user
            res.save()
            updated += 1
    log_action("results_saved", actor=user, target=str(assessment),
               details=f"{created} created, {updated} updated" + (f"; changes (student id): {'; '.join(changes)}" if changes else ""))
    return {"created": created, "updated": updated}
