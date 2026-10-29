from django.urls import path

from . import views as v

app_name = "analytics"

urlpatterns = [
    path("", v.DashboardView.as_view(), name="dashboard"),
    path("analysis/", v.AnalysisView.as_view(), name="analysis"),
    path("exports/", v.ExportsView.as_view(), name="exports"),
    path("exports/<slug:key>/download/", v.ExportDownloadView.as_view(), name="export_download"),
    path("dictionary/", v.DictionaryView.as_view(), name="dictionary"),
    path("dictionary.csv", v.DictionaryCsvView.as_view(), name="dictionary_csv"),
]
