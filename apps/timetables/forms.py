from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import CourseOffering, LecturerProfile
from apps.core.forms import BootstrapFormMixin

from .models import LectureSession, Venue
from .services import reschedule_session, validate_reschedule


class VenueForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Venue
        fields = ["name", "building", "capacity", "is_active"]


class LectureSessionForm(BootstrapFormMixin, forms.ModelForm):
    """Create a lecture (all fields) or edit its details (topic only; times change via Reschedule)."""

    class Meta:
        model = LectureSession
        fields = ["offering", "lecturer", "venue", "start_at", "end_at", "topic"]

    def __init__(self, *args, user, lecturer_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        offerings = CourseOffering.objects.filter(is_active=True).select_related("course", "semester__academic_year")
        self.fields["venue"].queryset = Venue.objects.filter(is_active=True)
        self.fields["lecturer"].queryset = LecturerProfile.objects.select_related("user")
        self.lecturer_profile = lecturer_profile
        if lecturer_profile is not None:
            # Lecturers may only schedule their own assigned offerings, always as themselves.
            offerings = offerings.filter(lecturers=lecturer_profile)
            del self.fields["lecturer"]
            self.instance.lecturer = lecturer_profile
        self.fields["offering"].queryset = offerings
        if self.instance.pk:
            for name in ("offering", "lecturer", "venue", "start_at", "end_at"):
                self.fields.pop(name, None)
            self.fields["topic"].help_text = "To change the time or venue, use Reschedule."


class RescheduleForm(BootstrapFormMixin, forms.Form):
    start_at = forms.DateTimeField(label="New start")
    end_at = forms.DateTimeField(label="New end")
    venue = forms.ModelChoiceField(queryset=Venue.objects.none())
    reason = forms.CharField(widget=forms.Textarea, help_text="Shown in the lecture's change history.")

    def __init__(self, *args, session, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.session, self.user = session, user
        self.fields["venue"].queryset = Venue.objects.filter(is_active=True) | Venue.objects.filter(pk=session.venue_id)
        self.initial.setdefault("start_at", session.start_at)
        self.initial.setdefault("end_at", session.end_at)
        self.initial.setdefault("venue", session.venue_id)

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            try:
                validate_reschedule(self.session, start=cleaned["start_at"], end=cleaned["end_at"], venue=cleaned["venue"])
            except ValidationError as exc:
                raise ValidationError(exc.messages)
        return cleaned

    def save(self):
        d = self.cleaned_data
        return reschedule_session(self.session, self.user, start=d["start_at"], end=d["end_at"], venue=d["venue"], reason=d["reason"])


class CancelForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), label="Reason for cancelling")
