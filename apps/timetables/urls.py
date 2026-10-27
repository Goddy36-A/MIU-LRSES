from django.urls import path

from . import views as v

app_name = "timetables"

urlpatterns = [
    path("venues/", v.VenueList.as_view(), name="venue_list"),
    path("venues/add/", v.VenueCreate.as_view(), name="venue_add"),
    path("venues/<int:pk>/edit/", v.VenueUpdate.as_view(), name="venue_edit"),
    path("lectures/", v.SessionList.as_view(), name="session_list"),
    path("lectures/add/", v.SessionCreate.as_view(), name="session_add"),
    path("lectures/<int:pk>/", v.SessionDetail.as_view(), name="session_detail"),
    path("lectures/<int:pk>/edit/", v.SessionEdit.as_view(), name="session_edit"),
    path("lectures/<int:pk>/reschedule/", v.SessionReschedule.as_view(), name="session_reschedule"),
    path("lectures/<int:pk>/cancel/", v.SessionCancel.as_view(), name="session_cancel"),
    path("my-timetable/", v.MyTimetableView.as_view(), name="my_timetable"),
]
