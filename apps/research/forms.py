from django import forms
from django.utils import timezone

from apps.academics.models import StudentProfile, StudentStatus
from apps.core.forms import BootstrapFormMixin

from .models import (AllocationMethod, ConsentStatus, Eligibility, Group, MeasurementStatus, OutcomeDefinition, Participant,
                     ResearchStudy, WithdrawalDataHandling)


class ResearchStudyForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ResearchStudy
        fields = ["title", "description", "status", "is_active", "ethics_status", "ethics_reference",
                  "population_size", "target_sample_size", "target_intervention", "target_control", "intervention_weeks",
                  "eligible_year_min", "eligible_year_max", "baseline_start", "baseline_end", "intervention_start",
                  "intervention_end", "significance_level", "min_analysis_n", "protocol_notes", "analysis_plan_notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Added in Phase 7: leaving it blank keeps the current value (or the default for a new study).
        self.fields["min_analysis_n"].required = False

    def clean_min_analysis_n(self):
        value = self.cleaned_data.get("min_analysis_n")
        if value is None:
            value = self.instance.min_analysis_n if self.instance.pk else ResearchStudy._meta.get_field("min_analysis_n").default
        return value


class OutcomeDefinitionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = OutcomeDefinition
        fields = ["name", "code", "kind", "source", "definition", "unit", "min_value", "max_value", "applies_to", "measured_at", "is_active"]

    def __init__(self, *args, study=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.study = study or self.instance.study

    def clean_code(self):
        code = self.cleaned_data["code"]
        clash = OutcomeDefinition.objects.filter(study=self.study, code=code).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("This study already has an outcome with that code.")
        return code


def _student_label(student):
    return f"{student.registration_number} - {student.user.display_name()} ({student.programme.code}, year {student.year_of_study})"


class ParticipantRegisterForm(BootstrapFormMixin, forms.Form):
    student = forms.ModelChoiceField(queryset=StudentProfile.objects.none(), label="Student",
                                     help_text="Registering a student is not enrolment and does not record consent.")
    eligibility = forms.ChoiceField(choices=Eligibility.choices, initial=Eligibility.PENDING)
    eligibility_notes = forms.CharField(required=False, widget=forms.Textarea, label="Eligibility notes")
    notes = forms.CharField(required=False, widget=forms.Textarea, label="Research notes",
                            help_text="Do not enter names, registration numbers or contact details.")

    def __init__(self, *args, study, **kwargs):
        super().__init__(*args, **kwargs)
        taken = Participant.objects.filter(study=study).values("student_id")
        qs = (StudentProfile.objects.filter(status=StudentStatus.ACTIVE, user__is_active=True).exclude(pk__in=taken)
              .select_related("user", "programme").order_by("registration_number"))
        self.fields["student"].queryset = qs
        self.fields["student"].label_from_instance = _student_label


class ParticipantUpdateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Participant
        fields = ["eligibility", "eligibility_notes", "consent_status", "consent_date", "consent_reference", "enrolled_on", "notes"]

    def clean(self):
        cleaned = super().clean()
        p = self.instance
        if p.group and (cleaned.get("eligibility") != Eligibility.ELIGIBLE or cleaned.get("consent_status") != ConsentStatus.GIVEN
                        or not cleaned.get("enrolled_on")):
            raise forms.ValidationError("This participant has already been allocated to a group. To stop their participation, "
                                        "use Withdraw instead of changing eligibility, consent or enrolment.")
        return cleaned


class AllocationForm(BootstrapFormMixin, forms.Form):
    group = forms.ChoiceField(choices=Group.choices)
    method = forms.ChoiceField(choices=AllocationMethod.choices, label="How was the group decided?")
    procedure = forms.CharField(widget=forms.Textarea, label="Procedure used",
                                help_text="Describe exactly how this participant was allocated (protocol step, list or random-number "
                                          "procedure used, who carried it out). The system does not randomise for you.")
    allocation_date = forms.DateField(initial=timezone.localdate)
    reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason for changing group",
                             help_text="Required only when moving a participant who is already allocated.")


class WithdrawForm(BootstrapFormMixin, forms.Form):
    withdrawn_on = forms.DateField(initial=timezone.localdate, label="Date of withdrawal")
    data_handling = forms.ChoiceField(choices=WithdrawalDataHandling.choices, label="Data collected so far")
    reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason (optional)",
                             help_text="Participants do not have to give a reason. Do not enter names or contact details.")


class MeasurementForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(choices=[c for c in MeasurementStatus.choices if c[0] != MeasurementStatus.PLANNED])
    value = forms.DecimalField(required=False, max_digits=10, decimal_places=2)
    collected_on = forms.DateField(required=False, label="Date collected")
    missing_reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason missing / not applicable")
    notes = forms.CharField(required=False, widget=forms.Textarea, help_text="Do not enter names or contact details.")
    reason = forms.CharField(required=False, widget=forms.Textarea, label="Reason for correction",
                             help_text="Required when changing a value that was already collected. The original value stays in the history.")

    def __init__(self, *args, measurement, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurement = measurement
        outcome = measurement.outcome
        self.fields["value"].help_text = f"Allowed range: {outcome.min_value:f} to {outcome.max_value:f} ({outcome.unit})."
