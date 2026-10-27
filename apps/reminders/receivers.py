from django.dispatch import receiver

from apps.timetables.signals import lecture_changed

from . import services


@receiver(lecture_changed, dispatch_uid="reminders.handle_lecture_change")
def on_lecture_changed(sender, session, change, **kwargs):
    # Runs inside the scheduling service's transaction, so reminders can never disagree with the schedule.
    services.handle_lecture_change(session, change)
