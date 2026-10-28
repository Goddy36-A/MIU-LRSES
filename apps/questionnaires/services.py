"""Questionnaire business logic. Views only call these functions.

Rules (documented in docs/QUESTIONNAIRES.md):
* Researchers write the items. The only built-in content is an *example* TAM questionnaire, labelled unapproved,
  which cannot be opened until a researcher has reviewed and approved the items.
* Items can only be edited while the questionnaire is a draft; any edit withdraws the researcher's approval.
  To change an opened questionnaire, duplicate it (responses to the original are never altered).
* Questionnaires are assigned only to enrolled, consenting, non-withdrawn participants, and only by explicit action.
* A participant can answer only their own assignment, only while the questionnaire is open, and only once it is
  submitted: a submitted response is locked. Drafts may be partial; submission requires every required item.
* Summaries use submitted responses only, and leave out participants who withdrew with "exclude all data".
  A construct score is the mean of the construct's Likert items (after reverse scoring) and exists only when every
  item of that construct was answered. Nothing is estimated or filled in.
"""
import statistics
from collections import Counter, OrderedDict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import get_student_profile
from apps.accounts.audit import log_action
from apps.attendance.services import percent
from apps.research.models import ConsentStatus, Eligibility, Group, Participant
from apps.research.services import enrolled_participants

from .models import (Answer, Assignment, Construct, LIKERT_CHOICES, MAX_TEXT_LENGTH, Option, Question, QuestionType,
                     Questionnaire, QuestionnaireStatus, Response, ResponseStatus, TAM_CONSTRUCTS)

# ---- Example content ---------------------------------------------------------------------------------------------------
EXAMPLE_TITLE = "EXAMPLE (not approved): Technology acceptance of the lecture reminder system"
EXAMPLE_ITEMS = [
    ("PU", "Receiving lecture reminders helps me keep track of my lectures."),
    ("PU", "The lecture reminders make me more likely to attend my lectures."),
    ("PU", "The lecture reminders help me stay on top of my coursework."),
    ("PEOU", "Learning to use the lecture reminder system was easy for me."),
    ("PEOU", "The reminder notifications are clear and easy to understand."),
    ("PEOU", "It is easy for me to find the notifications I need."),
    ("BI", "I intend to keep using the lecture reminders if they remain available."),
    ("BI", "I would recommend the lecture reminders to other students."),
    ("BI", "I would like lecture reminders to be available for all of my courses."),
]


@transaction.atomic
def create_example_tam(study, user):
    """Create an editable EXAMPLE questionnaire with three Likert items for each TAM construct. These items were written
    as a starting point only: they are not an approved or validated instrument and must be reviewed by a researcher."""
    q = Questionnaire.objects.create(
        study=study, title=EXAMPLE_TITLE, is_example=True, created_by=user, period="post_intervention",
        research_question="Example only. Replace with the study's approved research question.",
        instructions="Example only: these items need researcher review and approval before use.\n"
                     "Please rate how much you agree with each statement. Do not write your name in any comment box.")
    for i, (construct, text) in enumerate(EXAMPLE_ITEMS, start=1):
        Question.objects.create(questionnaire=q, order=i, text=text, qtype=QuestionType.LIKERT, construct=construct)
    Question.objects.create(questionnaire=q, order=len(EXAMPLE_ITEMS) + 1, text="Any other comments about the lecture reminders? (optional; do not write your name)",
                            qtype=QuestionType.TEXT, required=False)
    log_action("questionnaire_example_created", actor=user, target=q.title)
    return q


# ---- Building ----------------------------------------------------------------------------------------------------------------
def _require_draft(q):
    if not q.items_editable:
        raise ValidationError("Items can only be changed while the questionnaire is a draft. Duplicate it to make a corrected version.")


def _withdraw_approval(q):
    if q.items_approved:
        q.items_approved, q.approved_by, q.approved_at = False, None, None
        q.save(update_fields=["items_approved", "approved_by", "approved_at", "updated_at"])


def parse_options(text):
    labels = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(set(l.lower() for l in labels)) != len(labels):
        raise ValidationError("Each option must be different.")
    return labels


@transaction.atomic
def save_question(question, *, options_text=""):
    """Save an edited or new question (already populated) and its options; withdraws any earlier approval."""
    q = question.questionnaire
    _require_draft(q)
    labels = parse_options(options_text) if question.qtype == QuestionType.CHOICE else []
    if question.qtype == QuestionType.CHOICE and len(labels) < 2:
        raise ValidationError("A multiple-choice question needs at least two options (one per line).")
    question.full_clean(exclude=["questionnaire"])
    question.save()
    question.options.all().delete()
    Option.objects.bulk_create([Option(question=question, order=i, label=label) for i, label in enumerate(labels, start=1)])
    _withdraw_approval(q)
    return question


@transaction.atomic
def delete_question(question):
    q = question.questionnaire
    _require_draft(q)
    question.delete()
    _withdraw_approval(q)


@transaction.atomic
def approve_items(q, user):
    _require_draft(q)
    if not q.questions.exists():
        raise ValidationError("Add at least one question before approving.")
    q.items_approved, q.is_example, q.approved_by, q.approved_at = True, False, user, timezone.now()
    q.save()
    log_action("questionnaire_items_approved", actor=user, target=q.title)


def validate_ready_to_open(q):
    problems = []
    if not q.items_approved:
        problems.append("A researcher must review and approve the items first." + (" This is still example content." if q.is_example else ""))
    questions = list(q.questions.prefetch_related("options"))
    if not questions:
        problems.append("The questionnaire has no questions.")
    for question in questions:
        if question.qtype == QuestionType.CHOICE and question.options.count() < 2:
            problems.append(f"Question {question.order} needs at least two options.")
    if problems:
        raise ValidationError(problems)


@transaction.atomic
def open_questionnaire(q, user):
    if q.status == QuestionnaireStatus.OPEN:
        raise ValidationError("This questionnaire is already open.")
    validate_ready_to_open(q)
    q.status, q.closed_at = QuestionnaireStatus.OPEN, None
    q.opened_at = q.opened_at or timezone.now()
    q.save()
    log_action("questionnaire_opened", actor=user, target=q.title)


@transaction.atomic
def close_questionnaire(q, user):
    if q.status != QuestionnaireStatus.OPEN:
        raise ValidationError("Only an open questionnaire can be closed.")
    q.status, q.closed_at = QuestionnaireStatus.CLOSED, timezone.now()
    q.save()
    log_action("questionnaire_closed", actor=user, target=q.title)


@transaction.atomic
def duplicate_questionnaire(q, user):
    """Copy items into a new draft (no assignments, no responses, approval withdrawn)."""
    copy = Questionnaire.objects.create(
        study=q.study, title=f"Copy of {q.title}"[:200], instructions=q.instructions, research_question=q.research_question,
        period=q.period, is_example=q.is_example, created_by=user)
    for question in q.questions.prefetch_related("options"):
        new = Question.objects.create(questionnaire=copy, order=question.order, text=question.text, qtype=question.qtype,
                                      construct=question.construct, required=question.required, reverse_scored=question.reverse_scored)
        Option.objects.bulk_create([Option(question=new, order=o.order, label=o.label) for o in question.options.all()])
    log_action("questionnaire_duplicated", actor=user, target=copy.title)
    return copy


# ---- Assignment -----------------------------------------------------------------------------------------------------------------
ASSIGN_TARGETS = [("all", "All enrolled participants"), ("intervention", "Intervention group only"), ("control", "Control group only")]


@transaction.atomic
def assign_questionnaire(q, user, *, target, due_date=None):
    """Assign an open questionnaire to enrolled, consenting, non-withdrawn participants. Idempotent: participants who
    already have it are left alone. Returns (created, already_assigned)."""
    if q.status != QuestionnaireStatus.OPEN:
        raise ValidationError("Only an open questionnaire can be assigned.")
    people = enrolled_participants(q.study)
    if target == "intervention":
        people = people.filter(group=Group.INTERVENTION)
    elif target == "control":
        people = people.filter(group=Group.CONTROL)
    elif target != "all":
        raise ValidationError("Choose who the questionnaire is for.")
    have = set(Assignment.objects.filter(questionnaire=q).values_list("participant_id", flat=True))
    new = [Assignment(questionnaire=q, participant=p, due_date=due_date, assigned_by=user) for p in people if p.pk not in have]
    Assignment.objects.bulk_create(new)
    log_action("questionnaire_assigned", actor=user, target=q.title, details=f"{len(new)} participant(s) assigned; target={target}")
    return len(new), len(have & {p.pk for p in people})


# ---- Students answering ------------------------------------------------------------------------------------------------------
def participations_for(user):
    """The student's own participations that currently allow data use (enrolled, consented, not withdrawn)."""
    profile = get_student_profile(user)
    if profile is None:
        return Participant.objects.none()
    return Participant.objects.filter(student=profile, enrolled_on__isnull=False, eligibility=Eligibility.ELIGIBLE,
                                      consent_status=ConsentStatus.GIVEN, withdrawn_on__isnull=True)


def assignments_for_student(user):
    from django.db.models import Q
    return (Assignment.objects.filter(participant__in=participations_for(user))
            .filter(Q(questionnaire__status=QuestionnaireStatus.OPEN) | Q(response__status=ResponseStatus.SUBMITTED))
            .select_related("questionnaire", "response").order_by("-assigned_at"))


def pending_count(user):
    return assignments_for_student(user).exclude(response__status=ResponseStatus.SUBMITTED).filter(
        questionnaire__status=QuestionnaireStatus.OPEN).count()


def _clean_answer(question, raw):
    """Return the validated value for a question or None if blank. Raises ValidationError with a clear message."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    label = f"Question {question.order}"
    if question.qtype == QuestionType.LIKERT:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValidationError(f"{label}: choose one of the five options.")
        if value not in dict(LIKERT_CHOICES):
            raise ValidationError(f"{label}: the answer must be between 1 and 5.")
        return value
    if question.qtype == QuestionType.CHOICE:
        try:
            option = question.options.get(pk=int(raw))
        except (TypeError, ValueError, Option.DoesNotExist):
            raise ValidationError(f"{label}: choose one of the listed options.")
        return option
    text = str(raw).strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise ValidationError(f"{label}: the comment is too long (maximum {MAX_TEXT_LENGTH} characters).")
    return text


@transaction.atomic
def save_response(assignment, answers, *, submit):
    """Save (and optionally submit) a participant's answers. ``answers`` maps question id -> raw value or blank.
    Raises ValidationError (and saves nothing) if anything is invalid."""
    assignment = Assignment.objects.select_related("questionnaire", "participant").get(pk=assignment.pk)
    q, participant = assignment.questionnaire, assignment.participant
    p = Participant.objects.get(pk=participant.pk)
    if not p.is_enrolled:
        raise ValidationError("You can no longer answer this questionnaire.")
    if q.status != QuestionnaireStatus.OPEN:
        raise ValidationError("This questionnaire is not open.")
    response, _ = Response.objects.get_or_create(assignment=assignment)
    if response.is_submitted:
        raise ValidationError("This questionnaire has already been submitted and can no longer be changed.")
    questions = list(q.questions.prefetch_related("options"))
    errors, cleaned = [], {}
    for question in questions:
        try:
            cleaned[question.pk] = _clean_answer(question, answers.get(question.pk))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)
    for question in questions:
        value = cleaned[question.pk]
        if value is None:
            Answer.objects.filter(response=response, question=question).delete()
            continue
        fields = {"likert_value": None, "option": None, "text": ""}
        if question.qtype == QuestionType.LIKERT:
            fields["likert_value"] = value
        elif question.qtype == QuestionType.CHOICE:
            fields["option"] = value
        else:
            fields["text"] = value
        Answer.objects.update_or_create(response=response, question=question, defaults=fields)
    if submit:
        missing = [str(question.order) for question in questions if question.required and cleaned[question.pk] is None]
        if missing:
            raise ValidationError("Please answer every required question before submitting. Missing: question " + ", ".join(missing) + ".")
        response.status, response.submitted_at = ResponseStatus.SUBMITTED, timezone.now()
        response.save()
    else:
        response.save()  # refreshes updated_at
    return response


# ---- Reporting (researcher) -----------------------------------------------------------------------------------------------------
GROUP_LABELS = OrderedDict([(Group.INTERVENTION, "Intervention"), (Group.CONTROL, "Control"), ("", "Not allocated")])


def usable_responses(q):
    """Submitted responses, excluding participants who withdrew with 'exclude all of my data'."""
    return (Response.objects.filter(assignment__questionnaire=q, status=ResponseStatus.SUBMITTED)
            .exclude(assignment__participant__withdrawn_on__isnull=False, assignment__participant__withdrawal_data_handling="exclude")
            .select_related("assignment__participant").prefetch_related("answers"))


def completeness(q):
    """Response counts and rates. Withdrawn participants are shown separately and left out of the response rate."""
    assignments = list(q.assignments.select_related("participant", "response"))
    active = [a for a in assignments if not a.participant.is_withdrawn]
    submitted = sum(1 for a in active if hasattr(a, "response") and a.response.is_submitted)
    draft = sum(1 for a in active if hasattr(a, "response") and not a.response.is_submitted)
    usable = list(usable_responses(q))
    rows = []
    for question in q.questions.all():
        answered = sum(1 for r in usable if any(a.question_id == question.pk and _has_value(a) for a in r.answers.all()))
        rows.append({"question": question, "answered": answered, "skipped": len(usable) - answered,
                     "answered_pct": percent(answered, len(usable))})
    return {"assigned": len(assignments), "eligible_to_answer": len(active), "withdrawn": len(assignments) - len(active),
            "not_started": len(active) - submitted - draft, "in_progress": draft, "submitted": submitted,
            "response_rate": percent(submitted, len(active)), "usable": len(usable), "questions": rows}


def _has_value(answer):
    return answer.likert_value is not None or answer.option_id is not None or bool(answer.text)


def question_summaries(q):
    """Per-question descriptive summaries over usable responses."""
    usable = list(usable_responses(q))
    by_question = {}
    for r in usable:
        for a in r.answers.all():
            by_question.setdefault(a.question_id, []).append(a)
    out = []
    for question in q.questions.prefetch_related("options"):
        answers = by_question.get(question.pk, [])
        row = {"question": question, "n": len([a for a in answers if _has_value(a)])}
        if question.qtype == QuestionType.LIKERT:
            values = [a.likert_value for a in answers if a.likert_value is not None]
            counts = Counter(values)
            row.update(counts=[(v, label, counts.get(v, 0)) for v, label in LIKERT_CHOICES],
                       mean=round(statistics.mean(values), 2) if values else None)
        elif question.qtype == QuestionType.CHOICE:
            counts = Counter(a.option_id for a in answers if a.option_id)
            row["counts"] = [(o.pk, o.label, counts.get(o.pk, 0)) for o in question.options.all()]
        out.append(row)
    return out


def response_construct_scores(questions, answers):
    """{construct: score or None} for one response. questions: iterable of Question; answers: iterable of Answer."""
    given = {a.question_id: a.likert_value for a in answers if a.likert_value is not None}
    scores = {}
    for construct in TAM_CONSTRUCTS:
        items = [qu for qu in questions if qu.construct == construct and qu.qtype == QuestionType.LIKERT]
        if not items:
            continue
        if any(qu.pk not in given for qu in items):
            scores[construct] = None
            continue
        values = [(6 - given[qu.pk]) if qu.reverse_scored else given[qu.pk] for qu in items]
        scores[construct] = statistics.mean(values)
    return scores


def _describe(values):
    if not values:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {"n": len(values), "mean": round(statistics.mean(values), 2),
            "sd": round(statistics.stdev(values), 2) if len(values) > 1 else None, "min": round(min(values), 2), "max": round(max(values), 2)}


def construct_summaries(q):
    """Descriptive TAM construct scores per group. Returns a list of dicts, one per construct present in the questionnaire.
    Only participants with every item of the construct answered contribute (incomplete ones are counted, not estimated)."""
    questions = list(q.questions.all())
    constructs = [c for c in TAM_CONSTRUCTS if any(qu.construct == c for qu in questions)]
    scored = {c: {g: [] for g in GROUP_LABELS} for c in constructs}
    incomplete = Counter()
    for r in usable_responses(q):
        scores = response_construct_scores(questions, r.answers.all())
        group = r.assignment.participant.group
        for c in constructs:
            if scores.get(c) is None:
                incomplete[c] += 1
            else:
                scored[c][group].append(scores[c])
    out = []
    for c in constructs:
        everyone = [v for g in scored[c].values() for v in g]
        out.append({"construct": c, "label": Construct(c).label, "items": sum(1 for qu in questions if qu.construct == c),
                    "overall": _describe(everyone), "incomplete": incomplete[c],
                    "groups": [(GROUP_LABELS[g], _describe(scored[c][g])) for g in GROUP_LABELS if scored[c][g]]})
    return out
