from django.conf import settings
from django.db import models


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    EXCUSED = "excused", "Excused"


class ExcusedPolicy(models.TextChoices):
    EXCLUDE = "exclude", "Exclude from the rate (not in numerator or denominator)"
    ATTENDED = "attended", "Count as attended"
    ABSENT = "absent", "Count as absent"


class AttendanceRules(models.Model):
    """Single-row configuration of how attendance rates are calculated (institution policy).

    Defaults: a late student counts as attended; an excused absence is excluded from the rate.
    A lecture with no attendance record is never counted as an absence (it is reported as 'not recorded')."""

    late_counts_as_attended = models.BooleanField(default=True)
    excused_policy = models.CharField(max_length=10, choices=ExcusedPolicy.choices, default=ExcusedPolicy.EXCLUDE)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "attendance rules"

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def __str__(self):
        return "Attendance calculation rules"


class AttendanceRecord(models.Model):
    """One student's attendance at one lecture. At most one record per student and lecture."""

    session = models.ForeignKey("timetables.LectureSession", on_delete=models.PROTECT, related_name="attendance_records")
    student = models.ForeignKey("academics.StudentProfile", on_delete=models.PROTECT, related_name="attendance_records")
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["session__start_at", "student__registration_number"]
        constraints = [models.UniqueConstraint(fields=["session", "student"], name="unique_attendance_per_student_session")]

    def __str__(self):
        return f"{self.student.registration_number} {self.get_status_display()} at {self.session}"


class AttendanceChange(models.Model):
    """Append-only audit trail: the first recording and every later correction of an attendance record."""

    record = models.ForeignKey(AttendanceRecord, on_delete=models.CASCADE, related_name="changes")
    old_status = models.CharField(max_length=10, blank=True, choices=AttendanceStatus.choices,
                                  help_text="Blank for the first recording.")
    new_status = models.CharField(max_length=10, choices=AttendanceStatus.choices)
    reason = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    @property
    def is_correction(self):
        return bool(self.old_status)

    def __str__(self):
        return f"{self.record}: {self.old_status or 'new'} -> {self.new_status}"
