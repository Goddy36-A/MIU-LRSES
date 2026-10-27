from django.urls import path

from . import views as v

app_name = "reminders"

urlpatterns = [
    path("notifications/", v.NotificationListView.as_view(), name="notifications"),
    path("notifications/<int:pk>/read/", v.MarkReadView.as_view(), name="mark_read"),
    path("notifications/read-all/", v.MarkAllReadView.as_view(), name="mark_all_read"),
    path("notifications/unread-count/", v.UnreadCountView.as_view(), name="unread_count"),
    path("manage/", v.OverviewView.as_view(), name="overview"),
    path("manage/settings/", v.ConfigUpdate.as_view(), name="config_edit"),
    path("manage/intervals/add/", v.IntervalCreate.as_view(), name="interval_add"),
    path("manage/intervals/<int:pk>/edit/", v.IntervalUpdate.as_view(), name="interval_edit"),
    path("manage/queue/", v.QueueList.as_view(), name="queue"),
    path("manage/runs/", v.RunList.as_view(), name="run_list"),
    path("manage/run-now/", v.RunNowView.as_view(), name="run_now"),
]
