# MIU-LRSES — MIU Lecture Reminder and Student Engagement System

Django web application supporting the study *"Evaluating the Impact of Lecture Reminder Systems on Student
Engagement and Academic Performance: A Case Study of Metropolitan International University, Biharwe Division,
Mbarara City."*

**Status: Phase 1 of 8 (foundation) complete.** Later features (academic management, reminders, attendance,
research, questionnaires, analytics) are not built yet. See `docs/PHASE_STATUS.md`.

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
Phase 1: 32 tests, all passing in the sandbox run.

## Roles (Phase 1)
| Role | Dashboard | Can do now |
|---|---|---|
| System administrator | `/dashboard/admin/` | Create/edit users, assign roles, view audit log, open Django Admin |
| Lecturer | `/dashboard/lecturer/` | Placeholder dashboard only |
| Student | `/dashboard/student/` | Placeholder dashboard only |
| Researcher | `/dashboard/researcher/` | Placeholder dashboard only |

Roles are exclusive and enforced on the server (HTTP 403 for the wrong role). A researcher does not inherit
administrator rights. Only the administrator role (and superusers) can open `/django-admin/`.
`createsuperuser` automatically assigns the administrator role.

## Password reset
Reset emails are printed to the console window running `runserver`; no email is actually sent unless you
configure SMTP via `MIU_LRSES_EMAIL_BACKEND` and Django's `EMAIL_*` settings.

## Security limitations (development configuration)
- Default `SECRET_KEY` and `DEBUG=1` are for local use only. Set `MIU_LRSES_SECRET_KEY` and `MIU_LRSES_DEBUG=0`.
- SQLite and the Django development server are not suitable for public hosting.
- HTTPS, a production web server, backups, rate limiting of login attempts, and a security review are required
  before any public deployment. Failed logins are audited but not yet throttled.
- Password-reset email needs a real mail service to work outside development.
