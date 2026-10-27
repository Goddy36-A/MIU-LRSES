from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

MAX_INTERVAL_MINUTES = 7 * 24 * 60   # a reminder can be set at most 7 days before a lecture
MAX_ATTEMPTS = 3                      # a failed reminder is retried until it has been attempted this often


def humanize_minutes(minutes):
    """90 -> '90 minutes', 60 -> '1 hour', 1440 -> '24 hours'."""
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


class ReminderConfig(models.Model):
    """Single-row system setting (always primary key 1)."""

    reminders_enabled = models.BooleanField(
        default=True, help_text="When off, process_reminders delivers nothing. Scheduled reminders are kept.")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")

    class Meta:
        verbose_name = "reminder settings"
        verbose_name_plural = "reminder settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def __str__(self):
        return "Reminder settings"


class ReminderInterval(models.Model):
    """How long before a lecture a reminder is due. Defaults: 24 hours, 1 hour, 15 minutes."""

    minutes_before = models.PositiveIntegerField(
        unique=True, validators=[MinValueValidator(1), MaxValueValidator(MAX_INTERVAL_MINUTES)],
        help_text="Minutes before the lecture starts (1 to 10080). 1440 = 24 hours, 60 = 1 hour.")
    label = models.CharField(max_length=60, blank=True, help_text="Optional display name. Leave blank to generate one.")
    is_active = models.BooleanField(default=True, help_text="Inactive intervals create no new reminders and pending ones are cancelled.")

    class Meta:
        ordering = ["-minutes_before"]

    @property
    def display(self):
        return self.label or f"{humanize_minutes(self.minutes_before)} before"

    def __str__(self):
        return self.display


class NotificationKind(models.TextChoices):
    REMINDER = "reminder", "Lecture reminder"
    SCHEDULE_CHANGE = "schedule_change", "Schedule change notice"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"        # scheduled, not yet due or not yet processed
    DELIVERED = "delivered", "Delivered"  # available in the recipient's in-app inbox
    CANCELLED = "cancelled", "Cancelled"  # no longer applicable (lecture cancelled, interval off, ...)
    EXPIRED = "expired", "Expired"        # became due only after the lecture had started
    FAILED = "failed", "Failed"           # a delivery channel raised an error


class Notification(models.Model):
    """An in-app notification. Reminders start as PENDING and are delivered when due; schedule-change
    notices are created already DELIVERED. Recipients only ever see DELIVERED notifications."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    session = models.ForeignKey("timetables.LectureSession", on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=NotificationKind.choices, default=NotificationKind.REMINDER, db_index=True)
    interval = models.ForeignKey(ReminderInterval, null=True, blank=True, on_delete=models.PROTECT, related_name="notifications")
    minutes_before = models.PositiveIntegerField(null=True, blank=True, help_text="Interval length when scheduled (kept for reporting).")
    change = models.ForeignKey("timetables.LectureChange", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    scheduled_for = models.DateTimeField(db_index=True, help_text="When the reminder becomes due.")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=NotificationStatus.choices, default=NotificationStatus.PENDING, db_index=True)
    status_detail = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    superseded = models.BooleanField(default=False, help_text="A delivered reminder for a time that has since been changed by a reschedule.")

    class Meta:
        ordering = ["-scheduled_for", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "session", "interval"], name="unique_reminder_per_recipient_session_interval",
                condition=Q(kind="reminder", superseded=False)),
            models.UniqueConstraint(
                fields=["recipient", "change"], name="unique_change_notice_per_recipient",
                condition=Q(kind="schedule_change")),
        ]
        indexes = [models.Index(fields=["status", "scheduled_for"]),
                   models.Index(fields=["recipient", "status", "read_at"])]

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self, when=None):
        if self.read_at is None:
            self.read_at = when or timezone.now()
            self.save(update_fields=["read_at"])

    def __str__(self):
        return f"{self.get_kind_display()} for {self.recipient} ({self.status})"


class RunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    ERRORS = "errors", "Completed with errors"
    DISABLED = "disabled", "Skipped (reminders disabled)"
    CRASHED = "crashed", "Stopped unexpectedly"


class ReminderRun(models.Model):
    """One execution of the reminder processor (management command or the admin 'process now' button)."""

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    trigger = models.CharField(max_length=10, choices=[("command", "Command"), ("admin", "Administrator")], default="command")
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=RunStatus.choices, default=RunStatus.RUNNING)
    sync_created = models.PositiveIntegerField(default=0)
    sync_updated = models.PositiveIntegerField(default=0)
    sync_cancelled = models.PositiveIntegerField(default=0)
    due_found = models.PositiveIntegerField(default=0)
    delivered = models.PositiveIntegerField(default=0)
    expired = models.PositiveIntegerField(default=0)
    cancelled = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0, help_text="Already handled by another run.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    @property
    def duration(self):
        return (self.finished_at - self.started_at) if self.finished_at else None

    def __str__(self):
        return f"Run {self.started_at:%Y-%m-%d %H:%M} ({self.status})"
