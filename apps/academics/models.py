from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import Role

YEAR_VALIDATORS = [MinValueValidator(1), MaxValueValidator(6)]


class Programme(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    duration_years = models.PositiveSmallIntegerField(default=3, validators=YEAR_VALIDATORS)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Course(models.Model):
    """A course (unit) belongs to one programme. Assumption: shared service
    courses are registered once per programme with the same title."""

    code = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=200)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="courses")
    year_of_study = models.PositiveSmallIntegerField(default=1, validators=YEAR_VALIDATORS)
    credit_units = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(20)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.title}"


class AcademicYear(models.Model):
    name = models.CharField(max_length=20, unique=True, help_text="For example 2026/2027")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False, help_text="Only one academic year can be current.")

    class Meta:
        ordering = ["-start_date"]

    def clean(self):
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "End date must be after the start date."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:
                AcademicYear.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
            super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Semester(models.Model):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="semesters")
    number = models.PositiveSmallIntegerField(choices=[(1, "Semester 1"), (2, "Semester 2")])
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False, help_text="Only one semester can be current.")

    class Meta:
        ordering = ["-start_date"]
        constraints = [models.UniqueConstraint(fields=["academic_year", "number"], name="unique_semester_per_year")]

    def clean(self):
        errors = {}
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                errors["end_date"] = "End date must be after the start date."
            elif self.academic_year_id:
                year = self.academic_year
                if self.start_date < year.start_date or self.end_date > year.end_date:
                    errors["start_date"] = (
                        f"Semester dates must fall within the academic year ({year.start_date} to {year.end_date}).")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_current:
                Semester.objects.exclude(pk=self.pk).filter(is_current=True).update(is_current=False)
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.academic_year.name} Semester {self.number}"


class StudentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    GRADUATED = "graduated", "Graduated"
    WITHDRAWN = "withdrawn", "Withdrawn"


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    registration_number = models.CharField(max_length=30, unique=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="students")
    year_of_study = models.PositiveSmallIntegerField(default=1, validators=YEAR_VALIDATORS)
    status = models.CharField(max_length=12, choices=StudentStatus.choices, default=StudentStatus.ACTIVE)

    class Meta:
        ordering = ["registration_number"]

    def clean(self):
        if self.user_id and self.user.role != Role.STUDENT:
            raise ValidationError("A student profile can only belong to a user with the Student role.")

    def __str__(self):
        return f"{self.registration_number} - {self.user.display_name()}"


class LecturerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lecturer_profile")
    staff_number = models.CharField(max_length=30, unique=True)
    department = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["staff_number"]

    def clean(self):
        if self.user_id and self.user.role != Role.LECTURER:
            raise ValidationError("A lecturer profile can only belong to a user with the Lecturer role.")

    def __str__(self):
        return f"{self.user.display_name()} ({self.staff_number})"


class CourseOffering(models.Model):
    """A course taught in a particular semester, by one or more lecturers."""

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="offerings")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="offerings")
    lecturers = models.ManyToManyField(LecturerProfile, blank=True, related_name="offerings")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-semester__start_date", "course__code"]
        constraints = [models.UniqueConstraint(fields=["course", "semester"], name="unique_offering_per_semester")]

    def __str__(self):
        return f"{self.course.code} ({self.semester})"


class EnrolmentStatus(models.TextChoices):
    ENROLLED = "enrolled", "Enrolled"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Enrolment(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="enrolments")
    offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="enrolments")
    status = models.CharField(max_length=10, choices=EnrolmentStatus.choices, default=EnrolmentStatus.ENROLLED)
    enrolled_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["offering", "student__registration_number"]
        constraints = [models.UniqueConstraint(fields=["student", "offering"], name="unique_student_offering")]

    def __str__(self):
        return f"{self.student.registration_number} in {self.offering}"


def get_student_profile(user):
    return StudentProfile.objects.filter(user=user).first() if user.is_authenticated else None


def get_lecturer_profile(user):
    return LecturerProfile.objects.filter(user=user).first() if user.is_authenticated else None
