"""Reminder engine: scheduling, rescheduling/cancellation handling and due-reminder processing.

Key rules (documented in docs/REMINDERS.md):
* One reminder per recipient + lecture + interval (database constraint, plus get-or-skip logic).
* Reminders are created when a lecture is scheduled, and re-synchronised by every process_reminders run,
  so new enrolments, edited intervals and lectures that pre-date this phase are all picked up.
* A reminder whose time had already passed when it would be created is not created (a lecture booked
  30 minutes ahead gets no "24 hours before" reminder).
* Reschedule: pending reminders move to the new time; already-delivered ones are kept as history and
  marked superseded, and fresh reminders are scheduled for the new time.
* Cancel: pending reminders are cancelled; delivered ones are kept.
* Reminders are the study's intervention mechanism and pass through recipient filters (Phase 5 registers
  the control-group exclusion). Schedule-change notices are ordinary academic communication and do not.
"""
import logging
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus, StudentProfile, StudentStatus
from apps.timetables.models import ChangeType, LectureSession, SessionStatus

from .channels import get_channels
from .models import (MAX_ATTEMPTS, Notification, NotificationKind, NotificationStatus, ReminderConfig,
                     ReminderInterval, ReminderRun, RunStatus)

logger = logging.getLogger(__name__)

# ---- Recipient eligibility ---------------------------------------------------------------------
# A filter is a function (queryset_of_StudentProfile, session) -> queryset_of_StudentProfile. They apply to
# reminders only. Phase 5 uses this to exclude control-group participants from intervention reminders.
_recipient_filters = []


def register_recipient_filter(func):
    if func not in _recipient_filters:
        _recipient_filters.append(func)
    return func


def unregister_recipient_filter(func):
    if func in _recipient_filters:
        _recipient_filters.remove(func)


def _base_students(session):
    return (StudentProfile.objects
            .filter(enrolments__offering_id=session.offering_id, enrolments__status=EnrolmentStatus.ENROLLED,
                    status=StudentStatus.ACTIVE, user__is_active=True)
            .select_related("user").distinct())


def notice_recipients(session):
    """Students who should be told about a schedule change: everyone currently enrolled."""
    return list(_base_students(session))


def reminder_recipients(session):
    """Students who should receive intervention reminders (enrolled, active, passing all filters)."""
    qs = _base_students(session)
    for func in _recipient_filters:
        qs = func(qs, session)
    return list(qs)


# ---- Message text ----------------------------------------------------------------------------------
def _local(dt):
    return timezone.localtime(dt)


def humanize_remaining(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if minutes < 48 * 60:
        hours, rest = divmod(minutes, 60)
        text = f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{text} {rest} minute{'s' if rest != 1 else ''}" if rest else text
    days = minutes // (24 * 60)
    return f"{days} days"


def _when(session):
    start, end = _local(session.start_at), _local(session.end_at)
    return f"{start:%a %d %b %Y}, {start:%H:%M}-{end:%H:%M}"


def build_reminder_text(session, *, as_of):
    """Title and message for a reminder, with the time remaining measured from ``as_of``."""
    course = session.offering.course
    remaining = humanize_remaining(session.start_at - as_of)
    title = f"Lecture reminder: {course.code} starts in about {remaining}"
    parts = [f"{course.code} - {course.title}", _when(session), f"Venue: {session.venue.name}"]
    if session.venue.building:
        parts[-1] += f" ({session.venue.building})"
    parts.append(f"Lecturer: {session.lecturer.user.display_name()}")
    if session.topic:
        parts.append(f"Topic: {session.topic}")
    return title, "\n".join(parts)


def build_change_text(session, change):
    course = session.offering.course
    if change.change_type == ChangeType.CANCELLED:
        title = f"Lecture cancelled: {course.code}"
        lines = [f"The {course.code} lecture on {_local(change.old_start_at):%a %d %b %Y, %H:%M} has been cancelled."]
    else:
        title = f"Lecture rescheduled: {course.code}"
        lines = [f"The {course.code} lecture has moved.",
                 f"Was: {_local(change.old_start_at):%a %d %b %Y, %H:%M} at {change.old_venue}",
                 f"Now: {_when(session)} at {change.new_venue}"]
    if change.reason:
        lines.append(f"Reason: {change.reason}")
    return title, "\n".join(lines)


# ---- Scheduling ----------------------------------------------------------------------------------------
def _cancel(qs, detail, now):
    return qs.update(status=NotificationStatus.CANCELLED, status_detail=detail, processed_at=now)


def sync_session_reminders(session, *, now=None):
    """Make the stored reminders for one lecture match the current schedule, intervals and recipients.

    Idempotent: running it repeatedly changes nothing once the data is in sync. Returns a Counter with
    keys created, updated, cancelled.
    """
    now = now or timezone.now()
    stats = Counter()
    existing_qs = Notification.objects.filter(session=session, kind=NotificationKind.REMINDER, superseded=False)

    if session.status != SessionStatus.SCHEDULED:
        stats["cancelled"] += _cancel(existing_qs.filter(status=NotificationStatus.PENDING), "Lecture cancelled.", now)
        return stats
    if session.start_at <= now:
        return stats  # already started: nothing new to schedule; leftovers expire when processed

    intervals = list(ReminderInterval.objects.filter(is_active=True))
    recipients = {sp.user_id: sp for sp in reminder_recipients(session)}
    existing = {(n.recipient_id, n.interval_id): n for n in existing_qs}
    wanted = set()
    to_create = []

    for interval in intervals:
        due_at = session.start_at - timedelta(minutes=interval.minutes_before)
        for user_id in recipients:
            key = (user_id, interval.pk)
            wanted.add(key)
            row = existing.get(key)
            if row is None:
                if due_at < now:
                    continue  # that moment has already passed; do not create a reminder for it
                title, message = build_reminder_text(session, as_of=due_at)
                to_create.append(Notification(
                    recipient_id=user_id, session=session, kind=NotificationKind.REMINDER, interval=interval,
                    minutes_before=interval.minutes_before, title=title, message=message, scheduled_for=due_at))
            elif row.status == NotificationStatus.PENDING:
                if row.scheduled_for != due_at or row.minutes_before != interval.minutes_before:
                    if due_at < now and row.scheduled_for != due_at:
                        # the lecture moved so that this reminder's moment is already past
                        Notification.objects.filter(pk=row.pk).update(
                            status=NotificationStatus.CANCELLED, scheduled_for=due_at, processed_at=now,
                            minutes_before=interval.minutes_before,
                            status_detail="Cancelled: the reminder time had already passed for the new schedule.")
                        stats["cancelled"] += 1
                    else:
                        title, message = build_reminder_text(session, as_of=due_at)
                        Notification.objects.filter(pk=row.pk).update(
                            scheduled_for=due_at, minutes_before=interval.minutes_before, title=title, message=message)
                        stats["updated"] += 1
            elif row.status == NotificationStatus.CANCELLED and due_at >= now:
                title, message = build_reminder_text(session, as_of=due_at)  # applicable again: reactivate
                Notification.objects.filter(pk=row.pk).update(
                    status=NotificationStatus.PENDING, status_detail="", scheduled_for=due_at,
                    minutes_before=interval.minutes_before, title=title, message=message, processed_at=None, attempts=0)
                stats["updated"] += 1

    if to_create:
        before = Notification.objects.filter(session=session, kind=NotificationKind.REMINDER).count()
        Notification.objects.bulk_create(to_create, ignore_conflicts=True)  # the unique constraint is the final guard
        stats["created"] += Notification.objects.filter(session=session, kind=NotificationKind.REMINDER).count() - before

    for key, row in existing.items():
        if key not in wanted and row.status == NotificationStatus.PENDING:
            inactive = row.interval_id not in {i.pk for i in intervals}
            detail = "Cancelled: reminder interval is inactive." if inactive else "Cancelled: recipient is no longer eligible."
            Notification.objects.filter(pk=row.pk).update(status=NotificationStatus.CANCELLED, status_detail=detail, processed_at=now)
            stats["cancelled"] += 1
    return stats


def cancel_pending_reminders_for(user, detail, *, now=None):
    """Cancel a user's pending (not yet delivered) reminders, for example when a study rule makes them ineligible.
    Delivered reminders are kept as history. Returns the number cancelled."""
    return _cancel(Notification.objects.filter(recipient=user, kind=NotificationKind.REMINDER,
                                               status=NotificationStatus.PENDING), detail, now or timezone.now())


def sync_upcoming(*, now=None):
    """Synchronise reminders for every scheduled lecture that has not started, and tidy up cancelled ones."""
    now = now or timezone.now()
    total = Counter()
    total["cancelled"] += _cancel(
        Notification.objects.filter(kind=NotificationKind.REMINDER, status=NotificationStatus.PENDING)
        .exclude(session__status=SessionStatus.SCHEDULED), "Lecture cancelled.", now)
    sessions = (LectureSession.objects.filter(status=SessionStatus.SCHEDULED, start_at__gt=now)
                .select_related("offering__course", "venue", "lecturer__user"))
    for session in sessions:
        total.update(sync_session_reminders(session, now=now))
    return total


# ---- Reacting to lecture changes (called from the lecture_changed signal) ----------------------
def _notify_change(session, change, now):
    title, message = build_change_text(session, change)
    rows = [Notification(recipient=sp.user, session=session, kind=NotificationKind.SCHEDULE_CHANGE, change=change,
                         title=title, message=message, scheduled_for=now, status=NotificationStatus.DELIVERED,
                         status_detail="Delivered to in-app notifications.", processed_at=now, delivered_at=now)
            for sp in notice_recipients(session)]
    Notification.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


@transaction.atomic
def handle_lecture_change(session, change, *, now=None):
    now = now or timezone.now()
    if change.change_type == ChangeType.CREATED:
        return sync_session_reminders(session, now=now)
    if change.change_type == ChangeType.RESCHEDULED:
        # Reminders already delivered (or expired/failed) were for the old time: keep them as history but free
        # their slot so fresh reminders can be scheduled for the new time.
        Notification.objects.filter(
            session=session, kind=NotificationKind.REMINDER, superseded=False,
            status__in=[NotificationStatus.DELIVERED, NotificationStatus.EXPIRED, NotificationStatus.FAILED],
        ).update(superseded=True)
        stats = sync_session_reminders(session, now=now)
        _notify_change(session, change, now)
        return stats
    if change.change_type == ChangeType.CANCELLED:
        stats = sync_session_reminders(session, now=now)  # cancels pending reminders
        _notify_change(session, change, now)
        return stats


# ---- Processing due reminders ----------------------------------------------------------------------
def _resolve_skip(notification, now):
    """Return a (status, detail) if this due reminder must not be delivered, else None."""
    session = notification.session
    if session.status != SessionStatus.SCHEDULED:
        return NotificationStatus.CANCELLED, "Lecture cancelled."
    if session.start_at <= now:
        return NotificationStatus.EXPIRED, "Became due only after the lecture had started."
    if notification.interval is not None and not notification.interval.is_active:
        return NotificationStatus.CANCELLED, "Reminder interval is inactive."
    if notification.recipient_id not in {sp.user_id for sp in reminder_recipients(session)}:
        return NotificationStatus.CANCELLED, "Recipient is no longer eligible."
    return None


def _process_one(pk, now, run, channels):
    candidate = (Notification.objects.select_related("session__offering__course", "session__venue", "session__lecturer__user",
                                                     "recipient", "interval")
                 .filter(pk=pk, status__in=[NotificationStatus.PENDING, NotificationStatus.FAILED]).first())
    if candidate is None or (candidate.status == NotificationStatus.FAILED and candidate.attempts >= MAX_ATTEMPTS):
        run.skipped += 1
        return
    # Claim the reminder (compare-and-swap on attempts) so two overlapping runs cannot both handle it.
    claimed = Notification.objects.filter(pk=pk, status=candidate.status, attempts=candidate.attempts).update(
        attempts=F("attempts") + 1)
    if not claimed:
        run.skipped += 1
        return
    n = candidate
    n.attempts += 1
    skip = _resolve_skip(n, now)
    if skip:
        status, detail = skip
        Notification.objects.filter(pk=pk).update(status=status, status_detail=detail, processed_at=now)
        if status == NotificationStatus.EXPIRED:
            run.expired += 1
        else:
            run.cancelled += 1
        return
    n.title, n.message = build_reminder_text(n.session, as_of=now)  # wording reflects the actual time remaining
    try:
        for channel in channels:
            channel.send(n)
    except Exception as exc:  # noqa: BLE001 - one bad delivery must not stop the batch
        logger.exception("Reminder %s failed", pk)
        detail = f"{type(exc).__name__}: {exc}"[:240]
        Notification.objects.filter(pk=pk).update(status=NotificationStatus.FAILED, status_detail=detail, processed_at=now)
        run.failed += 1
        run.notes += f"Notification {pk} failed (attempt {n.attempts}): {detail}\n"
        return
    Notification.objects.filter(pk=pk).update(
        status=NotificationStatus.DELIVERED, status_detail="Delivered to in-app notifications.", processed_at=now,
        delivered_at=now, title=n.title, message=n.message)
    run.delivered += 1


def due_reminders(now):
    """Reminders whose time has come: pending ones, plus failed ones that still have attempts left."""
    return Notification.objects.filter(kind=NotificationKind.REMINDER, scheduled_for__lte=now).filter(
        Q(status=NotificationStatus.PENDING) | Q(status=NotificationStatus.FAILED, attempts__lt=MAX_ATTEMPTS))


def process_due_reminders(*, now=None, trigger="command", user=None, sync=True):
    """Process every due reminder and record the outcome in a ReminderRun. Safe to run repeatedly."""
    now = now or timezone.now()
    run = ReminderRun.objects.create(started_at=now, trigger=trigger, triggered_by=user)
    try:
        if not ReminderConfig.get().reminders_enabled:
            run.status = RunStatus.DISABLED
            run.notes = "Reminders are switched off in the reminder settings; nothing was processed."
        else:
            if sync:
                stats = sync_upcoming(now=now)
                run.sync_created, run.sync_updated, run.sync_cancelled = stats["created"], stats["updated"], stats["cancelled"]
            channels = get_channels()  # a misconfigured channel stops the run loudly instead of failing every reminder
            ids = list(due_reminders(now).order_by("scheduled_for", "id").values_list("pk", flat=True))
            run.due_found = len(ids)
            for pk in ids:
                _process_one(pk, now, run, channels)
            run.status = RunStatus.ERRORS if run.failed else RunStatus.COMPLETED
    except Exception as exc:
        run.status = RunStatus.CRASHED
        run.notes += f"Unexpected error: {type(exc).__name__}: {exc}\n"
        raise
    finally:
        run.finished_at = timezone.now() if run.status != RunStatus.RUNNING else now
        run.save()
    return run


# ---- Read helpers ----------------------------------------------------------------------------------
def inbox_for(user):
    """What a user may see: their own delivered notifications, nothing pending, nothing of anyone else's."""
    return (Notification.objects.filter(recipient=user, status=NotificationStatus.DELIVERED)
            .select_related("session__offering__course", "session__venue").order_by("-delivered_at", "-id"))


def unread_count(user):
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(recipient=user, status=NotificationStatus.DELIVERED, read_at__isnull=True).count()


def session_summary(session):
    """Counts of reminder states for a lecture (administrators and lecturers see these, never the recipients)."""
    rows = Notification.objects.filter(session=session, kind=NotificationKind.REMINDER, superseded=False)
    counts = {row["status"]: row["n"] for row in rows.order_by().values("status").annotate(n=Count("id"))}
    return {label: counts.get(value, 0) for value, label in NotificationStatus.choices}
