from django.urls import path

from . import views as v

app_name = "questionnaires"

urlpatterns = [
    path("", v.QuestionnaireList.as_view(), name="list"),
    path("add/", v.QuestionnaireSave.as_view(), name="add"),
    path("example-tam/", v.ExampleTam.as_view(), name="example_tam"),
    path("<int:pk>/", v.QuestionnaireDetail.as_view(), name="detail"),
    path("<int:pk>/edit/", v.QuestionnaireSave.as_view(), name="edit"),
    path("<int:pk>/do/<str:action>/", v.QuestionnaireAction.as_view(), name="action"),
    path("<int:pk>/questions/add/", v.QuestionSave.as_view(), name="question_add"),
    path("<int:pk>/questions/<int:qid>/edit/", v.QuestionSave.as_view(), name="question_edit"),
    path("<int:pk>/questions/<int:qid>/delete/", v.QuestionDelete.as_view(), name="question_delete"),
    path("<int:pk>/responses/", v.ResponseList.as_view(), name="responses"),
    path("responses/<int:pk>/", v.ResponseDetail.as_view(), name="response_detail"),
    path("<int:pk>/report/", v.Report.as_view(), name="report"),
    path("my/", v.MyQuestionnaires.as_view(), name="my_list"),
    path("my/<int:pk>/", v.FillQuestionnaire.as_view(), name="fill"),
]
