"""Business logic for lecture scheduling: conflict detection, creation, rescheduling, cancelling."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Enrolment, EnrolmentStatus, StudentProfile
from apps.accounts.audit import log_action

from .models import MAX_LECTURE_HOURS, ChangeType, LectureChange, LectureSession, SessionStatus
from .signals import lecture_changed


def _fmt(dt):
    return timezone.localtime(dt).strftime("%d %b %Y %H:%M")


def find_conflicts(*, offering, lecturer, venue, start, end, exclude_pk=None):
    """Return human-readable conflict messages for a proposed time slot.

    Two slots overlap when start < other_end and end > other_start, so back-to-back
    lectures (one ends exactly when the next starts) are allowed. Cancelled lectures are ignored.
    Checks: same lecturer, same venue, same course offering, and any student enrolled in
    this offering who is already scheduled for another overlapping lecture.
    """
    overlapping = LectureSession.objects.filter(
        status=SessionStatus.SCHEDULED, start_at__lt=end, end_at__gt=start
    ).select_related("offering__course", "venue", "lecturer__user")
    if exclude_pk:
        overlapping = overlapping.exclude(pk=exclude_pk)

    messages = []
    for s in overlapping.filter(lecturer=lecturer):
        messages.append(f"Lecturer conflict: {lecturer.user.display_name()} is already teaching "
                        f"{s.offering.course.code} from {_fmt(s.start_at)} to {_fmt(s.end_at)}.")
    for s in overlapping.filter(venue=venue):
        messages.append(f"Venue conflict: {venue.name} is already booked for {s.offering.course.code} "
                        f"from {_fmt(s.start_at)} to {_fmt(s.end_at)}.")
    for s in overlapping.filter(offering=offering):
        messages.append(f"Timetable conflict: this course already has a lecture from "
                        f"{_fmt(s.start_at)} to {_fmt(s.end_at)}.")

    student_ids = list(Enrolment.objects.filter(offering=offering, status=EnrolmentStatus.ENROLLED)
                       .values_list("student_id", flat=True))
    if student_ids:
        for s in overlapping.exclude(offering=offering):
            shared = Enrolment.objects.filter(offering=s.offering_id, status=EnrolmentStatus.ENROLLED,
                                              student_id__in=student_ids).count()
            if shared:
                messages.append(f"Student conflict: {shared} enrolled student(s) also attend "
                                f"{s.offering.course.code} from {_fmt(s.start_at)} to {_fmt(s.end_at)}.")
    return messages


@transaction.atomic
def create_session(session, user):
    """Save a validated new session, record its history and notify listeners."""
    session.created_by = user
    session.save()
    change = LectureChange.objects.create(
        session=session, change_type=ChangeType.CREATED, new_start_at=session.start_at, new_end_at=session.end_at,
        new_venue=session.venue.name, changed_by=user)
    log_action("lecture_created", actor=user, target=str(session))
    lecture_changed.send(sender=LectureSession, session=session, change=change)
    return session


def validate_reschedule(session, *, start, end, venue):
    """Raise ValidationError if moving this lecture to the proposed slot is not allowed."""
    if session.status == SessionStatus.CANCELLED:
        raise ValidationError("A cancelled lecture cannot be rescheduled. Create a new lecture instead.")
    if end <= start:
        raise ValidationError("End time must be after the start time.")
    if (end - start).total_seconds() > MAX_LECTURE_HOURS * 3600:
        raise ValidationError(f"A lecture cannot be longer than {MAX_LECTURE_HOURS} hours.")
    if not venue.is_active and venue.pk != session.venue_id:
        raise ValidationError("This venue is inactive.")
    if (start, end, venue.pk) == (session.start_at, session.end_at, session.venue_id):
        raise ValidationError("Nothing changed: choose a different time or venue.")
    conflicts = find_conflicts(offering=session.offering, lecturer=session.lecturer, venue=venue,
                               start=start, end=end, exclude_pk=session.pk)
    if conflicts:
        raise ValidationError(conflicts)


@transaction.atomic
def reschedule_session(session, user, *, start, end, venue, reason):
    validate_reschedule(session, start=start, end=end, venue=venue)
    change = LectureChange(session=session, change_type=ChangeType.RESCHEDULED,
                           old_start_at=session.start_at, old_end_at=session.end_at, old_venue=session.venue.name,
                           new_start_at=start, new_end_at=end, new_venue=venue.name, reason=reason, changed_by=user)
    session.start_at, session.end_at, session.venue = start, end, venue
    session.save()
    change.save()
    log_action("lecture_rescheduled", actor=user, target=str(session), details=reason)
    lecture_changed.send(sender=LectureSession, session=session, change=change)
    return session


@transaction.atomic
def cancel_session(session, user, *, reason):
    if session.status == SessionStatus.CANCELLED:
        raise ValidationError("This lecture is already cancelled.")
    change = LectureChange(session=session, change_type=ChangeType.CANCELLED, old_start_at=session.start_at,
                           old_end_at=session.end_at, old_venue=session.venue.name, reason=reason, changed_by=user)
    session.status = SessionStatus.CANCELLED
    session.cancellation_reason = reason
    session.save()
    change.save()
    log_action("lecture_cancelled", actor=user, target=str(session), details=reason)
    lecture_changed.send(sender=LectureSession, session=session, change=change)
    return session


def sessions_for_student(user):
    """Lectures of offerings in which this student is currently enrolled (never anyone else's)."""
    profile = StudentProfile.objects.filter(user=user).first()
    if profile is None:
        return LectureSession.objects.none()
    return (LectureSession.objects
            .filter(offering__enrolments__student=profile, offering__enrolments__status=EnrolmentStatus.ENROLLED)
            .select_related("offering__course", "venue", "lecturer__user").distinct())


def sessions_for_lecturer(profile):
    if profile is None:
        return LectureSession.objects.none()
    return (LectureSession.objects.filter(offering__lecturers=profile)
            .select_related("offering__course", "offering__semester", "venue", "lecturer__user").distinct())
