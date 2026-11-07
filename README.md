# MIU-LRSES — MIU Lecture Reminder and Student Engagement System

Django web application supporting the study *"Evaluating the Impact of Lecture Reminder Systems on Student
Engagement and Academic Performance: A Case Study of Metropolitan International University, Biharwe Division,
Mbarara City."*

**Status: Phases 1-7 complete; Phase 8 (final verification and documentation) in progress.** Phase 7 delivers research analytics and exports. See [`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md).

No institutional ethical approval is claimed by this software. No research data or findings are included.

## Stack
Python, Django 5.2, SQLite3, Django templates, Bootstrap 5.3 and Chart.js 4 (both bundled locally in
`static/vendor/`, so no internet is needed at runtime). Time zone: Africa/Kampala.

## Quick start on Windows (no commands to type)
1. **Install Python once** from https://www.python.org/downloads/ (version 3.10 or newer). In the installer, **tick "Add python.exe to PATH"**, then click Install.
2. **Unzip** the project folder anywhere (for example your Desktop or `C:\MIU-LRSES`).
3. **Double-click `start.bat`.** The first time, it creates a private Python environment, installs the packages (needs internet once),
   prepares the database and asks you to choose an **administrator username and password** (typing the password is hidden).
   Then it starts the system and opens your browser at http://127.0.0.1:8000/.
4. **Next time**, double-click `start.bat` again - it skips setup and starts straight away. Keep the black window open while you use the system;
   press `Ctrl+C` in it (or close it) to stop.

While that window is open it also processes lecture reminders about once a minute, so in-app reminders are delivered without Task Scheduler.
When the window is closed, no reminders are processed (see `docs/REMINDERS.md` to schedule them permanently). Reminders remain in-app only.

| File | What it does |
|---|---|
| `start.bat` | Sets up on first use, then starts the system. The only file most people need. |
| `setup.bat` | Re-runs setup (safe to repeat; finished steps are skipped). |
| `run_tests.bat` | Runs the automated tests. |
| `start.sh` | The same as `start.bat` for macOS/Linux. |

Options for `start.bat` (rarely needed): `--port 8080`, `--no-browser`, `--no-reminders`.
Not working? "Python was not found" -> install Python as in step 1 and tick the PATH box. "Package installation failed" -> check the internet connection and run `start.bat` again.
If the administrator step is cancelled or fails, nothing is marked finished, and `start.bat` asks again next time.

> **Tested status:** `setup_local.py`, `run_server.py` and `start.sh` were tested on Linux (fresh copy: setup with weak/strong passwords, interactive prompts,
> re-run, server start, logins, busy-port fallback, reminder loop, Ctrl+C and SIGTERM shutdown). The `.bat` files are thin wrappers
> that call those Python scripts; they have **not been run on Windows** in this environment. If a `.bat` misbehaves, the manual commands below still work.

## Manual installation (alternative)
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
The Phase 7 status reports **452 tests passing** in the full suite (development sandbox, Linux, Python 3.12, Django 5.2.18). The suite has not yet been run on Windows.

## User guides and verification
The system starts empty: every record (users, programmes, courses, lectures, participants, marks) is entered by authorised users.
Guides: `docs/USER_GUIDE_ADMIN.md`, `docs/USER_GUIDE_LECTURER.md`, `docs/USER_GUIDE_STUDENT.md`, `docs/USER_GUIDE_RESEARCHER.md`,
checklist `docs/VERIFICATION_CHECKLIST.md`. Project-wide tests in `apps/core/tests.py` automatically check that every route
requires sign-in and that every menu link works for every role. Phase 7 reference documentation is in [`docs/ANALYTICS.md`](docs/ANALYTICS.md)
and [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md); analytics/export user guides remain part of Phase 8.

## Roles and access
| Role | Main capabilities |
|---|---|
| System administrator | User accounts and audit log; programmes, courses, academic years, semesters, course offerings, student and lecturer registration, enrolment and institutional setup. Administrators do not have access to individual participant research data. |
| Lecturer | View assigned courses and rosters; manage lectures and attendance; create assignments and assessments; record submissions and marks; view relevant course reports. |
| Student | View own courses and timetable; receive and manage own in-app lecture reminders; view own attendance, deadlines and results; answer own assigned research questionnaires. |
| Researcher | Configure the study and outcomes; manage participants, eligibility, consent, enrolment, group allocation, withdrawal and measurements; manage questionnaires; use the analytics dashboard, statistical analysis, data-quality checks and research exports. |

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
  reason) and audited. Cancelled lectures cannot be rescheduled or edited. Changes update or cancel pending reminders (Phase 3).
- **Time zone:** times are stored timezone-aware and entered/displayed in Africa/Kampala.
- **Assumptions:** a course belongs to one programme; accounts are created by administrators (no self-registration);
  records are deactivated rather than deleted (related records are protected from deletion); students may enrol
  in courses outside their programme (electives).

## Lecture reminders (Phase 3)
Reminders (default 24 hours, 1 hour and 15 minutes before a lecture) are created when lectures are scheduled and
delivered by `python manage.py process_reminders`. **Delivery is to the in-app notification system only** - no
email, SMS, WhatsApp, Telegram or browser push. **Reminders are only delivered while that command runs**, so
schedule it (every 5 minutes) with Windows Task Scheduler. Full details, rules, statuses and the Task Scheduler steps
are in [docs/REMINDERS.md](docs/REMINDERS.md).
```
python manage.py process_reminders
```

## Attendance and performance (Phase 4)
Lecturers record attendance from a lecture's page (corrections need a reason and are kept in a history), create
assignments and assessments from the sidebar, and record submissions, extensions and marks on one page per item.
Students see their own attendance, deadlines and results. Calculation rules (late and excused handling, missing
records, extensions, exemptions, weighting) are defined in [docs/ATTENDANCE_PERFORMANCE.md](docs/ATTENDANCE_PERFORMANCE.md).
Missing attendance is never counted as absence and missing marks are never counted as zero.

## Research study (Phase 5)
Researchers can manage study settings and outcome definitions; register participants; record eligibility and consent;
enrol and allocate participants; document withdrawals and data handling; and record baseline and post-intervention
measurements. The system records researcher-entered group allocations and does not randomise participants. Control-group
reminder exclusion is supported. Study workflows and assumptions are documented in the researcher guide and
[`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md).

## Questionnaires (Phase 6)
Researchers can create and assign questionnaires with TAM constructs and Likert, choice or text questions. Students
can answer their own assigned questionnaires. The system tracks response completeness and provides descriptive
reporting; reverse-scored items are supported. See the researcher and student guides and [`docs/PHASE_STATUS.md`](docs/PHASE_STATUS.md).

## Analytics and exports (Phase 7)
Researcher-only analytics are available under `/analytics/` and through the researcher menu:

- **Dashboard:** enrollment and group counts, baseline/post data completeness, outcome summaries by group and period,
  reminder interaction, questionnaire response rates, TAM summaries and data-quality alerts.
- **Statistical analysis:** descriptive summaries and eligible group/before-after comparisons for outcomes and TAM
  constructs. Reports include tests, confidence intervals and effect sizes where estimable. The study's significance
  level and minimum analysis sample size govern test availability; below the minimum, descriptive results are shown
  without inferential tests.
- **Data-quality checks:** report inconsistencies, duplicates and missing or overdue data; checks never change records.
- **CSV exports:** nine research datasets plus a data-quality report, with row counts and a field-by-field data
  dictionary. Downloads are researcher-only, CSRF-protected, POST-only, audited and sent with no-store headers.
- **Privacy and interpretation safeguards:** analysis/export eligibility follows consent, enrolment and withdrawal
  choices; non-collected values are not treated as zero; exports use research codes, omit direct identifiers and free
  text, preserve stored values, and neutralise spreadsheet formula-like text. Results are associations, not proof of
  causation; multiple-testing correction and ANCOVA are not implemented.

See [`docs/ANALYTICS.md`](docs/ANALYTICS.md) for methods, assumptions and limitations, and
[`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) for the exported fields. To regenerate the Markdown data dictionary:
```
python manage.py export_data_dictionary
```
Phase 8 remains in progress: final verification and analytics/export user guides are still outstanding, and the full suite
has not yet been run on Windows.

## University reference data
Setup loads the Metropolitan International University programmes that can be verified from the university's own
pages, and the research study profile (title and planning figures from the proposal, no dates, ethics status *Not
recorded*). Academic years, semesters, courses, venues, lecturers, students and all collected data are entered by you
from official records. See [docs/INSTITUTION_DATA.md](docs/INSTITUTION_DATA.md). To run it by hand:
```
python manage.py load_institution_data
```

## Password reset
Reset emails are printed to the console window running `runserver`; no email is actually sent unless you
configure SMTP via `MIU_LRSES_EMAIL_BACKEND` and Django's `EMAIL_*` settings.

## Security limitations (development configuration)
- Default `SECRET_KEY` and `DEBUG=1` are for local use only. Set `MIU_LRSES_SECRET_KEY` and `MIU_LRSES_DEBUG=0`.
- SQLite and the Django development server are not suitable for public hosting.
- HTTPS, a production web server, backups, rate limiting of login attempts, and a security review are required
  before any public deployment. Failed logins are audited but not yet throttled.
- Password-reset email needs a real mail service to work outside development.
