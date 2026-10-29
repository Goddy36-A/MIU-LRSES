from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudListView
from apps.research.views import ActiveStudyMixin

from . import services
from .forms import AssignForm, QuestionForm, QuestionnaireForm, ResponseForm
from .models import (Answer, Assignment, LIKERT_LABELS, Question, QuestionType, Questionnaire, QuestionnaireStatus, ResponseStatus)

RESEARCHER_ONLY = (Role.RESEARCHER,)
STUDENT_ONLY = (Role.STUDENT,)


class QuestionnaireMixin(ActiveStudyMixin):
    allowed_roles = RESEARCHER_ONLY

    def get_questionnaire(self, pk):
        return get_object_or_404(Questionnaire.objects.filter(study=self.study), pk=pk)


# ---- Researcher: building -------------------------------------------------------------------------------------------------------
class QuestionnaireList(QuestionnaireMixin, CrudListView):
    allowed_roles = RESEARCHER_ONLY
    model = Questionnaire
    title = "Questionnaires"
    subtitle = "Items are written by researchers and must be reviewed and approved before a questionnaire can be opened."
    columns = [("Title", "title"), ("Status", "get_status_display"), ("Period", lambda q: q.get_period_display() or "-"),
               ("Items approved", "items_approved"), ("Questions", lambda q: q.questions.count()), ("Assigned", lambda q: q.assignments.count())]
    search_fields = ("title",)
    add_url, detail_url = "questionnaires:add", "questionnaires:detail"
    empty_text = "No questionnaires yet."

    def get_queryset(self):
        return super().get_queryset().filter(study=self.study)


class QuestionnaireSave(QuestionnaireMixin, View):
    """Create (no pk) or edit (draft only)."""

    def get_obj(self, pk):
        if pk is None:
            return None
        q = self.get_questionnaire(pk)
        return q

    def get(self, request, pk=None):
        q = self.get_obj(pk)
        if q is not None and not q.items_editable:
            messages.error(request, "Only a draft questionnaire can be edited. Duplicate it to make a corrected version.")
            return redirect("questionnaires:detail", pk=q.pk)
        return self.render(QuestionnaireForm(instance=q), q)

    def post(self, request, pk=None):
        q = self.get_obj(pk)
        if q is not None and not q.items_editable:
            messages.error(request, "Only a draft questionnaire can be edited.")
            return redirect("questionnaires:detail", pk=q.pk)
        form = QuestionnaireForm(request.POST, instance=q)
        if form.is_valid():
            obj = form.save(commit=False)
            if q is None:
                obj.study, obj.created_by = self.study, request.user
            obj.save()
            if q is not None:
                services._withdraw_approval(obj)
            log_action("questionnaire_created" if q is None else "questionnaire_updated", actor=request.user, target=obj.title)
            messages.success(request, "Questionnaire saved.")
            return redirect("questionnaires:detail", pk=obj.pk)
        return self.render(form, q)

    def render(self, form, q):
        return render(self.request, "crud/form.html", {"form": form, "title": "Edit questionnaire" if q else "Add questionnaire",
                                                       "submit_label": "Save", "cancel_url": reverse("questionnaires:list")})


class QuestionnaireDetail(QuestionnaireMixin, TemplateView):
    template_name = "questionnaires/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.get_questionnaire(self.kwargs["pk"])
        ctx.update(q=q, questions=q.questions.prefetch_related("options"), assign_form=AssignForm(), likert=LIKERT_LABELS,
                   assigned=q.assignments.count(), QuestionnaireStatus=QuestionnaireStatus)
        return ctx


class QuestionnaireAction(QuestionnaireMixin, View):
    """POST-only state changes: approve, open, close, duplicate, assign."""

    def post(self, request, pk, action):
        q = self.get_questionnaire(pk)
        try:
            if action == "approve":
                services.approve_items(q, request.user)
                messages.success(request, "Items approved by you for use in the study.")
            elif action == "open":
                services.open_questionnaire(q, request.user)
                messages.success(request, "Questionnaire opened. Assign it to participants so they can answer.")
            elif action == "close":
                services.close_questionnaire(q, request.user)
                messages.success(request, "Questionnaire closed. Submitted responses are kept.")
            elif action == "duplicate":
                copy = services.duplicate_questionnaire(q, request.user)
                messages.success(request, "Copied into a new draft. Review and approve the items before opening it.")
                return redirect("questionnaires:detail", pk=copy.pk)
            elif action == "assign":
                form = AssignForm(request.POST)
                if not form.is_valid():
                    messages.error(request, "Choose who to assign the questionnaire to.")
                else:
                    created, existing = services.assign_questionnaire(q, request.user, target=form.cleaned_data["target"],
                                                                      due_date=form.cleaned_data["due_date"])
                    messages.success(request, f"Assigned to {created} participant(s); {existing} already had it.")
            else:
                raise ValidationError("Unknown action.")
        except ValidationError as exc:
            for m in exc.messages:
                messages.error(request, m)
        return redirect("questionnaires:detail", pk=pk)


class QuestionSave(QuestionnaireMixin, View):
    def get_question(self, pk, qid):
        q = self.get_questionnaire(pk)
        return q, (get_object_or_404(Question, pk=qid, questionnaire=q) if qid else None)

    def get(self, request, pk, qid=None):
        q, question = self.get_question(pk, qid)
        if not q.items_editable:
            messages.error(request, "Items can only be changed while the questionnaire is a draft.")
            return redirect("questionnaires:detail", pk=pk)
        initial = {"order": q.questions.count() + 1} if question is None else None
        return self.render(q, question, QuestionForm(instance=question, initial=initial))

    def post(self, request, pk, qid=None):
        q, question = self.get_question(pk, qid)
        form = QuestionForm(request.POST, instance=question)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.questionnaire = q
            try:
                services.save_question(obj, options_text=form.cleaned_data["options_text"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Question saved. Any earlier approval of the items has been withdrawn.")
                return redirect("questionnaires:detail", pk=pk)
        return self.render(q, question, form)

    def render(self, q, question, form):
        return render(self.request, "crud/form.html", {"form": form, "title": "Edit question" if question else "Add question",
                                                       "submit_label": "Save question", "cancel_url": reverse("questionnaires:detail", args=[q.pk])})


class QuestionDelete(QuestionnaireMixin, View):
    def post(self, request, pk, qid):
        q = self.get_questionnaire(pk)
        question = get_object_or_404(Question, pk=qid, questionnaire=q)
        try:
            services.delete_question(question)
            messages.success(request, "Question deleted.")
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return redirect("questionnaires:detail", pk=pk)


# ---- Researcher: responses and reports -----------------------------------------------------------------------------------------------
class ResponseList(QuestionnaireMixin, CrudListView):
    allowed_roles = RESEARCHER_ONLY
    model = Assignment
    title = "Responses"
    subtitle = "Identified by research code only."
    select_related = ("participant", "questionnaire")
    columns = [("Research code", "participant.research_code"), ("Group", lambda a: a.participant.get_group_display() or "-"),
               ("Status", lambda a: ("Withdrawn" if a.participant.is_withdrawn else
                                     (a.response.get_status_display() if hasattr(a, "response") else "Not started"))),
               ("Submitted", lambda a: a.response.submitted_at.strftime("%d %b %Y %H:%M") if hasattr(a, "response") and a.response.submitted_at else "-")]
    search_fields = ("participant__research_code",)
    search_help = "Research code"
    detail_url = "questionnaires:response_detail"

    def get_queryset(self):
        self.questionnaire = self.get_questionnaire(self.kwargs["pk"])
        return super().get_queryset().filter(questionnaire=self.questionnaire)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = f"Responses: {self.questionnaire.title}"
        return ctx


class ResponseDetail(QuestionnaireMixin, TemplateView):
    template_name = "questionnaires/response_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        a = get_object_or_404(Assignment.objects.select_related("participant", "questionnaire"), pk=self.kwargs["pk"], questionnaire__study=self.study)
        response = getattr(a, "response", None)
        questions = list(a.questionnaire.questions.prefetch_related("options"))
        answers = {x.question_id: x for x in response.answers.select_related("option")} if response else {}
        rows = [{"q": q, "a": answers.get(q.pk), "likert": LIKERT_LABELS.get(answers[q.pk].likert_value) if q.pk in answers and answers[q.pk].likert_value else None}
                for q in questions]
        scores = services.response_construct_scores(questions, answers.values()) if response else {}
        ctx.update(assignment=a, response=response, rows=rows, scores=[(k, round(v, 2) if v is not None else None) for k, v in scores.items()])
        return ctx


class Report(QuestionnaireMixin, TemplateView):
    template_name = "questionnaires/report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.get_questionnaire(self.kwargs["pk"])
        constructs = services.construct_summaries(q)
        chart = {"labels": [c["construct"] for c in constructs],
                 "datasets": [{"label": g, "data": [dict(c["groups"]).get(g, {}).get("mean") for c in constructs]}
                              for g in sorted({name for c in constructs for name, _ in c["groups"]}, key=lambda n: ["Intervention", "Control", "Not allocated"].index(n))]}
        ctx.update(q=q, completeness=services.completeness(q), summaries=services.question_summaries(q), constructs=constructs, chart=chart)
        return ctx


# ---- Student -------------------------------------------------------------------------------------------------------------------------
class MyQuestionnaires(RoleRequiredMixin, TemplateView):
    allowed_roles = STUDENT_ONLY
    template_name = "questionnaires/my_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["assignments"] = services.assignments_for_student(self.request.user)
        return ctx


class FillQuestionnaire(RoleRequiredMixin, View):
    allowed_roles = STUDENT_ONLY
    template_name = "questionnaires/fill.html"

    def get_assignment(self, pk):
        return get_object_or_404(services.assignments_for_student(self.request.user), pk=pk)

    def _form(self, a, data=None):
        questions = a.questionnaire.questions.prefetch_related("options")
        initial = {}
        response = getattr(a, "response", None)
        if response is not None:
            for ans in response.answers.all():
                initial[f"q{ans.question_id}"] = ans.likert_value if ans.likert_value is not None else (ans.option_id if ans.option_id else ans.text)
            initial = {k: str(v) if isinstance(v, int) else v for k, v in initial.items()}
        return ResponseForm(questions, data, initial=initial)

    def get(self, request, pk):
        a = self.get_assignment(pk)
        return self.render(a, self._form(a))

    def post(self, request, pk):
        a = self.get_assignment(pk)
        form = self._form(a, request.POST)
        if form.is_valid():
            submit = "submit" in request.POST
            try:
                services.save_response(a, form.raw_answers(), submit=submit)
            except ValidationError as exc:
                for m in exc.messages:
                    form.add_error(None, m)
            else:
                messages.success(request, "Thank you. Your answers were submitted." if submit else "Your answers were saved. You can finish later.")
                return redirect("questionnaires:my_list")
        return self.render(a, form)

    def render(self, a, form):
        response = getattr(a, "response", None)
        submitted = bool(response and response.is_submitted)
        return render(self.request, self.template_name, {"a": a, "form": form, "submitted": submitted,
                                                         "open": a.questionnaire.status == QuestionnaireStatus.OPEN})
