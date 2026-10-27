from django.urls import path

from . import views as v

app_name = "performance"

urlpatterns = [
    path("assignments/", v.AssignmentList.as_view(), name="assignment_list"),
    path("assignments/add/", v.AssignmentFormView.as_view(), name="assignment_add"),
    path("assignments/<int:pk>/", v.AssignmentDetail.as_view(), name="assignment_detail"),
    path("assignments/<int:pk>/edit/", v.AssignmentFormView.as_view(), name="assignment_edit"),
    path("assignments/<int:pk>/records/", v.AssignmentRecords.as_view(), name="assignment_records"),
    path("assessments/", v.AssessmentList.as_view(), name="assessment_list"),
    path("assessments/add/", v.AssessmentFormView.as_view(), name="assessment_add"),
    path("assessments/<int:pk>/", v.AssessmentDetail.as_view(), name="assessment_detail"),
    path("assessments/<int:pk>/edit/", v.AssessmentFormView.as_view(), name="assessment_edit"),
    path("assessments/<int:pk>/results/", v.AssessmentResults.as_view(), name="assessment_results"),
    path("offerings/<int:pk>/", v.OfferingPerformanceReport.as_view(), name="offering_report"),
    path("my/deadlines/", v.MyDeadlinesView.as_view(), name="my_deadlines"),
    path("my/results/", v.MyResultsView.as_view(), name="my_results"),
]
