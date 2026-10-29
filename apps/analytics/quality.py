"""Data-quality checks for research data. They REPORT problems; they never change or delete anything.

Each issue is {code, severity ("error" = an inconsistency that should be fixed before analysis, "warning" = missing or
incomplete data to be aware of), message, count, examples (research codes only, at most 10)}.
"""
from collections import Counter

from django.db.models import Count, F
from django.utils import timezone

from apps.questionnaires.models import Answer, Assignment as QAssignment, Response, ResponseStatus
from apps.reminders.models import Notification, NotificationKind, NotificationStatus
from apps.research.models import (Allocation, Group, Measurement, MeasurementStatus, Participant, Period)
from apps.research import services as research_services

MAX_EXAMPLES = 10


def _issue(code, severity, message, codes):
    codes = sorted(set(codes))
    return {"code": code, "severity": severity, "message": message, "count": len(codes), "examples": codes[:MAX_EXAMPLES]}


def data_quality_issues(study, *, today=None):
    today = today or timezone.localdate()
    issues = []
    people = list(Participant.objects.filter(study=study).prefetch_related("allocations"))
    by_id = {p.pk: p for p in people}
    enrolled = [p for p in people if p.enrolled_on]

    # ---- duplicates ----
    dup_codes = [c for c, n in Counter(p.research_code for p in people).items() if n > 1]
    if dup_codes:
        issues.append(_issue("duplicate_research_codes", "error", "The same research code is used by more than one participant.", dup_codes))
    dups = (Measurement.objects.filter(participant__study=study).values("participant", "outcome", "period").annotate(n=Count("id")).filter(n__gt=1))
    if dups:
        issues.append(_issue("duplicate_measurements", "error", "More than one measurement exists for the same participant, outcome and period.",
                             [by_id[d["participant"]].research_code for d in dups if d["participant"] in by_id]))
    dup_answers = (Answer.objects.filter(response__assignment__questionnaire__study=study).values("response", "question").annotate(n=Count("id")).filter(n__gt=1))
    if dup_answers:
        issues.append(_issue("duplicate_answers", "error", "A questionnaire question has more than one stored answer in the same response.",
                             [str(d["response"]) for d in dup_answers]))

    # ---- group assignment consistency ----
    no_alloc, mismatch = [], []
    for p in people:
        allocs = sorted(p.allocations.all(), key=lambda a: a.id)
        if p.group and not allocs:
            no_alloc.append(p.research_code)
        elif p.group and allocs and allocs[-1].group != p.group:
            mismatch.append(p.research_code)
        elif not p.group and allocs:
            mismatch.append(p.research_code)
    if no_alloc:
        issues.append(_issue("group_without_allocation_record", "error", "A participant has a group but no documented allocation record.", no_alloc))
    if mismatch:
        issues.append(_issue("group_differs_from_latest_allocation", "error", "A participant's current group differs from their latest allocation record.", mismatch))
    unallocated = [p.research_code for p in enrolled if not p.group and not p.withdrawn_on]
    if unallocated:
        issues.append(_issue("enrolled_not_allocated", "warning", "Enrolled participants have not been allocated to a group, so they are in no comparison.", unallocated))

    wrong_outcome = (Measurement.objects.filter(participant__study=study, participant__group=Group.CONTROL, outcome__applies_to="intervention",
                                                status=MeasurementStatus.COLLECTED))
    if wrong_outcome:
        issues.append(_issue("intervention_only_outcome_for_control", "error", "A control-group participant has a collected value for an intervention-only outcome.",
                             [m.participant.research_code for m in wrong_outcome.select_related("participant")]))

    if study.restricts_control_reminders:
        leaked = []
        for p in people:
            if p.group != Group.CONTROL or p.withdrawn_on:
                continue
            latest = max(p.allocations.all(), key=lambda a: a.id, default=None)
            if latest is None:
                continue
            if Notification.objects.filter(recipient=p.student.user, kind=NotificationKind.REMINDER, status=NotificationStatus.DELIVERED,
                                          delivered_at__date__gte=latest.allocation_date).exists():
                leaked.append(p.research_code)
        if leaked:
            issues.append(_issue("control_received_reminders", "error",
                                 "A control-group participant was delivered lecture reminders after allocation, which the study design does not allow.", leaked))

    realloc_post = [p.research_code for p in people if any(a.is_reallocation for a in p.allocations.all())
                    and p.measurements.filter(period=Period.POST, status=MeasurementStatus.COLLECTED).exists()]
    if realloc_post:
        issues.append(_issue("reallocated_with_post_data", "error", "A participant was moved between groups and also has post-intervention data.", realloc_post))

    # ---- invalid dates ----
    bad = []
    for p in people:
        if p.enrolled_on and p.consent_date and p.enrolled_on < p.consent_date:
            bad.append(p.research_code)
        if p.withdrawn_on and p.enrolled_on and p.withdrawn_on < p.enrolled_on:
            bad.append(p.research_code)
        if p.consent_date and p.consent_date > today:
            bad.append(p.research_code)
    if bad:
        issues.append(_issue("invalid_participant_dates", "error", "Participant dates are inconsistent (consent after enrolment, withdrawal before enrolment, or a future date).", bad))

    collected = Measurement.objects.filter(participant__study=study, status=MeasurementStatus.COLLECTED).select_related("participant", "outcome")
    future, post_early, base_late, after_withdrawal = [], [], [], []
    for m in collected:
        if m.collected_on and m.collected_on > today:
            future.append(m.participant.research_code)
        if m.period == Period.POST and study.intervention_start and m.collected_on and m.collected_on < study.intervention_start:
            post_early.append(m.participant.research_code)
        if m.period == Period.BASELINE and study.intervention_start and m.collected_on and m.collected_on >= study.intervention_start:
            base_late.append(m.participant.research_code)
        if m.participant.withdrawn_on and m.collected_on and m.collected_on > m.participant.withdrawn_on:
            after_withdrawal.append(m.participant.research_code)
    for code, msg, found in [("collection_date_in_future", "A measurement has a collection date in the future.", future),
                             ("post_before_intervention_start", "A post-intervention measurement was collected before the intervention start date.", post_early),
                             ("baseline_after_intervention_start", "A baseline measurement was collected on or after the intervention start date.", base_late),
                             ("collected_after_withdrawal", "A measurement was collected after the participant withdrew (it is left out of analyses).", after_withdrawal)]:
        if found:
            issues.append(_issue(code, "error", msg, found))
    early_responses = [r.assignment.participant.research_code for r in
                       Response.objects.filter(assignment__questionnaire__study=study, status=ResponseStatus.SUBMITTED, submitted_at__lt=F("assignment__assigned_at"))
                       .select_related("assignment__participant")]
    if early_responses:
        issues.append(_issue("response_before_assignment", "error", "A questionnaire response was submitted before it was assigned.", early_responses))

    # ---- missing values ----
    no_data = [p.research_code for p in enrolled if not p.withdrawn_on and not p.measurements.filter(status=MeasurementStatus.COLLECTED).exists()]
    if no_data:
        issues.append(_issue("enrolled_without_collected_data", "warning", "Enrolled participants have no collected measurement yet.", no_data))
    overdue = [m.participant.research_code for m in Measurement.objects.filter(participant__study=study, status=MeasurementStatus.PLANNED,
                                                                                 participant__withdrawn_on__isnull=True).select_related("participant", "outcome__study")
               if research_services.display_state(m, today) == "not_yet_collected"]
    if overdue:
        issues.append(_issue("overdue_planned_measurements", "warning", "Planned measurements are overdue: their window ended and no value was collected.", overdue))
    late_q = [a.participant.research_code for a in QAssignment.objects.filter(questionnaire__study=study, due_date__lt=today, participant__withdrawn_on__isnull=True)
              .select_related("participant", "response") if not (hasattr(a, "response") and a.response.is_submitted)]
    if late_q:
        issues.append(_issue("questionnaire_past_due_unanswered", "warning", "Assigned questionnaires are past their due date and not submitted.", late_q))
    no_choice = [p.research_code for p in people if p.withdrawn_on and p.withdrawal_data_handling not in ("retain", "exclude")]
    if no_choice:
        issues.append(_issue("withdrawal_choice_missing", "warning", "A withdrawn participant has no recorded choice about their data; their data are excluded.", no_choice))
    issues.sort(key=lambda i: (i["severity"] != "error", i["code"]))
    return issues
