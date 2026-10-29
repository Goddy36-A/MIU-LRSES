# Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: project, custom user, roles, auth, base UI, admin, tests | Done |
| 2 | Academic management: programmes, courses, years, semesters, profiles, offerings, enrolment, venues, lectures, conflict checks | Done |
| 3 | Reminders: intervals, scheduling, in-app notifications, `process_reminders`, reschedule/cancel handling | Done (Windows Task Scheduler steps unverified) |
| 4 | Attendance and performance: attendance with audit trail, assignments, submissions, assessments, marks, reports | Done |
| 5 | Research study: participants, consent, allocation records, baseline/post measurements, control-group reminder exclusion | Done |
| 6 | Questionnaires: TAM constructs, Likert/choice/text items, assignment, student answering, completeness and descriptive reports | Done |
| 7 | Analytics and exports | Not started |
| 8 | Final verification and documentation | In progress: route/menu checks, user guides and verification checklist done for Phases 1-6; analytics/export docs wait for Phase 7 |

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

## Phase 3 design decisions
- App `reminders`. Hooks into Phase 2 via the existing `lecture_changed` signal; the scheduling services are unchanged.
- Reminders (the study intervention) and schedule-change notices (normal academic communication) are separate
  notification kinds. Only reminders pass through recipient filters, which is where Phase 5 will exclude the control group.
- Default intervals 24h / 1h / 15m are data (seeded by a migration) and editable by administrators; they are never hard-coded in logic.
- Reminders are materialised in the database when a lecture is scheduled and re-synchronised on every processor run.
  Moments already in the past are not scheduled. Reminders that fall due after a lecture starts expire.
- Ambiguities resolved with defaults (please confirm): only students receive reminders; late-processed reminders are
  still delivered while the lecture has not started; "Delivered" means available in the in-app inbox.
- Enrolment changes are applied by the next processor run, not instantly.
- Known limitation: the sync step loads every upcoming lecture on each run. This is fine for a single-campus pilot;
  it should be optimised if the data volume grows substantially.

## Phase 4 design decisions
- Apps: `attendance` (rules, records, change history) and `performance` (assignments, submissions, assessments, results). Calculation
  logic lives in each app's `services.py`; views only call services. Ownership rules are shared in `apps/core/scope.py`.
- Exact calculation rules, missing-data handling and assumptions are in [ATTENDANCE_PERFORMANCE.md](ATTENDANCE_PERFORMANCE.md).
- Missing attendance is never an absence; missing marks are never zero; assignments count toward punctuality only once their records are marked complete.
- Attendance rules (late handling, excused policy) are administrator-configurable data, with documented defaults.
- Researchers have no access to attendance or marks yet; research-specific access arrives with consent rules in Phase 5.
- Ambiguities resolved with defaults (please confirm): late counts as attended; excused absences are excluded from the rate;
  attendance can be recorded once a lecture has started; there are no letter grades.

## Phase 5 design decisions
- App `research`; full description in [RESEARCH.md](RESEARCH.md). Small hooks added elsewhere: windowed item selection in `performance/services.py`,
  `cancel_pending_reminders_for` in `reminders/services.py`, administrator permissions limited to the study model in `accounts/signals.py`.
- The test run uses a lower-iteration PBKDF2 hasher (`miu_lrses/test_hashers.py`, only when `test` is in the command) so the suite runs in seconds.
- Ambiguities resolved with defaults (please confirm): see "Assumptions to confirm" in RESEARCH.md.

## Phase 6 design decisions
- App `questionnaires`; full description in [QUESTIONNAIRES.md](QUESTIONNAIRES.md). Depends on `research` (study, participants).
- Items are locked once a questionnaire is opened (duplicate to correct); submitted responses are locked.
- Ambiguities resolved with defaults (please confirm): see "Assumptions to confirm" in QUESTIONNAIRES.md.

## Phase 8 - one-click local setup
- `start.bat` / `setup.bat` / `run_tests.bat` (Windows) and `start.sh` (macOS/Linux) wrap `setup_local.py` (venv, packages, migrations, administrator account with password validation) and `run_server.py` (migrations, free-port check, browser, background reminder processing every 60 s while the window is open).
- Tested on Linux only; the `.bat` wrappers are untested on Windows. The background reminder loop is a localhost convenience, not a replacement for Task Scheduler.

## Content policy (supervisor requirement)
- The system ships with no pre-loaded records and no pre-written questionnaire content, and no command creates any. All records are entered by authorised users.
- Removed the built-in starter questionnaire feature (service, view, URL and its database flag) and its tests. Migration `questionnaires/0002_remove_starter_content_flag`
  also deletes any never-used starter drafts left in an existing database; a researcher's own questionnaires are never touched.
- Automated tests build their own temporary records in a throw-away test database; nothing from them reaches the real database.
- Configuration that is kept on purpose: the three default reminder intervals (24 h, 1 h, 15 min), the four standard outcome definitions created with a new study
  (editable), and the research proposal's planning figures as editable study defaults.
