from django import forms
from django.contrib.auth import password_validation
from django.db import transaction

from apps.accounts.models import Role, User
from apps.core.forms import BootstrapFormMixin

from .models import (AcademicYear, Course, CourseOffering, Enrolment, EnrolmentStatus, LecturerProfile, Programme,
                     Semester, StudentProfile, StudentStatus)


class ProgrammeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Programme
        fields = ["code", "name", "duration_years", "is_active"]


class CourseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ["code", "title", "programme", "year_of_study", "credit_units", "is_active"]


class AcademicYearForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "start_date", "end_date", "is_current"]


class SemesterForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Semester
        fields = ["academic_year", "number", "start_date", "end_date", "is_current"]


class CourseOfferingForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CourseOffering
        fields = ["course", "semester", "lecturers", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lecturers"].queryset = LecturerProfile.objects.select_related("user").filter(user__is_active=True)
        self.fields["lecturers"].widget.attrs["size"] = 6
        self.fields["lecturers"].help_text = "Hold Ctrl (or Cmd) to select several lecturers."


class EnrolmentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Enrolment
        fields = ["student", "offering", "status", "enrolled_on"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = StudentProfile.objects.select_related("user")
        self.fields["offering"].queryset = CourseOffering.objects.select_related("course", "semester__academic_year")


class BulkEnrolForm(BootstrapFormMixin, forms.Form):
    students = forms.ModelMultipleChoiceField(queryset=StudentProfile.objects.none(), label="Students to enrol")

    def __init__(self, *args, offering, **kwargs):
        super().__init__(*args, **kwargs)
        self.offering = offering
        already = Enrolment.objects.filter(offering=offering, status=EnrolmentStatus.ENROLLED).values("student")
        self.fields["students"].queryset = (
            StudentProfile.objects.filter(status=StudentStatus.ACTIVE).exclude(pk__in=already).select_related("user"))
        self.fields["students"].widget.attrs["size"] = 8
        self.fields["students"].help_text = "Only active students not already enrolled are listed. Ctrl/Cmd-click to select several."

    def save(self):
        count = 0
        with transaction.atomic():
            for student in self.cleaned_data["students"]:
                enrolment, created = Enrolment.objects.get_or_create(student=student, offering=self.offering)
                if not created and enrolment.status != EnrolmentStatus.ENROLLED:
                    enrolment.status = EnrolmentStatus.ENROLLED
                    enrolment.save(update_fields=["status"])
                    created = True
                count += int(created)
        return count


class _AccountFieldsMixin:
    """Shared user-account fields for registering a student or lecturer together with their profile."""

    account_role = None

    def _setup_account_fields(self):
        base = "form-control"
        self.fields["first_name"] = forms.CharField(max_length=150)
        self.fields["last_name"] = forms.CharField(max_length=150)
        self.fields["email"] = forms.EmailField()
        if self.instance.pk:
            user = self.instance.user
            for name in ("first_name", "last_name", "email"):
                self.fields[name].initial = getattr(user, name)
        else:
            self.fields["username"] = forms.CharField(max_length=150)
            self.fields["password1"] = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
            self.fields["password2"] = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
        for name in ("first_name", "last_name", "email", "username", "password1", "password2"):
            if name in self.fields:
                self.fields[name].widget.attrs["class"] = base
        account = ["username", "first_name", "last_name", "email", "password1", "password2"]
        profile = [f for f in self.Meta.fields]
        self.order_fields([f for f in account if f in self.fields] + profile)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Another account already uses this email address.")
        return email

    def _validate_passwords(self, cleaned):
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            candidate = User(username=cleaned.get("username", ""), email=cleaned.get("email", ""),
                             first_name=cleaned.get("first_name", ""), last_name=cleaned.get("last_name", ""))
            try:
                password_validation.validate_password(p1, candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            self._validate_passwords(cleaned)
        return cleaned

    def save(self, commit=True):
        with transaction.atomic():
            profile = super().save(commit=False)
            cd = self.cleaned_data
            if profile.pk:
                user = profile.user
            else:
                user = User(username=cd["username"], role=self.account_role)
                user.set_password(cd["password1"])
            user.first_name, user.last_name, user.email = cd["first_name"], cd["last_name"], cd["email"]
            user.save()
            profile.user = user
            profile.save()
        return profile


class StudentRegistrationForm(_AccountFieldsMixin, BootstrapFormMixin, forms.ModelForm):
    account_role = Role.STUDENT

    class Meta:
        model = StudentProfile
        fields = ["registration_number", "programme", "year_of_study", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_account_fields()


class LecturerRegistrationForm(_AccountFieldsMixin, BootstrapFormMixin, forms.ModelForm):
    account_role = Role.LECTURER

    class Meta:
        model = LecturerProfile
        fields = ["staff_number", "department"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_account_fields()
