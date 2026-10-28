"""Hooks the study's control-group rule into the reminder engine (see apps/reminders/services.py)."""
from apps.reminders.services import register_recipient_filter

from .services import exclude_control_group_from_reminders

register_recipient_filter(exclude_control_group_from_reminders)
