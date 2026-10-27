from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "MIU-LRSES Administration"
admin.site.site_title = "MIU-LRSES Admin"
admin.site.index_title = "Database administration"

handler403 = "apps.accounts.views.permission_denied_view"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("academics/", include("apps.academics.urls")),
    path("timetables/", include("apps.timetables.urls")),
    path("", include("apps.accounts.urls")),
]
