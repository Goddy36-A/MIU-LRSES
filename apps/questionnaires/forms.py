from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import LIKERT_CHOICES, MAX_TEXT_LENGTH, Question, QuestionType, Questionnaire
from .services import ASSIGN_TARGETS


class QuestionnaireForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Questionnaire
        fields = ["title", "instructions", "research_question", "period"]


class QuestionForm(BootstrapFormMixin, forms.ModelForm):
    options_text = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}), label="Options (multiple choice only)",
                                   help_text="One option per line. At least two for a multiple-choice question.")

    class Meta:
        model = Question
        fields = ["order", "text", "qtype", "construct", "required", "reverse_scored"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["options_text"].initial = "\n".join(self.instance.options.values_list("label", flat=True))


class AssignForm(BootstrapFormMixin, forms.Form):
    target = forms.ChoiceField(choices=ASSIGN_TARGETS, label="Assign to")
    due_date = forms.DateField(required=False, label="Due date (optional)")


class ResponseForm(forms.Form):
    """One field per question, named q<id>. Blank answers are allowed here; the service enforces required items on submit."""

    def __init__(self, questions, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.questions = list(questions)
        for q in self.questions:
            name = f"q{q.pk}"
            if q.qtype == QuestionType.LIKERT:
                self.fields[name] = forms.ChoiceField(choices=[(str(v), label) for v, label in LIKERT_CHOICES], widget=forms.RadioSelect, required=False)
            elif q.qtype == QuestionType.CHOICE:
                self.fields[name] = forms.ChoiceField(choices=[(str(o.pk), o.label) for o in q.options.all()], widget=forms.RadioSelect, required=False)
            else:
                self.fields[name] = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "maxlength": MAX_TEXT_LENGTH}),
                                                    required=False, max_length=MAX_TEXT_LENGTH)
            self.fields[name].label = f"{q.order}. {q.text}"

    def raw_answers(self):
        return {q.pk: self.cleaned_data.get(f"q{q.pk}") for q in self.questions}

    def rows(self):
        return [(q, self[f"q{q.pk}"]) for q in self.questions]
