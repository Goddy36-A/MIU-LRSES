from django.urls import path

from . import views as v

app_name = "academics"

urlpatterns = [
    path("programmes/", v.ProgrammeList.as_view(), name="programme_list"),
    path("programmes/add/", v.ProgrammeCreate.as_view(), name="programme_add"),
    path("programmes/<int:pk>/edit/", v.ProgrammeUpdate.as_view(), name="programme_edit"),
    path("courses/", v.CourseList.as_view(), name="course_list"),
    path("courses/add/", v.CourseCreate.as_view(), name="course_add"),
    path("courses/<int:pk>/edit/", v.CourseUpdate.as_view(), name="course_edit"),
    path("years/", v.YearList.as_view(), name="year_list"),
    path("years/add/", v.YearCreate.as_view(), name="year_add"),
    path("years/<int:pk>/edit/", v.YearUpdate.as_view(), name="year_edit"),
    path("semesters/", v.SemesterList.as_view(), name="semester_list"),
    path("semesters/add/", v.SemesterCreate.as_view(), name="semester_add"),
    path("semesters/<int:pk>/edit/", v.SemesterUpdate.as_view(), name="semester_edit"),
    path("students/", v.StudentList.as_view(), name="student_list"),
    path("students/add/", v.StudentCreate.as_view(), name="student_add"),
    path("students/<int:pk>/edit/", v.StudentUpdate.as_view(), name="student_edit"),
    path("lecturers/", v.LecturerList.as_view(), name="lecturer_list"),
    path("lecturers/add/", v.LecturerCreate.as_view(), name="lecturer_add"),
    path("lecturers/<int:pk>/edit/", v.LecturerUpdate.as_view(), name="lecturer_edit"),
    path("offerings/", v.OfferingList.as_view(), name="offering_list"),
    path("offerings/add/", v.OfferingCreate.as_view(), name="offering_add"),
    path("offerings/<int:pk>/", v.OfferingDetail.as_view(), name="offering_detail"),
    path("offerings/<int:pk>/edit/", v.OfferingUpdate.as_view(), name="offering_edit"),
    path("offerings/<int:pk>/enrol/", v.BulkEnrolView.as_view(), name="offering_enrol"),
    path("enrolments/", v.EnrolmentList.as_view(), name="enrolment_list"),
    path("enrolments/add/", v.EnrolmentCreate.as_view(), name="enrolment_add"),
    path("enrolments/<int:pk>/edit/", v.EnrolmentUpdate.as_view(), name="enrolment_edit"),
    path("my-courses/", v.MyCoursesView.as_view(), name="my_courses"),
]
