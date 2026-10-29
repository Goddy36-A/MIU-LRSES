"""Research analytics (Phase 7): which data may be used, descriptive summaries, group comparisons and the dashboard.

Rules (documented in docs/ANALYTICS.md):
* Only data of participants who are eligible, have given consent and are enrolled can be used. A withdrawn participant's
  data are used only if they withdrew with "keep data collected before withdrawal", and only data dated on or before the
  withdrawal date. Withdrawing with "exclude all data" (or without stating a choice) removes the participant entirely.
* Only COLLECTED measurements enter any statistic. Planned, missing and not-applicable rows are counted as missing, never
  turned into zeros or filled in.
* Inferential tests are shown only when every group has at least ``study.min_analysis_n`` observations (pairs, for
  before/after tests). Otherwise the page says the analysis is not yet available and why, and shows descriptives only.
* Nothing here says an intervention "worked". Results are associations in a study whose allocation this system did not
  randomise; the pages say so.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

from django.db.models import F, Q
from django.utils import timezone

from apps.attendance.services import percent
from apps.questionnaires import services as q_services
from apps.questionnaires.models import Construct, Question, Questionnaire, QuestionType, Response, ResponseStatus, TAM_CONSTRUCTS
from apps.reminders.models import Notification, NotificationKind, NotificationStatus
from apps.research import services as research_services
from apps.research.models import (ConsentStatus, Eligibility, Group, Measurement, MeasurementStatus, OutcomeDefinition,
                                  Participant, Period)

from . import stats

GROUP_LABELS = OrderedDict([(Group.INTERVENTION, "Intervention"), (Group.CONTROL, "Control")])
DESIGN_NOTE = ("Allocation to groups is recorded by the researcher; this system does not randomise. A statistical result here is an "
               "association between group and outcome. It does not prove that the reminders caused a difference, and a p-value above or below "
               "the significance level does not show that an effect is present or absent. Several outcomes are tested and no correction for "
               "multiple testing is applied: interpret isolated results with caution.")


# ---- Which data may be used ------------------------------------------------------------------------------------------
def analysis_participants(study):
    """Participants whose data may be used: eligible, consent given, enrolled, and not withdrawn unless data are retained."""
    return (Participant.objects.filter(study=study, eligibility=Eligibility.ELIGIBLE, consent_status=ConsentStatus.GIVEN,
                                       enrolled_on__isnull=False)
            .filter(Q(withdrawn_on__isnull=True) | Q(withdrawal_data_handling="retain")))


def usable_measurements(study):
    """Collected measurements that may be used, with the participant and outcome loaded."""
    return (Measurement.objects.filter(participant__in=analysis_participants(study), outcome__study=study,
                                       status=MeasurementStatus.COLLECTED)
            .filter(Q(participant__withdrawn_on__isnull=True) | Q(collected_on__lte=F("participant__withdrawn_on")))
            .select_related("participant", "outcome"))


def _local_date(dt):
    return timezone.localtime(dt).date()


def _within_retained_window(participant, when):
    """True if a timestamped record may be used for this participant (not after a retained withdrawal)."""
    return participant.withdrawn_on is None or _local_date(when) <= participant.withdrawn_on


# ---- Descriptive helpers ---------------------------------------------------------------------------------------------
def _round(v, nd=2):
    return None if v is None else round(v, nd)


def describe(values, alpha):
    d = stats.describe(values, alpha)
    return {k: (_round(v, 2) if k != "n" else v) for k, v in d.items()}


def alpha_of(study):
    return float(study.significance_level)


def ci_level(alpha):
    """Confidence level text matching the significance level, e.g. alpha 0.05 -> "95%"."""
    pct = (1 - alpha) * 100
    return f"{pct:g}%"


# ---- Outcome data ----------------------------------------------------------------------------------------------------
def outcome_values(study, outcome):
    """{participant_id: {"group": str, Period.BASELINE: float, Period.POST: float}} for collected, usable values."""
    people = {}
    for m in usable_measurements(study).filter(outcome=outcome):
        entry = people.setdefault(m.participant_id, {"group": m.participant.group, "code": m.participant.research_code})
        entry[m.period] = float(m.value)
    return people


def group_counts(study):
    """Participants who may be analysed, per group (including the not-yet-allocated)."""
    counts = {Group.INTERVENTION: 0, Group.CONTROL: 0, "": 0}
    for g in analysis_participants(study).values_list("group", flat=True):
        counts[g] += 1
    return counts


def _applicable_counts(study, outcome):
    counts = group_counts(study)
    if outcome.applies_to == "intervention":
        counts = {Group.INTERVENTION: counts[Group.INTERVENTION], Group.CONTROL: 0, "": 0}
    return counts


# ---- Statistical blocks ----------------------------------------------------------------------------------------------
def _result_view(r):
    """Round a stats result dict for display; keep None where not estimable."""
    if r is None:
        return None
    if not r.get("estimable"):
        return {"estimable": False, "note": r.get("note", "Not estimable.")}
    out = {"estimable": True, "test": r["test"], "statistic": _round(r["statistic"], 3), "p": r["p"],
           "p_display": "< 0.001" if r["p"] < 0.001 else f"{r['p']:.3f}", "method": r.get("method"),
           "df": _round(r.get("df"), 1) if r.get("df") is not None else None}
    for k in ("diff", "ci_low", "ci_high"):
        if k in r:
            out[k] = _round(r[k], 2)
    eff = r.get("effect")
    if eff:
        out["effect"] = {"name": eff["name"], "value": _round(eff["value"], 2),
                         "ci_low": _round(eff.get("ci_low"), 2) if eff.get("ci_low") is not None else None,
                         "ci_high": _round(eff.get("ci_high"), 2) if eff.get("ci_high") is not None else None}
    if "superiority" in r:
        out["superiority"] = _round(r["superiority"], 2)
    if r.get("dropped_zero"):
        out["dropped_zero"] = r["dropped_zero"]
    return out


def _unavailable(block, study, counts):
    need = study.min_analysis_n
    block["available"] = False
    block["message"] = (f"Analysis not yet available: each group needs at least {need} observations ({counts}). "
                        "Descriptive summaries are shown below; the minimum is a study setting.")
    return block


def two_sample_block(study, title, description, x, y, *, enrolled, unit, label_x="Intervention", label_y="Control"):
    """Compare two independent groups (x minus y). x and y are lists of floats."""
    alpha = alpha_of(study)
    block = {"kind": "two_sample", "title": title, "description": description, "unit": unit, "alpha": alpha, "ci_level": ci_level(alpha),
             "groups": [{"label": label_x, "enrolled": enrolled[0], "n": len(x), "missing": max(enrolled[0] - len(x), 0), "summary": describe(x, alpha)},
                        {"label": label_y, "enrolled": enrolled[1], "n": len(y), "missing": max(enrolled[1] - len(y), 0), "summary": describe(y, alpha)}],
             "available": True, "message": "", "primary": None, "secondary": None, "selection": ""}
    if min(len(x), len(y)) < study.min_analysis_n:
        return _unavailable(block, study, f"{label_x.lower()} n = {len(x)}, {label_y.lower()} n = {len(y)}")
    choice, reason = stats.choose_two_sample(x, y)
    welch, mw = stats.welch_t(x, y, alpha), stats.mann_whitney(x, y, alpha)
    block["selection"] = reason
    block["primary"], block["secondary"] = (_result_view(welch), _result_view(mw)) if choice == "welch" else (_result_view(mw), _result_view(welch))
    block["primary_is"] = "Welch's t-test" if choice == "welch" else "Mann-Whitney U test"
    block["direction"] = f"Difference = {label_x.lower()} minus {label_y.lower()} (mean difference, {ci_level(alpha)} confidence interval)."
    block["significant"] = bool(block["primary"] and block["primary"].get("estimable") and block["primary"]["p"] < alpha)
    return block


def paired_block(study, title, description, pairs, *, enrolled, unit, group_label):
    """Baseline versus post-intervention within one group. pairs: list of (baseline, post)."""
    alpha = alpha_of(study)
    diffs = [post - base for base, post in pairs]
    block = {"kind": "paired", "title": title, "description": description, "unit": unit, "alpha": alpha, "ci_level": ci_level(alpha),
             "groups": [{"label": group_label, "enrolled": enrolled, "n": len(pairs), "missing": max(enrolled - len(pairs), 0),
                         "summary": describe(diffs, alpha), "baseline": describe([b for b, _ in pairs], alpha),
                         "post": describe([p for _, p in pairs], alpha)}],
             "available": True, "message": "", "primary": None, "secondary": None, "selection": ""}
    if len(pairs) < study.min_analysis_n:
        return _unavailable(block, study, f"{group_label.lower()} complete pairs = {len(pairs)}")
    choice, reason = stats.choose_paired(diffs)
    t, w = stats.paired_t(diffs, alpha), stats.wilcoxon_signed_rank(diffs)
    block["selection"] = reason
    block["primary"], block["secondary"] = (_result_view(t), _result_view(w)) if choice == "paired_t" else (_result_view(w), _result_view(t))
    block["primary_is"] = "Paired t-test" if choice == "paired_t" else "Wilcoxon signed-rank test"
    block["direction"] = f"Change = post-intervention minus baseline (mean change, {ci_level(alpha)} confidence interval)."
    block["significant"] = bool(block["primary"] and block["primary"].get("estimable") and block["primary"]["p"] < alpha)
    return block


def analyse_outcome(study, outcome):
    """All applicable comparisons for one outcome definition."""
    data = outcome_values(study, outcome)
    enrolled = _applicable_counts(study, outcome)
    unit = outcome.unit
    ivg, ctl = Group.INTERVENTION, Group.CONTROL

    def vals(group, period):
        return [e[period] for e in data.values() if e["group"] == group and period in e]

    def pairs(group):
        return [(e[Period.BASELINE], e[Period.POST]) for e in data.values()
                if e["group"] == group and Period.BASELINE in e and Period.POST in e]

    blocks = []
    both_periods = outcome.measured_at == "both"
    if outcome.applies_to == "intervention":
        alpha = alpha_of(study)
        for period in outcome.periods():
            v = vals(ivg, period)
            blocks.append({"kind": "descriptive", "title": f"{Period(period).label}: intervention group only",
                           "description": "This outcome applies to the intervention group only, so there is no control comparison.",
                           "unit": unit, "available": True, "message": "", "alpha": alpha, "ci_level": ci_level(alpha),
                           "groups": [{"label": "Intervention", "enrolled": enrolled[ivg], "n": len(v), "missing": max(enrolled[ivg] - len(v), 0),
                                       "summary": describe(v, alpha)}]})
        if both_periods:
            blocks.append(paired_block(study, "Baseline versus post-intervention: intervention group", "Complete pairs only.",
                                       pairs(ivg), enrolled=enrolled[ivg], unit=unit, group_label="Intervention"))
        return {"outcome": outcome, "blocks": blocks, "collected": len(data)}

    if both_periods:
        blocks.append(two_sample_block(study, "Baseline comparability: intervention versus control",
                                       "Compares the groups before the intervention. A difference here means any later difference may not be due to the intervention.",
                                       vals(ivg, Period.BASELINE), vals(ctl, Period.BASELINE), enrolled=(enrolled[ivg], enrolled[ctl]), unit=unit))
    blocks.append(two_sample_block(study, "Post-intervention: intervention versus control", "Compares the groups after the intervention period.",
                                   vals(ivg, Period.POST), vals(ctl, Period.POST), enrolled=(enrolled[ivg], enrolled[ctl]), unit=unit))
    if both_periods:
        ch = lambda g: [post - base for base, post in pairs(g)]  # noqa: E731
        blocks.append(two_sample_block(study, "Change from baseline: intervention versus control",
                                       "Compares each participant's change (post minus baseline) between groups. Only participants with both values are included.",
                                       ch(ivg), ch(ctl), enrolled=(enrolled[ivg], enrolled[ctl]), unit=unit))
        blocks.append(paired_block(study, "Baseline versus post-intervention: intervention group", "Complete pairs only.",
                                   pairs(ivg), enrolled=enrolled[ivg], unit=unit, group_label="Intervention"))
        blocks.append(paired_block(study, "Baseline versus post-intervention: control group", "Complete pairs only.",
                                   pairs(ctl), enrolled=enrolled[ctl], unit=unit, group_label="Control"))
    return {"outcome": outcome, "blocks": blocks, "collected": len(data)}


# ---- TAM constructs --------------------------------------------------------------------------------------------------
def analysis_responses(study, q):
    """Submitted responses of participants whose data may be used (and submitted on or before a retained withdrawal)."""
    participants = analysis_participants(study)
    rows = (Response.objects.filter(assignment__questionnaire=q, status=ResponseStatus.SUBMITTED,
                                    assignment__participant__in=participants)
            .select_related("assignment__participant").prefetch_related("answers"))
    return [r for r in rows if _within_retained_window(r.assignment.participant, r.submitted_at)]


def construct_data(study, q):
    """{construct: {"scores": [(group, score)], "complete_rows": [[item scores]], "incomplete": n, "items": n}} for one questionnaire."""
    questions = list(q.questions.all())
    out = {}
    for c in TAM_CONSTRUCTS:
        items = [qu for qu in questions if qu.construct == c and qu.qtype == QuestionType.LIKERT]
        if items:
            out[c] = {"items": items, "scores": [], "complete_rows": [], "incomplete": 0}
    for r in analysis_responses(study, q):
        given = {a.question_id: a.likert_value for a in r.answers.all() if a.likert_value is not None}
        group = r.assignment.participant.group
        for c, d in out.items():
            if any(qu.pk not in given for qu in d["items"]):
                d["incomplete"] += 1
                continue
            row = [(6 - given[qu.pk]) if qu.reverse_scored else given[qu.pk] for qu in d["items"]]
            d["complete_rows"].append(row)
            d["scores"].append((group, stats.mean(row)))
    return out


def analyse_tam(study):
    """Per questionnaire and construct: descriptives (overall and by group), reliability and, when both groups are
    large enough, an intervention-versus-control comparison."""
    alpha = alpha_of(study)
    results = []
    for q in Questionnaire.objects.filter(study=study).order_by("id"):
        data = construct_data(study, q)
        if not data:
            continue
        constructs = []
        for c, d in data.items():
            ivg = [s for g, s in d["scores"] if g == Group.INTERVENTION]
            ctl = [s for g, s in d["scores"] if g == Group.CONTROL]
            unallocated = [s for g, s in d["scores"] if g == ""]
            rel = stats.cronbach_alpha(d["complete_rows"])
            entry = {"construct": c, "label": Construct(c).label, "items": len(d["items"]), "incomplete": d["incomplete"],
                     "overall": describe([s for _, s in d["scores"]], alpha),
                     "groups": [("Intervention", describe(ivg, alpha)), ("Control", describe(ctl, alpha))] + ([("Not allocated", describe(unallocated, alpha))] if unallocated else []),
                     "alpha": _round(rel["alpha"], 2) if rel.get("alpha") is not None else None,
                     "alpha_note": rel.get("note", ""), "alpha_n": rel["n"], "comparison": None}
            if ivg and ctl:
                entry["comparison"] = two_sample_block(study, f"{c}: intervention versus control", "Compares construct scores (1 to 5) between groups.",
                                                       ivg, ctl, enrolled=(len(ivg), len(ctl)), unit="score (1-5)")
            constructs.append(entry)
        results.append({"questionnaire": q, "period": q.get_period_display() if q.period else "Not tied to a period", "constructs": constructs})
    return results


# ---- Reminder interaction --------------------------------------------------------------------------------------------
def reminder_window(study):
    """(start, end, label) timestamps for the reminder summary: the post-intervention window if set, otherwise all time."""
    window = study.post_window
    if not window:
        return None, None, "all delivered reminders (the intervention window is not set)"
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(window[0], datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(window[1] + timedelta(days=1), datetime.min.time()), tz)
    return start, end, f"{window[0]:%d %b %Y} to {window[1]:%d %b %Y}"


def delivered_reminders(study):
    """Delivered lecture reminders to participants whose data may be used (within a retained withdrawal date)."""
    participants = {p.student.user_id: p for p in analysis_participants(study).select_related("student")}
    start, end, _label = reminder_window(study)
    qs = (Notification.objects.filter(recipient_id__in=list(participants), kind=NotificationKind.REMINDER, status=NotificationStatus.DELIVERED)
          .select_related("session__offering__course"))
    if start:
        qs = qs.filter(delivered_at__gte=start, delivered_at__lt=end)
    return [(participants[n.recipient_id], n) for n in qs if _within_retained_window(participants[n.recipient_id], n.delivered_at)]


def reminder_summary(study):
    rows = {g: {"participants": 0, "with_reminders": 0, "delivered": 0, "read": 0} for g in (Group.INTERVENTION, Group.CONTROL, "")}
    for g, n in group_counts(study).items():
        rows[g]["participants"] = n
    seen = {g: set() for g in rows}
    for participant, n in delivered_reminders(study):
        r = rows[participant.group]
        r["delivered"] += 1
        r["read"] += n.read_at is not None
        seen[participant.group].add(participant.pk)
    out = []
    for g, label in [(Group.INTERVENTION, "Intervention"), (Group.CONTROL, "Control"), ("", "Not allocated")]:
        r = rows[g]
        r["with_reminders"] = len(seen[g])
        r["read_rate"] = percent(r["read"], r["delivered"])
        r["label"] = label
        out.append(r)
    return {"rows": out, "window": reminder_window(study)[2]}


# ---- Dashboard -------------------------------------------------------------------------------------------------------
def completeness_by_period(study):
    """Share of expected measurements that were collected, per period (withdrawn participants left out of the denominator)."""
    rows = research_services.completeness(study)
    out = OrderedDict()
    for r in rows:
        agg = out.setdefault(r["period"], {"period": r["period"], "expected": 0, "collected": 0, "planned": 0, "missing": 0, "not_yet_collected": 0, "no_row": 0})
        agg["expected"] += r["total"] - r["counts"]["withdrawn"]
        for k in ("collected", "planned", "missing", "not_yet_collected", "no_row"):
            agg[k] += r["counts"][k]
    for agg in out.values():
        agg["rate"] = percent(agg["collected"], agg["expected"])
    return list(out.values()), rows


def dashboard(study):
    from . import quality  # local import: quality uses this module's helpers
    alpha = alpha_of(study)
    overview = research_services.study_overview(study)
    groups = group_counts(study)
    by_period, completeness_rows = completeness_by_period(study)
    summaries, chart_rows = [], []
    for outcome in OutcomeDefinition.objects.filter(study=study, is_active=True):
        data = outcome_values(study, outcome)
        entry = {"outcome": outcome, "periods": []}
        for period in outcome.periods():
            cells = []
            for g, label in GROUP_LABELS.items():
                values = [e[period] for e in data.values() if e["group"] == g and period in e]
                cells.append({"label": label, "summary": describe(values, alpha)})
                chart_rows.append((outcome, period, g, describe(values, alpha)["mean"]))
            entry["periods"].append({"period": Period(period).label, "cells": cells})
        summaries.append(entry)
    chart_labels = [o.name for o in OutcomeDefinition.objects.filter(study=study, is_active=True, unit="percent")]
    datasets = []
    for period in (Period.BASELINE, Period.POST):
        for g, label in GROUP_LABELS.items():
            datasets.append({"label": f"{label} - {Period(period).label}",
                             "data": [next((m for o, p, gg, m in chart_rows if o.name == name and p == period and gg == g), None) for name in chart_labels]})
    q_rows = []
    for q in Questionnaire.objects.filter(study=study).order_by("id"):
        c = q_services.completeness(q)
        q_rows.append({"questionnaire": q, **c})
    tam = analyse_tam(study)
    issues = quality.data_quality_issues(study)
    return {"study": study, "overview": overview, "groups": groups, "by_period": by_period, "completeness_rows": completeness_rows,
            "summaries": summaries, "reminders": reminder_summary(study), "questionnaires": q_rows, "tam": tam,
            "chart": {"outcomes": chart_labels, "datasets": datasets,
                      "groups": {"labels": ["Intervention", "Control", "Not allocated"], "values": [groups[Group.INTERVENTION], groups[Group.CONTROL], groups[""]]}},
            "ci_level": ci_level(alpha), "issues": issues, "issue_errors": sum(1 for i in issues if i["severity"] == "error"),
            "issue_warnings": sum(1 for i in issues if i["severity"] == "warning"), "design_note": DESIGN_NOTE}
