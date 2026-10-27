from django.urls import path

from . import views as v

app_name = "attendance"

urlpatterns = [
    path("lectures/<int:pk>/", v.MarkAttendanceView.as_view(), name="mark"),
    path("my/", v.MyAttendanceView.as_view(), name="my_attendance"),
    path("students/<int:pk>/", v.StudentAttendanceReport.as_view(), name="student_report"),
    path("offerings/<int:pk>/", v.OfferingAttendanceReport.as_view(), name="offering_report"),
    path("rules/", v.AttendanceRulesView.as_view(), name="rules"),
]
