from django.urls import path

from . import views as v

app_name = "research"

urlpatterns = [
    path("studies/", v.StudyList.as_view(), name="study_list"),
    path("studies/add/", v.StudyCreate.as_view(), name="study_add"),
    path("studies/<int:pk>/", v.StudyDetail.as_view(), name="study_detail"),
    path("studies/<int:pk>/edit/", v.StudyUpdate.as_view(), name="study_edit"),
    path("studies/<int:pk>/plan/", v.StudyPlanView.as_view(), name="study_plan"),
    path("studies/<int:pk>/calculate/", v.StudyCalculateView.as_view(), name="study_calculate"),

    path("outcomes/", v.OutcomeList.as_view(), name="outcome_list"),
    path("outcomes/add/", v.OutcomeCreate.as_view(), name="outcome_add"),
    path("outcomes/<int:pk>/edit/", v.OutcomeUpdate.as_view(), name="outcome_edit"),

    path("participants/", v.ParticipantList.as_view(), name="participant_list"),
    path("participants/register/", v.ParticipantRegister.as_view(), name="participant_register"),
    path("participants/<int:pk>/", v.ParticipantDetail.as_view(), name="participant_detail"),
    path("participants/<int:pk>/edit/", v.ParticipantEdit.as_view(), name="participant_edit"),
    path("participants/<int:pk>/allocate/", v.ParticipantAllocate.as_view(), name="participant_allocate"),
    path("participants/<int:pk>/withdraw/", v.ParticipantWithdraw.as_view(), name="participant_withdraw"),

    path("measurements/", v.MeasurementList.as_view(), name="measurement_list"),
    path("measurements/<int:pk>/", v.MeasurementEdit.as_view(), name="measurement_edit"),
    path("measurements/<int:pk>/calculate/", v.MeasurementCalculate.as_view(), name="measurement_calculate"),
    path("completeness/", v.Completeness.as_view(), name="completeness"),
]
