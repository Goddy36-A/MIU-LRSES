from django.contrib import admin

from . import models


@admin.register(models.Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "duration_years", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "programme", "year_of_study", "credit_units", "is_active")
    list_filter = ("programme", "year_of_study", "is_active")
    search_fields = ("code", "title")


@admin.register(models.AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_current")


@admin.register(models.Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("__str__", "start_date", "end_date", "is_current")
    list_filter = ("academic_year",)


@admin.register(models.StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("registration_number", "user", "programme", "year_of_study", "status")
    list_filter = ("programme", "year_of_study", "status")
    search_fields = ("registration_number", "user__username", "user__first_name", "user__last_name")


@admin.register(models.LecturerProfile)
class LecturerProfileAdmin(admin.ModelAdmin):
    list_display = ("staff_number", "user", "department")
    search_fields = ("staff_number", "user__username", "user__first_name", "user__last_name")


@admin.register(models.CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("course", "semester", "is_active")
    list_filter = ("semester", "is_active")
    filter_horizontal = ("lecturers",)


@admin.register(models.Enrolment)
class EnrolmentAdmin(admin.ModelAdmin):
    list_display = ("student", "offering", "status", "enrolled_on")
    list_filter = ("status", "offering__semester")
    search_fields = ("student__registration_number",)
