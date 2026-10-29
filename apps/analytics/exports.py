"""CSV exports of research data and the data dictionary that describes them.

Design rules (docs/ANALYTICS.md):
* One definition per dataset: the ``fields`` list is both the CSV header and the data dictionary, and a test checks that
  every row has exactly those fields, so the dictionary cannot drift from the files.
* Rows use the anonymous research code. No name, registration number, email, username, password, token or contact detail
  is ever exported. Free-text fields (research notes, missing-value reasons, free-text questionnaire answers) are not
  exported because researchers may have typed identifying details into them.
* Only data that may be used (see services.analysis_participants) is exported. Original values are written exactly as
  stored; nothing is rounded, imputed, filled in or corrected.
* Cells that a spreadsheet could execute as a formula are neutralised (see ``safe_cell``).
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from django.utils import timezone

from apps.questionnaires import services as q_services
from apps.questionnaires.models import Questionnaire
from apps.research import services as research_services
from apps.research.models import MeasurementStatus, Measurement, OutcomeKind, Period

from . import quality, services


@dataclass(frozen=True)
class Field:
    name: str
    meaning: str
    values: str
    calc: str = "Copied from the stored record."


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    description: str
    fields: tuple
    rows: Callable

    @property
    def filename_stem(self):
        return self.key.replace("_", "-")

    @property
    def header(self):
        return [f.name for f in self.fields]


YES_NO = "yes / no"
GROUP_VALUES = "intervention, control, or empty (enrolled but not yet allocated)"
DATE_VALUE = "ISO date YYYY-MM-DD, or empty"
STAMP_VALUE = "ISO date-time with UTC offset (Africa/Kampala is +03:00), or empty"

CODE = Field("research_code", "Anonymous participant identifier assigned when the student was registered in the study. "
                              "It is not derived from the student's name or number.", "P- followed by 6 letters/digits, e.g. P-7KQ2MX")
GROUP = Field("group", "The participant's current study group.", GROUP_VALUES,
              "Latest allocation recorded by the researcher; the system never randomises.")


# ---- CSV formatting ------------------------------------------------------------------------------------------------
def safe_cell(value):
    """Neutralise spreadsheet formula injection: text starting with = + - @ tab or CR is prefixed with an apostrophe."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return safe_cell(value)
    return str(value)


# ---- Row builders ---------------------------------------------------------------------------------------------------
def participant_rows(study):
    for p in services.analysis_participants(study).select_related("student").prefetch_related("allocations").order_by("research_code"):
        allocs = sorted(p.allocations.all(), key=lambda a: a.id)
        last = allocs[-1] if allocs else None
        yield {"research_code": p.research_code, "year_of_study": p.student.year_of_study, "eligibility": p.eligibility,
               "consent_status": p.consent_status, "consent_date": p.consent_date, "enrolled_on": p.enrolled_on, "group": p.group,
               "allocation_method": last.method if last else None, "allocation_date": last.allocation_date if last else None,
               "allocation_count": len(allocs), "reallocated": any(a.is_reallocation for a in allocs),
               "withdrawn": p.is_withdrawn, "withdrawn_on": p.withdrawn_on, "withdrawal_data_handling": p.withdrawal_data_handling or None}


def measurement_rows(study, *, kinds=None, period=None):
    qs = (Measurement.objects.filter(participant__in=services.analysis_participants(study), outcome__study=study)
          .select_related("participant", "outcome__study").order_by("participant__research_code", "outcome__code", "period"))
    if kinds:
        qs = qs.filter(outcome__kind__in=kinds)
    if period:
        qs = qs.filter(period=period)
    today = timezone.localdate()
    for m in qs:
        p = m.participant
        if m.status == MeasurementStatus.COLLECTED and p.withdrawn_on and m.collected_on > p.withdrawn_on:
            continue  # collected after a retained withdrawal: not usable
        collected = m.status == MeasurementStatus.COLLECTED
        yield {"research_code": p.research_code, "group": p.group, "outcome_code": m.outcome.code, "outcome_name": m.outcome.name,
               "outcome_kind": m.outcome.kind, "unit": m.outcome.unit, "period": m.period, "status": m.status,
               "state": research_services.display_state(m, today), "value": m.value if collected else None,
               "collected_on": m.collected_on if collected else None, "source": m.source or None,
               "calculation_detail": m.calculation_detail if collected else None}


def _kind_rows(*kinds):
    return lambda study: measurement_rows(study, kinds=kinds)


def questionnaire_answer_rows(study):
    for q in Questionnaire.objects.filter(study=study).order_by("id").prefetch_related("questions__options"):
        questions = list(q.questions.all())
        for r in sorted(services.analysis_responses(study, q), key=lambda r: r.assignment.participant.research_code):
            p = r.assignment.participant
            answers = {a.question_id: a for a in r.answers.all()}
            for qu in questions:
                a = answers.get(qu.pk)
                answered = bool(a and (a.likert_value is not None or a.option_id or a.text))
                scored = None
                if a and a.likert_value is not None:
                    scored = (6 - a.likert_value) if qu.reverse_scored else a.likert_value
                yield {"research_code": p.research_code, "group": p.group, "questionnaire_id": q.pk, "questionnaire_title": q.title,
                       "questionnaire_period": q.period or None, "submitted_at": r.submitted_at, "question_id": qu.pk,
                       "question_order": qu.order, "question_text": qu.text, "question_type": qu.qtype, "construct": qu.construct or None,
                       "reverse_scored": qu.reverse_scored, "answered": answered, "likert_value": a.likert_value if a else None,
                       "scored_value": scored, "option_label": a.option.label if a and a.option_id else None,
                       "text_provided": bool(a and a.text) if qu.qtype == "text" else None}


def construct_score_rows(study):
    for q in Questionnaire.objects.filter(study=study).order_by("id"):
        questions = list(q.questions.all())
        for r in sorted(services.analysis_responses(study, q), key=lambda r: r.assignment.participant.research_code):
            p = r.assignment.participant
            scores = q_services.response_construct_scores(questions, r.answers.all())
            for construct, score in scores.items():
                items = sum(1 for qu in questions if qu.construct == construct and qu.qtype == "likert")
                yield {"research_code": p.research_code, "group": p.group, "questionnaire_id": q.pk, "questionnaire_title": q.title,
                       "questionnaire_period": q.period or None, "submitted_at": r.submitted_at, "construct": construct,
                       "items_in_construct": items, "score": score, "complete": score is not None}


def reminder_event_rows(study):
    rows = services.delivered_reminders(study)
    for participant, n in sorted(rows, key=lambda t: (t[0].research_code, t[1].delivered_at)):
        minutes = None
        if n.read_at:
            minutes = round((n.read_at - n.delivered_at).total_seconds() / 60.0, 1)
        yield {"research_code": participant.research_code, "group": participant.group, "course_code": n.session.offering.course.code,
               "lecture_date": services._local_date(n.session.start_at), "minutes_before": n.minutes_before,
               "delivered_at": n.delivered_at, "read_at": n.read_at, "is_read": n.read_at is not None, "minutes_to_read": minutes}


# ---- Dataset definitions (header + dictionary) ----------------------------------------------------------------------
MEASUREMENT_FIELDS = (
    CODE, GROUP,
    Field("outcome_code", "Short code of the outcome definition (set by the researcher).", "e.g. attendance-rate"),
    Field("outcome_name", "Name of the outcome.", "Text from the outcome definition"),
    Field("outcome_kind", "Type of outcome.", ", ".join(OutcomeKind.values)),
    Field("unit", "Unit of the value.", "e.g. percent, score, count"),
    Field("period", "Measurement period.", ", ".join(Period.values)),
    Field("status", "Stored status of the measurement.", ", ".join(MeasurementStatus.values)),
    Field("state", "Status as shown in the application, which also separates overdue and withdrawn rows.",
          "collected, planned, not_yet_collected, missing, not_applicable, withdrawn",
          "planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew."),
    Field("value", "The measured value. Empty unless the status is collected (never zero-filled).", "Decimal number within the outcome's range, or empty",
          "For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher."),
    Field("collected_on", "Date the value was collected or calculated.", DATE_VALUE),
    Field("source", "How the value was obtained.", "manual (entered by a researcher), system (calculated from system records), or empty"),
    Field("calculation_detail", "Inputs the system used when it calculated the value (counts, rules applied).", "Text, or empty for manual values"),
)


def _measurement_dataset(key, title, description, rows):
    return Dataset(key, title, description, MEASUREMENT_FIELDS, rows)


DATASETS = [
    Dataset("participants", "Participant study records",
            "One row per participant whose data may be used (eligible, consent given, enrolled; withdrawn participants only if they chose to keep their data). "
            "Participants who declined, were ineligible, never enrolled, or withdrew with \"exclude all data\" are not listed.",
            (CODE,
             Field("year_of_study", "Student's year of study as recorded in the system at export time.", "1 to 6"),
             Field("eligibility", "Eligibility decision recorded by the researcher.", "eligible"),
             Field("consent_status", "Consent status.", "given"),
             Field("consent_date", "Date consent was given.", DATE_VALUE),
             Field("enrolled_on", "Date the participant was enrolled in the study.", DATE_VALUE),
             GROUP,
             Field("allocation_method", "How the latest allocation was made (the full procedure text is not exported).",
                   "manual, external_randomisation, other, or empty if not allocated"),
             Field("allocation_date", "Date of the latest allocation.", DATE_VALUE),
             Field("allocation_count", "Number of allocation records (more than 1 means the participant was re-allocated).", "0, 1, 2, ..."),
             Field("reallocated", "Whether the participant was ever moved between groups.", YES_NO),
             Field("withdrawn", "Whether the participant has withdrawn.", YES_NO),
             Field("withdrawn_on", "Date of withdrawal.", DATE_VALUE),
             Field("withdrawal_data_handling", "What the participant chose for data collected before withdrawal.", "retain, or empty if not withdrawn")),
            participant_rows),
    _measurement_dataset("attendance", "Attendance outcomes",
                         "Lecture attendance rate measurements (baseline and post-intervention), including planned and missing rows.", _kind_rows(OutcomeKind.ATTENDANCE)),
    _measurement_dataset("punctuality", "Assignment punctuality",
                         "Assignment punctuality rate measurements (baseline and post-intervention), including planned and missing rows.", _kind_rows(OutcomeKind.PUNCTUALITY)),
    _measurement_dataset("performance", "Academic performance",
                         "Academic assessment score measurements (baseline and post-intervention), including planned and missing rows.", _kind_rows(OutcomeKind.ASSESSMENT)),
    _measurement_dataset("baseline", "Baseline measurements",
                         "Every baseline measurement of every outcome, including planned, missing and not-applicable rows.", lambda study: measurement_rows(study, period=Period.BASELINE)),
    _measurement_dataset("post_intervention", "Post-intervention measurements",
                         "Every post-intervention measurement of every outcome, including planned, missing and not-applicable rows.", lambda study: measurement_rows(study, period=Period.POST)),
    Dataset("questionnaire_responses", "Questionnaire responses",
            "One row per question per submitted response (so skipped questions appear as unanswered). Free-text answers are not exported.",
            (CODE, GROUP,
             Field("questionnaire_id", "Identifier of the questionnaire.", "Integer"),
             Field("questionnaire_title", "Title of the questionnaire.", "Text"),
             Field("questionnaire_period", "Measurement period the questionnaire is tied to.", "baseline, post_intervention, or empty"),
             Field("submitted_at", "When the participant submitted the response.", STAMP_VALUE),
             Field("question_id", "Identifier of the question.", "Integer"),
             Field("question_order", "Position of the question in the questionnaire.", "1, 2, ..."),
             Field("question_text", "The question as asked.", "Text"),
             Field("question_type", "Type of question.", "likert, choice, text"),
             Field("construct", "Technology Acceptance Model construct the item measures.", "PU, PEOU, BI, or empty"),
             Field("reverse_scored", "Whether a Likert item is negatively worded and flipped for construct scores.", YES_NO),
             Field("answered", "Whether the participant answered this question.", YES_NO),
             Field("likert_value", "The answer as given on the five-point scale.", "1 Strongly disagree, 2 Disagree, 3 Neither, 4 Agree, 5 Strongly agree; empty if not a Likert answer"),
             Field("scored_value", "Likert value used for scoring.", "1 to 5, or empty", "6 minus likert_value for reverse-scored items; otherwise equal to likert_value."),
             Field("option_label", "Selected option of a multiple-choice question.", "Text, or empty"),
             Field("text_provided", "For free-text questions, whether any text was written (the text itself is not exported).", "yes / no, or empty for other types")),
            questionnaire_answer_rows),
    Dataset("construct_scores", "TAM construct scores",
            "One row per submitted response and Technology Acceptance Model construct present in the questionnaire.",
            (CODE, GROUP,
             Field("questionnaire_id", "Identifier of the questionnaire.", "Integer"),
             Field("questionnaire_title", "Title of the questionnaire.", "Text"),
             Field("questionnaire_period", "Measurement period the questionnaire is tied to.", "baseline, post_intervention, or empty"),
             Field("submitted_at", "When the participant submitted the response.", STAMP_VALUE),
             Field("construct", "Technology Acceptance Model construct.", "PU (Perceived Usefulness), PEOU (Perceived Ease of Use), BI (Behavioural Intention)"),
             Field("items_in_construct", "Number of Likert items in the construct.", "Integer"),
             Field("score", "Construct score, empty when any item of the construct was not answered (nothing is estimated).", "1.0 to 5.0, or empty",
                   "Mean of the construct's Likert items after reverse scoring (6 minus value for reverse-scored items)."),
             Field("complete", "Whether every item of the construct was answered.", YES_NO)),
            construct_score_rows),
    Dataset("reminder_events", "Reminder interaction events",
            "One row per lecture reminder delivered to a participant (to their in-app notifications), within the post-intervention window if set, otherwise all delivered reminders. "
            "Control-group participants are not sent reminders, so they normally have no rows.",
            (CODE, GROUP,
             Field("course_code", "Code of the course the lecture belongs to.", "e.g. BIT101"),
             Field("lecture_date", "Date of the lecture the reminder was about (Africa/Kampala).", "ISO date YYYY-MM-DD"),
             Field("minutes_before", "How long before the lecture the reminder was scheduled.", "Integer minutes, e.g. 1440, 60, 15"),
             Field("delivered_at", "When the reminder became visible in the participant's notifications.", STAMP_VALUE),
             Field("read_at", "When the participant opened (marked read) the reminder.", STAMP_VALUE),
             Field("is_read", "Whether the reminder was opened.", YES_NO),
             Field("minutes_to_read", "Minutes between delivery and opening.", "Decimal number, or empty if unread", "(read_at - delivered_at) in minutes, one decimal place.")),
            reminder_event_rows),
]
DATASET_BY_KEY = {d.key: d for d in DATASETS}

QUALITY_FIELDS = (
    Field("severity", "Seriousness of the finding.", "error (an inconsistency to fix before analysis), warning (missing or incomplete data)"),
    Field("code", "Short code of the check.", "Text"),
    Field("message", "What was found.", "Text"),
    Field("count", "Number of participants (or records) affected.", "Integer"),
    Field("example_research_codes", "Up to 10 research codes affected, separated by semicolons.", "Text"),
)


# ---- Output ----------------------------------------------------------------------------------------------------------
def write_csv(header, rows):
    """CSV text (RFC 4180, comma separated, UTF-8, CRLF line endings) for a header and an iterable of lists."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def dataset_csv(dataset, study):
    """Returns (csv_text, row_count)."""
    rows = []
    for row in dataset.rows(study):
        if set(row) != set(dataset.header):  # guards against the dictionary and the data drifting apart
            raise AssertionError(f"Row fields {sorted(row)} do not match the dictionary for {dataset.key}.")
        rows.append([format_value(row[name]) for name in dataset.header])
    return write_csv(dataset.header, rows), len(rows)


def quality_csv(study):
    issues = quality.data_quality_issues(study)
    rows = [[format_value(i["severity"]), format_value(i["code"]), format_value(i["message"]), i["count"], "; ".join(i["examples"])] for i in issues]
    return write_csv([f.name for f in QUALITY_FIELDS], rows), len(rows)


def dictionary_rows():
    rows = []
    for d in DATASETS:
        for f in d.fields:
            rows.append([d.key, f.name, f.meaning, f.values, f.calc])
    for f in QUALITY_FIELDS:
        rows.append(["data_quality_report", f.name, f.meaning, f.values, f.calc])
    return rows


def dictionary_csv():
    return write_csv(["dataset", "field", "meaning", "permitted_values", "how_calculated"], [[safe_cell(c) for c in r] for r in dictionary_rows()])


def dictionary_markdown():
    lines = ["# Research data dictionary", "",
             "Generated from the dataset definitions in `apps/analytics/exports.py` (`python manage.py export_data_dictionary`). "
             "Every CSV starts with a header row naming these fields, in this order. Empty cells mean \"not applicable or not available\", "
             "never zero. Files are comma-separated, UTF-8, with CRLF line endings. Dates are ISO (YYYY-MM-DD); date-times carry a UTC offset "
             "(Africa/Kampala is +03:00); yes/no fields are written `yes` or `no`.", "",
             "No dataset contains names, registration numbers, emails, usernames, passwords, tokens or free text typed by researchers or participants. "
             "Text cells that start with `=`, `+`, `-` or `@` are prefixed with an apostrophe so spreadsheets do not run them as formulas.", ""]
    for d in DATASETS:
        lines += [f"## {d.title} (`{d.key}`)", "", d.description, "", "| Field | Meaning | Permitted values | How calculated |", "|---|---|---|---|"]
        lines += [f"| `{f.name}` | {f.meaning} | {f.values} | {f.calc} |" for f in d.fields]
        lines.append("")
    lines += ["## Data quality report (`data_quality_report`)", "", "Findings of the automatic checks. The checks only report; they never change the data.", "",
              "| Field | Meaning | Permitted values | How calculated |", "|---|---|---|---|"]
    lines += [f"| `{f.name}` | {f.meaning} | {f.values} | {f.calc} |" for f in QUALITY_FIELDS]
    return "\n".join(lines) + "\n"
