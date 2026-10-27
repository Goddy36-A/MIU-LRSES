from django.dispatch import Signal

# Sent after a lecture is created, rescheduled or cancelled.
# Receivers get: session, change (a LectureChange). Phase 3 connects the reminder engine here.
lecture_changed = Signal()
