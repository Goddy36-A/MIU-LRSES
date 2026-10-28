from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin
from apps.core.crud import CrudCreateView, CrudListView, CrudUpdateView

from . import services
from .forms import (AllocationForm, MeasurementForm, OutcomeDefinitionForm, ParticipantRegisterForm, ParticipantUpdateForm,
                    ResearchStudyForm, WithdrawForm)
from .models import (ConsentStatus, Eligibility, Group, Measurement, MeasurementStatus, OutcomeDefinition, OutcomeSource,
                     Participant, Period, ResearchStudy, StudyStatus)

STUDY_ROLES = (Role.ADMIN, Role.RESEARCHER)   # may configure the protocol settings (no participant data)
RESEARCHER_ONLY = (Role.RESEARCHER,)          # participant-level data


class ActiveStudyMixin(RoleRequiredMixin):
    """Researcher pages work on the active study; if there is none the researcher is sent to the study list."""

    allowed_roles = RESEARCHER_ONLY

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role in self.allowed_roles:
            self.study = services.get_active_study()
            if self.study is None:
                messages.info(request, "There is no active study yet. Create one, or mark an existing study as active.")
                return redirect("research:study_list")
        return super().dispatch(request, *args, **kwargs)


# ---- Studies (administrators and researchers: configuration only) ----------------------------------------------------
class StudyList(CrudListView):
    allowed_roles = STUDY_ROLES
    model = ResearchStudy
    title = "Research studies"
    subtitle = "Protocol settings. The planning figures are editable defaults from the proposal, not recruitment results."
    columns = [("Title", "title"), ("Status", "get_status_display"), ("Active", "is_active"), ("Sample (planned)", "target_sample_size"),
               ("Intervention weeks", "intervention_weeks")]
    search_fields = ("title",)
    add_url, edit_url, detail_url = "research:study_add", "research:study_edit", "research:study_detail"
    empty_text = "No study has been set up yet."


class StudyCreate(CrudCreateView):
    allowed_roles = STUDY_ROLES
    model, form_class, title, entity = ResearchStudy, ResearchStudyForm, "Add research study", "research_study"
    success_url = reverse_lazy("research:study_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        added = services.ensure_default_outcomes(self.object)
        messages.info(self.request, f"{added} standard outcome definitions were added. Check them against the approved protocol.")
        return response


class StudyUpdate(CrudUpdateView):
    allowed_roles = STUDY_ROLES
    model, form_class, title, entity = ResearchStudy, ResearchStudyForm, "Edit research study", "research_study"
    success_url = reverse_lazy("research:study_list")

    def form_valid(self, form):
        changed = ", ".join(form.changed_data)
        response = super().form_valid(form)
        log_action("research_study_settings_changed", actor=self.request.user, target=str(self.object),
                   details=f"changed fields: {changed or 'none'}", request=self.request)
        return response


class StudyDetail(RoleRequiredMixin, TemplateView):
    allowed_roles = STUDY_ROLES
    template_name = "research/study_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        study = get_object_or_404(ResearchStudy, pk=self.kwargs["pk"])
        ctx.update(study=study, overview=services.study_overview(study), is_researcher=self.request.user.is_researcher,
                   baseline_window=study.baseline_window, post_window=study.post_window)
        return ctx


class StudyPlanView(RoleRequiredMixin, View):
    allowed_roles = RESEARCHER_ONLY

    def post(self, request, pk):
        study = get_object_or_404(ResearchStudy, pk=pk)
        created = services.plan_measurements(study, request.user)
        messages.success(request, f"{created} planned measurement(s) created." if created else "Nothing to plan: every enrolled participant already has all expected measurements.")
        return redirect("research:measurement_list")


class StudyCalculateView(RoleRequiredMixin, View):
    allowed_roles = RESEARCHER_ONLY

    def post(self, request, pk):
        study = get_object_or_404(ResearchStudy, pk=pk)
        calculated, skipped = services.calculate_all(study, request.user)
        messages.success(request, f"{calculated} measurement(s) calculated from system records.")
        for reason, n in skipped.items():
            messages.warning(request, f"{n} not calculated: {reason}")
        return redirect("research:measurement_list")


# ---- Outcome definitions -------------------------------------------------------------------------------------------------
class OutcomeList(ActiveStudyMixin, CrudListView):
    allowed_roles = RESEARCHER_ONLY
    model = OutcomeDefinition
    title = "Outcome definitions"
    subtitle = "What each measured outcome means and how it is obtained. Standard definitions are starting points to check against the approved protocol."
    columns = [("Name", "name"), ("Kind", "get_kind_display"), ("Source", "get_source_display"), ("Applies to", "get_applies_to_display"),
               ("Measured", "get_measured_at_display"), ("Active", "is_active")]
    add_url, edit_url = "research:outcome_add", "research:outcome_edit"

    def get_queryset(self):
        return super().get_queryset().filter(study=self.study)


class OutcomeFormMixin:
    allowed_roles = RESEARCHER_ONLY
    form_class = OutcomeDefinitionForm
    model = OutcomeDefinition
    entity = "outcome_definition"
    success_url = reverse_lazy("research:outcome_list")


class OutcomeCreate(OutcomeFormMixin, ActiveStudyMixin, CrudCreateView):
    title = "Add outcome definition"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "study": self.study}

    def form_valid(self, form):
        form.instance.study = self.study
        return super().form_valid(form)


class OutcomeUpdate(OutcomeFormMixin, ActiveStudyMixin, CrudUpdateView):
    title = "Edit outcome definition"

    def get_queryset(self):
        return OutcomeDefinition.objects.filter(study=self.study)


# ---- Participants ------------------------------------------------------------------------------------------------------------
class ParticipantList(ActiveStudyMixin, CrudListView):
    allowed_roles = RESEARCHER_ONLY
    model = Participant
    title = "Participants"
    subtitle = "Research codes only. Names are not shown in lists."
    columns = [("Research code", "research_code"), ("Eligibility", "get_eligibility_display"), ("Consent", "get_consent_status_display"),
               ("Stage", "stage"), ("Group", "get_group_display")]
    search_fields = ("research_code",)
    search_help = "Research code"
    filters = [("group", "group", "Group", Group.choices), ("eligibility", "eligibility", "Eligibility", Eligibility.choices),
               ("consent", "consent_status", "Consent", ConsentStatus.choices)]
    add_url, detail_url = "research:participant_register", "research:participant_detail"
    empty_text = "No participants registered yet. Registering is a deliberate step: nobody is added automatically."

    def get_queryset(self):
        return super().get_queryset().filter(study=self.study)


class ParticipantRegister(ActiveStudyMixin, View):
    def get(self, request):
        return self.render(ParticipantRegisterForm(study=self.study))

    def post(self, request):
        form = ParticipantRegisterForm(request.POST, study=self.study)
        if form.is_valid():
            d = form.cleaned_data
            try:
                p = services.register_participant(self.study, d["student"], request.user, eligibility=d["eligibility"],
                                                  eligibility_notes=d["eligibility_notes"], notes=d["notes"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"Registered as {p.research_code}. Consent and enrolment still need to be recorded.")
                if not p.year_matches_criterion:
                    messages.warning(request, f"This student is in year {p.student.year_of_study}, outside the study's eligible years "
                                              f"({self.study.eligible_year_min}-{self.study.eligible_year_max}). Check eligibility.")
                return redirect("research:participant_detail", pk=p.pk)
        return self.render(form)

    def render(self, form):
        return render(self.request, "crud/form.html", {"form": form, "title": "Register a participant", "submit_label": "Register",
                                                       "cancel_url": reverse("research:participant_list")})


class ParticipantMixin(ActiveStudyMixin):
    def get_participant(self, pk):
        return get_object_or_404(Participant.objects.select_related("student__user", "student__programme", "study"), pk=pk, study=self.study)


class ParticipantDetail(ParticipantMixin, TemplateView):
    template_name = "research/participant_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = self.get_participant(self.kwargs["pk"])
        rows = [{"m": m, "state": services.display_state(m), "label": services.STATE_LABELS[services.display_state(m)]}
                for m in p.measurements.select_related("outcome__study", "participant")]
        ctx.update(participant=p, events=p.events.select_related("by"), allocations=p.allocations.select_related("allocated_by"),
                   measurement_rows=rows, allocate_form=AllocationForm(), withdraw_form=WithdrawForm())
        return ctx


class ParticipantEdit(ParticipantMixin, View):
    def get(self, request, pk):
        p = self.get_participant(pk)
        return self.render(p, ParticipantUpdateForm(instance=p))

    def post(self, request, pk):
        p = self.get_participant(pk)
        if p.is_withdrawn:
            messages.error(request, "A withdrawn participant's record can no longer be edited.")
            return redirect("research:participant_detail", pk=pk)
        form = ParticipantUpdateForm(request.POST, instance=p)
        if form.is_valid():
            changed = set(form.changed_data)
            form.save()
            services.record_participant_update(p, request.user, changed)
            messages.success(request, "Participant record saved." if changed else "No changes to save.")
            return redirect("research:participant_detail", pk=pk)
        return self.render(p, form)

    def render(self, p, form):
        return render(self.request, "crud/form.html", {"form": form, "title": f"Eligibility, consent and enrolment: {p.research_code}",
                                                       "submit_label": "Save", "cancel_url": reverse("research:participant_detail", args=[p.pk])})


class ParticipantAllocate(ParticipantMixin, View):
    def get(self, request, pk):
        return self.render(self.get_participant(pk), AllocationForm())

    def post(self, request, pk):
        p = self.get_participant(pk)
        form = AllocationForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                services.allocate_participant(p, request.user, group=d["group"], method=d["method"], procedure=d["procedure"],
                                              allocation_date=d["allocation_date"], reason=d["reason"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"{p.research_code} allocated and the procedure recorded.")
                return redirect("research:participant_detail", pk=pk)
        return self.render(p, form)

    def render(self, p, form):
        return render(self.request, "crud/form.html", {"form": form, "title": f"Allocate {p.research_code} to a group", "submit_label": "Record allocation",
                                                       "cancel_url": reverse("research:participant_detail", args=[p.pk])})


class ParticipantWithdraw(ParticipantMixin, View):
    def get(self, request, pk):
        return self.render(self.get_participant(pk), WithdrawForm())

    def post(self, request, pk):
        p = self.get_participant(pk)
        form = WithdrawForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                services.withdraw_participant(p, request.user, withdrawn_on=d["withdrawn_on"], data_handling=d["data_handling"], reason=d["reason"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, f"{p.research_code} recorded as withdrawn.")
                return redirect("research:participant_detail", pk=pk)
        return self.render(p, form)

    def render(self, p, form):
        return render(self.request, "crud/form.html", {"form": form, "title": f"Record withdrawal of {p.research_code}", "submit_label": "Record withdrawal",
                                                       "cancel_url": reverse("research:participant_detail", args=[p.pk])})


# ---- Measurements ---------------------------------------------------------------------------------------------------------------
def _outcome_choices(study):
    return lambda: [(str(o.pk), o.name) for o in OutcomeDefinition.objects.filter(study=study)]


class MeasurementList(ActiveStudyMixin, CrudListView):
    allowed_roles = RESEARCHER_ONLY
    model = Measurement
    title = "Measurements"
    subtitle = "Planned, collected, missing and not-applicable measurements. A planned measurement has no value yet."
    select_related = ("participant", "outcome__study")
    columns = [("Participant", "participant.research_code"), ("Group", lambda m: m.participant.get_group_display() or "-"),
               ("Outcome", "outcome.name"), ("Period", "get_period_display"),
               ("State", lambda m: services.STATE_LABELS[services.display_state(m)]),
               ("Value", lambda m: f"{m.value:f}".rstrip("0").rstrip(".") if m.value is not None else "-"), ("Collected on", "collected_on")]
    search_fields = ("participant__research_code",)
    search_help = "Research code"
    detail_url = "research:measurement_edit"
    empty_text = "No measurements planned yet. Use Plan measurements on the study page after enrolling participants."

    @property
    def filters(self):
        return [("period", "period", "Period", Period.choices), ("outcome", "outcome_id", "Outcome", _outcome_choices(self.study)),
                ("status", "status", "Stored status", MeasurementStatus.choices), ("group", "participant__group", "Group", Group.choices)]

    def get_queryset(self):
        return super().get_queryset().filter(participant__study=self.study)


class MeasurementEdit(ActiveStudyMixin, View):
    template_name = "research/measurement_form.html"

    def get_measurement(self, pk):
        return get_object_or_404(Measurement.objects.select_related("participant", "outcome__study"), pk=pk, participant__study=self.study)

    def get(self, request, pk):
        m = self.get_measurement(pk)
        return self.render(m, MeasurementForm(measurement=m, initial=self._initial(m)))

    def post(self, request, pk):
        m = self.get_measurement(pk)
        form = MeasurementForm(request.POST, measurement=m)
        if form.is_valid():
            d = form.cleaned_data
            try:
                changed = services.record_measurement(m, request.user, status=d["status"], value=d["value"], collected_on=d["collected_on"],
                                                      missing_reason=d["missing_reason"], notes=d["notes"], reason=d["reason"])
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(request, "Measurement saved." if changed else "No changes to save.")
                return redirect("research:measurement_list")
        return self.render(m, form)

    @staticmethod
    def _initial(m):
        status = m.status if m.status != MeasurementStatus.PLANNED else MeasurementStatus.COLLECTED
        return {"status": status, "value": m.value, "collected_on": m.collected_on, "missing_reason": m.missing_reason, "notes": m.notes}

    def render(self, m, form):
        return render(self.request, self.template_name, {
            "m": m, "form": form, "state_label": services.STATE_LABELS[services.display_state(m)],
            "revisions": m.revisions.select_related("changed_by"), "can_calculate": m.outcome.source == OutcomeSource.CALCULATED})


class MeasurementCalculate(ActiveStudyMixin, View):
    def post(self, request, pk):
        m = get_object_or_404(Measurement.objects.select_related("participant", "outcome__study"), pk=pk, participant__study=self.study)
        try:
            changed = services.calculate_measurement(m, request.user)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect("research:measurement_edit", pk=pk)
        messages.success(request, "Calculated from system records and saved." if changed else "The calculated value is unchanged.")
        return redirect("research:measurement_list")


class Completeness(ActiveStudyMixin, TemplateView):
    template_name = "research/completeness.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(study=self.study, rows=services.completeness(self.study), state_labels=services.STATE_LABELS)
        return ctx
