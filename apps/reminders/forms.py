from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import ReminderConfig, ReminderInterval


class ReminderIntervalForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReminderInterval
        fields = ["minutes_before", "label", "is_active"]


class ReminderConfigForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReminderConfig
        fields = ["reminders_enabled"]
