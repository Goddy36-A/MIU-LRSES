from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

MAX_LECTURE_HOURS = 8


class Venue(models.Model):
    name = models.CharField(max_length=100, unique=True)
    building = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.building})" if self.building else self.name


class SessionStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    CANCELLED = "cancelled", "Cancelled"


class LectureSession(models.Model):
    """One scheduled lecture. Times are stored timezone-aware (UTC) and shown in Africa/Kampala."""

    offering = models.ForeignKey("academics.CourseOffering", on_delete=models.PROTECT, related_name="sessions")
    lecturer = models.ForeignKey("academics.LecturerProfile", on_delete=models.PROTECT, related_name="sessions")
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="sessions")
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField()
    topic = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED, db_index=True)
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]

    @property
    def is_cancelled(self):
        return self.status == SessionStatus.CANCELLED

    @property
    def local_date(self):
        return timezone.localtime(self.start_at).date()

    def clean(self):
        from .services import find_conflicts  # local import avoids a circular import

        errors = {}
        if self.start_at and self.end_at:
            if self.end_at <= self.start_at:
                errors["end_at"] = "End time must be after the start time."
            elif self.end_at - self.start_at > timedelta(hours=MAX_LECTURE_HOURS):
                errors["end_at"] = f"A lecture cannot be longer than {MAX_LECTURE_HOURS} hours."
        if self._state.adding:  # checks below apply when scheduling; later edits must not be blocked by newer changes
            if self.offering_id:
                if not self.offering.is_active:
                    errors["offering"] = "This course offering is inactive."
                elif self.lecturer_id and not self.offering.lecturers.filter(pk=self.lecturer_id).exists():
                    errors["lecturer"] = "This lecturer is not assigned to the selected course offering."
            if self.venue_id and not self.venue.is_active:
                errors["venue"] = "This venue is inactive."
        if errors:
            raise ValidationError(errors)
        ready = self.offering_id and self.lecturer_id and self.venue_id and self.start_at and self.end_at
        if self._state.adding and ready and self.status == SessionStatus.SCHEDULED:
            conflicts = find_conflicts(offering=self.offering, lecturer=self.lecturer, venue=self.venue,
                                       start=self.start_at, end=self.end_at, exclude_pk=self.pk)
            if conflicts:
                raise ValidationError(conflicts)

    def __str__(self):
        return f"{self.offering.course.code} {timezone.localtime(self.start_at):%d %b %Y %H:%M}"


class ChangeType(models.TextChoices):
    CREATED = "created", "Created"
    RESCHEDULED = "rescheduled", "Rescheduled"
    CANCELLED = "cancelled", "Cancelled"


class LectureChange(models.Model):
    """History of schedule changes. Phase 3 (reminders) reacts to these changes."""

    session = models.ForeignKey(LectureSession, on_delete=models.CASCADE, related_name="changes")
    change_type = models.CharField(max_length=12, choices=ChangeType.choices)
    old_start_at = models.DateTimeField(null=True, blank=True)
    old_end_at = models.DateTimeField(null=True, blank=True)
    new_start_at = models.DateTimeField(null=True, blank=True)
    new_end_at = models.DateTimeField(null=True, blank=True)
    old_venue = models.CharField(max_length=150, blank=True)
    new_venue = models.CharField(max_length=150, blank=True)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.get_change_type_display()} - {self.session}"
