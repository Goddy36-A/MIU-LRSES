# Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: project, custom user, roles, auth, base UI, admin, tests | Done |
| 2 | Academic management: programmes, courses, years, semesters, profiles, offerings, enrolment, venues, lectures, conflict checks | Done |
| 3 | Reminders | Not started |
| 4 | Attendance and performance | Not started |
| 5 | Research study | Not started |
| 6 | Questionnaires | Not started |
| 7 | Analytics and exports | Not started |
| 8 | Final verification and documentation | Not started |

## Phase 1 design decisions / assumptions
- One primary role per user (`User.role`), exclusive; roles are not stacked.
- `is_staff` (Django Admin access) is derived: true only for administrators and superusers.
- Role groups ("System Administrator", "Lecturer", "Student", "Researcher") are created after migrate. Only the
  administrator group has model permissions so far; later phases extend `ROLE_PERMISSIONS` in
  `apps/accounts/signals.py`.
- `AuditLog` is append-only (no add/change/delete in Django Admin). It records logins, logouts, failed login
  usernames (never passwords), and user create/update events.
- An administrator cannot demote or deactivate their own account (lock-out protection).
- Ambiguity: the brief did not say how accounts are created. Default chosen: administrators create accounts;
  there is no public self-registration.

## Phase 2 design decisions
- Apps: `academics` (programmes, courses, years, semesters, profiles, offerings, enrolments), `timetables`
  (venues, lecture sessions, change history, scheduling services), `core` (shared form and list/create/update helpers).
- Student/lecturer registration creates the user account and profile in one transaction.
- Role groups are now kept in sync with `User.role` automatically, and the administrator group receives
  add/change/view permissions on academic and timetable models for Django Admin.
- Lecture times/venue of an existing lecture are read-only in Django Admin so every change goes through
  Reschedule and is recorded.
- A student conflict is reported when a student enrolled in the lecture's offering is already enrolled in another
  offering with an overlapping scheduled lecture. Enrolments added later are not re-checked against old lectures.
