from django import forms
from django.core.exceptions import ValidationError

from apps.core.forms import BootstrapFormMixin
from apps.core.scope import offerings_for_staff

from .models import (Assessment, AssessmentResult, Assignment, ResultStatus, Submission, SubmissionStatus)

BLANK = [("", "No record")]


class _OfferingScopedForm(BootstrapFormMixin, forms.ModelForm):
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        qs = offerings_for_staff(user).filter(is_active=True)
        if self.instance.pk:
            qs = offerings_for_staff(user).filter(pk=self.instance.offering_id)  # the course cannot be changed later
            self.fields["offering"].disabled = True
        self.fields["offering"].queryset = qs


class AssignmentForm(_OfferingScopedForm):
    class Meta:
        model = Assignment
        fields = ["offering", "title", "instructions", "deadline", "max_marks", "weight_percent", "records_complete"]


class AssessmentForm(_OfferingScopedForm):
    class Meta:
        model = Assessment
        fields = ["offering", "title", "kind", "assessment_date", "max_marks", "weight_percent"]


def _dt_field(label):
    f = forms.DateTimeField(required=False, label=label, input_formats=BootstrapFormMixin.DATETIME_FORMATS,
                            widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control form-control-sm"},
                                                       format="%Y-%m-%dT%H:%M"))
    return f


class SubmissionRecordsForm(BootstrapFormMixin, forms.Form):
    """One row per enrolled student: status, submission time, optional extension and optional marks."""

    records_complete = forms.BooleanField(
        required=False, label="Submission records are complete",
        help_text="Tick when every student's submission has been recorded. Only then is this assignment counted in punctuality rates.")

    def __init__(self, *args, assignment, enrolments, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment = assignment
        existing = {s.student_id: s for s in assignment.submissions.all()}
        self.fields["records_complete"].initial = assignment.records_complete
        self.rows = []
        for e in enrolments:
            sid, sub = e.student_id, existing.get(e.student_id)
            names = {k: f"{k}_{sid}" for k in ("status", "submitted_at", "extension", "marks")}
            self.fields[names["status"]] = forms.ChoiceField(
                required=False, choices=BLANK + SubmissionStatus.choices, initial=sub.status if sub else "",
                label=f"Status for {e.student.registration_number}",
                widget=forms.Select(attrs={"class": "form-select form-select-sm"}))
            self.fields[names["submitted_at"]] = _dt_field(f"Submitted at ({e.student.registration_number})")
            self.fields[names["extension"]] = _dt_field(f"Extension deadline ({e.student.registration_number})")
            self.fields[names["marks"]] = forms.DecimalField(
                required=False, min_value=0, max_digits=6, decimal_places=2, label=f"Marks ({e.student.registration_number})",
                widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}))
            if sub:
                self.fields[names["submitted_at"]].initial = sub.submitted_at
                self.fields[names["extension"]].initial = sub.extended_deadline
                self.fields[names["marks"]].initial = sub.marks
            self.rows.append({"student": e.student, "sid": sid, "names": names})

    def clean(self):
        cleaned = super().clean()
        out = {}
        for r in self.rows:
            n, sid = r["names"], r["sid"]
            status = cleaned.get(n["status"], "")
            submitted_at, ext, marks = cleaned.get(n["submitted_at"]), cleaned.get(n["extension"]), cleaned.get(n["marks"])
            if not status:
                if submitted_at or ext or marks is not None:
                    self.add_error(n["status"], "Choose a status for this student or clear the other fields.")
                continue
            probe = Submission(assignment=self.assignment, student_id=sid, status=status,
                               submitted_at=submitted_at if status == SubmissionStatus.SUBMITTED else None,
                               extended_deadline=ext, marks=marks)
            if status != SubmissionStatus.SUBMITTED and submitted_at:
                self.add_error(n["submitted_at"], "Only a submitted assignment can have a submission time.")
                continue
            try:
                probe.clean()
            except ValidationError as exc:
                target = {"submitted_at": n["submitted_at"], "extended_deadline": n["extension"], "marks": n["marks"]}
                for fld, msgs in exc.message_dict.items():
                    for msg in msgs:
                        self.add_error(target.get(fld), msg)
                continue
            out[sid] = {"status": status, "submitted_at": probe.submitted_at, "extended_deadline": ext, "marks": marks}
        self.records = out
        return cleaned

    def bound_rows(self):
        return [dict(r, status=self[r["names"]["status"]], submitted_at=self[r["names"]["submitted_at"]],
                     extension=self[r["names"]["extension"]], marks=self[r["names"]["marks"]]) for r in self.rows]


class ResultsForm(BootstrapFormMixin, forms.Form):
    """One row per enrolled student: marked (with marks), did not sit, or exempt."""

    def __init__(self, *args, assessment, enrolments, **kwargs):
        super().__init__(*args, **kwargs)
        self.assessment = assessment
        existing = {r.student_id: r for r in assessment.results.all()}
        self.rows = []
        for e in enrolments:
            sid, res = e.student_id, existing.get(e.student_id)
            names = {"status": f"status_{sid}", "marks": f"marks_{sid}"}
            self.fields[names["status"]] = forms.ChoiceField(
                required=False, choices=BLANK + ResultStatus.choices, initial=res.status if res else "",
                label=f"Status for {e.student.registration_number}",
                widget=forms.Select(attrs={"class": "form-select form-select-sm"}))
            self.fields[names["marks"]] = forms.DecimalField(
                required=False, min_value=0, max_digits=6, decimal_places=2, label=f"Marks ({e.student.registration_number})",
                initial=res.marks if res else None,
                widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}))
            self.rows.append({"student": e.student, "sid": sid, "names": names})

    def clean(self):
        cleaned = super().clean()
        out = {}
        for r in self.rows:
            n, sid = r["names"], r["sid"]
            status, marks = cleaned.get(n["status"], ""), cleaned.get(n["marks"])
            if not status:
                if marks is not None:
                    self.add_error(n["status"], "Choose a status for this student or clear the marks.")
                continue
            probe = AssessmentResult(assessment=self.assessment, student_id=sid, status=status, marks=marks)
            try:
                probe.clean()
            except ValidationError as exc:
                for msg in exc.message_dict.get("marks", exc.messages):
                    self.add_error(n["marks"], msg)
                continue
            out[sid] = {"status": status, "marks": marks}
        self.records = out
        return cleaned

    def bound_rows(self):
        return [dict(r, status=self[r["names"]["status"]], marks=self[r["names"]["marks"]]) for r in self.rows]
