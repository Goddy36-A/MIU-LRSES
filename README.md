# MIU-LRSES — MIU Lecture Reminder and Student Engagement System

Django web application supporting the study *"Evaluating the Impact of Lecture Reminder Systems on Student
Engagement and Academic Performance: A Case Study of Metropolitan International University, Biharwe Division,
Mbarara City."*

**Status: Phase 2 of 8 (academic management) complete.** Reminders, attendance, assignments, research,
questionnaires and analytics are not built yet. See `docs/PHASE_STATUS.md`.

No institutional ethical approval is claimed by this software. No research data or findings are included.

## Stack
Python, Django 5.2, SQLite3, Django templates, Bootstrap 5.3 and Chart.js 4 (both bundled locally in
`static/vendor/`, so no internet is needed at runtime). Time zone: Africa/Kampala.

## Windows installation
Open Command Prompt in the project folder (the one containing `manage.py`):

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000/ and sign in with the account you created.
`makemigrations` reports "No changes detected" because migrations are already included.

> **Tested status:** these steps were executed on Linux (Python 3.12, Django 5.2.18) in the development
> sandbox, not on Windows. The same commands should work on Windows with Python 3.10+, but that has not yet
> been verified by running them there.

## Running the tests
```
python manage.py test
```
Phase 1 + 2: 102 tests, all passing in the sandbox run (Linux, Python 3.12).

## Roles and what each can do now
| Role | Can do (Phases 1-2) |
|---|---|
| System administrator | Everything below: user accounts, audit log, programmes, courses, academic years, semesters, course offerings, student and lecturer registration, enrolment (single and bulk), venues, all lectures (create, edit details, reschedule, cancel), Django Admin |
| Lecturer | View assigned courses and rosters; view, schedule, reschedule and cancel lectures **only for offerings assigned to them** |
| Student | View own courses and own timetable (upcoming/past, cancelled lectures marked) |
| Researcher | Placeholder dashboard only (research module arrives in Phase 5) |

Roles are exclusive and enforced on the server (403 for the wrong role, 404 for another lecturer's records).
A researcher does not inherit administrator rights. Only administrators and superusers can open `/django-admin/`.

## Academic management (Phase 2)
- **Setup order:** programme -> course; academic year -> semester; register lecturers and students; create a
  *course offering* (course + semester + lecturers); enrol students (offering page has bulk enrolment);
  add venues; schedule lectures.
- **Lecture scheduling rules:** end after start; maximum 8 hours; the lecturer must be assigned to the offering;
  inactive venues/offerings cannot be used for new lectures. A lecture is **blocked** if it overlaps another
  scheduled lecture for the same lecturer, the same venue, the same course offering, or any student enrolled in
  the offering. Back-to-back lectures are allowed. Cancelled lectures never conflict.
- **Reschedule / cancel:** each change is stored in the lecture's history (who, when, old/new time and venue,
  reason) and audited. Cancelled lectures cannot be rescheduled or edited. Phase 3 will use the `lecture_changed`
  signal to update or cancel pending reminders; nothing is sent yet.
- **Time zone:** times are stored timezone-aware and entered/displayed in Africa/Kampala.
- **Assumptions:** a course belongs to one programme; accounts are created by administrators (no self-registration);
  records are deactivated rather than deleted (related records are protected from deletion); students may enrol
  in courses outside their programme (electives).

## Password reset
Reset emails are printed to the console window running `runserver`; no email is actually sent unless you
configure SMTP via `MIU_LRSES_EMAIL_BACKEND` and Django's `EMAIL_*` settings.

## Security limitations (development configuration)
- Default `SECRET_KEY` and `DEBUG=1` are for local use only. Set `MIU_LRSES_SECRET_KEY` and `MIU_LRSES_DEBUG=0`.
- SQLite and the Django development server are not suitable for public hosting.
- HTTPS, a production web server, backups, rate limiting of login attempts, and a security review are required
  before any public deployment. Failed logins are audited but not yet throttled.
- Password-reset email needs a real mail service to work outside development.
