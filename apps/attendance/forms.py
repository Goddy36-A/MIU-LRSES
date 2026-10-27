from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import AttendanceRecord, AttendanceRules, AttendanceStatus

NOT_RECORDED = [("", "Not recorded")]


class AttendanceMarkForm(BootstrapFormMixin, forms.Form):
    """One status field per enrolled student, plus a reason used when correcting existing records."""

    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                             label="Reason for correction",
                             help_text="Required only if you change a status that was already recorded.")

    def __init__(self, *args, session, enrolments, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        existing = {r.student_id: r.status for r in AttendanceRecord.objects.filter(session=session)}
        self.rows = []
        for e in enrolments:
            name = f"status_{e.student_id}"
            self.fields[name] = forms.ChoiceField(required=False, choices=NOT_RECORDED + AttendanceStatus.choices,
                                                  label=f"Status for {e.student.registration_number}",
                                                  initial=existing.get(e.student_id, ""),
                                                  widget=forms.Select(attrs={"class": "form-select form-select-sm"}))
            self.rows.append({"student": e.student, "name": name, "recorded": e.student_id in existing})
        # BootstrapFormMixin ran before the dynamic fields were added; style them now.
        for name in (r["name"] for r in self.rows):
            self.fields[name].widget.attrs["class"] = "form-select form-select-sm"

    def statuses(self):
        return {int(r["name"].split("_")[1]): self.cleaned_data.get(r["name"], "") for r in self.rows}

    def bound_rows(self):
        return [dict(r, field=self[r["name"]]) for r in self.rows]


class AttendanceRulesForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AttendanceRules
        fields = ["late_counts_as_attended", "excused_policy"]
        labels = {"late_counts_as_attended": "A late student counts as attended",
                  "excused_policy": "Excused absences"}
