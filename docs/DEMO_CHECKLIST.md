# Demonstration checklist (Phases 1-6)

Tick each item when you have actually seen it work. Use **synthetic** data only.

## Preparation
- [ ] `python manage.py migrate` completed; `python manage.py createsuperuser` done.
- [ ] `python manage.py seed_demo_data --password <choose-a-demo-password>` printed "Synthetic demo data ready".
- [ ] `python manage.py runserver` running; http://127.0.0.1:8000/ opens.

## Accounts and roles
- [ ] Sign in as the superuser -> administrator dashboard with counts and chart.
- [ ] Sign in as `demo_lecturer1`, `demo_student01`, `demo_researcher` -> each lands on its own dashboard.
- [ ] As the student, open `/manage/users/` and `/academics/students/` -> "Access denied".
- [ ] A wrong password is refused; the failed attempt appears in the audit log.
- [ ] Change password and "Forgot your password?" work (reset link prints in the server console).

## Academic records (administrator)
- [ ] Create a programme and a course; see validation messages for a duplicate code.
- [ ] Create a semester outside its year's dates -> refused with a clear message.
- [ ] Register a student and a lecturer; check they can sign in.
- [ ] Create an offering, enrol students in bulk, withdraw one via Enrolments.
- [ ] Search, filter and paginate the student list.

## Lectures
- [ ] Schedule a lecture; schedule an overlapping one for the same lecturer/venue/course -> refused with the reason.
- [ ] Back-to-back lectures are accepted.
- [ ] Reschedule a lecture; the change history shows old and new time and your reason.
- [ ] Cancel a lecture; the student's timetable shows it crossed out and "Cancelled".
- [ ] A lecturer cannot open another lecturer's lecture (404).

## Reminders and notifications
- [ ] As administrator open Reminder settings; note the three intervals; schedule a lecture starting in about 2 hours.
- [ ] Run `python manage.py process_reminders`; open Scheduled reminders and Processing runs to see the counts.
- [ ] As an enrolled student open Notifications: the due reminder appears, unread count shown; mark it as read.
- [ ] Reschedule or cancel the lecture: the student gets a schedule-change notice; pending reminders move or are cancelled.
- [ ] State clearly in the demo: reminders are in-app only (no email/SMS/WhatsApp).

## Attendance and performance
- [ ] As lecturer record attendance (present/absent/late/excused) for a lecture; correct one record and show the history.
- [ ] A student with no record shows "not recorded", not absent.
- [ ] Create an assignment, record a late and an on-time submission; create an assessment and enter marks; open the course report.
- [ ] As the student, open My attendance, Assignment deadlines and My results (only own data).

## Research (use synthetic participants only)
- [ ] As researcher: confirm there is an active study; register participants, record eligibility and consent, enrol, allocate (write the procedure), try to allocate without consent -> refused.
- [ ] Control participant gets no reminders after processing; still gets a schedule-change notice.
- [ ] Plan measurements; record one collected and one missing (reason required); open Data completeness.
- [ ] As administrator confirm participant lists are not accessible (403), but Study settings are.

## Questionnaires
- [ ] Create a questionnaire with a Likert item per TAM construct (label examples as examples), assign it, answer it as a student, review completeness as researcher.

## Quality checks
- [ ] `python manage.py test` -> all tests OK.
- [ ] Resize the browser to phone width; the menu collapses behind the "Menu" button.
- [ ] Clean up: `python manage.py seed_demo_data --remove`.

## Not demonstrable yet
Analytics, statistical comparisons and CSV exports with the data dictionary (Phase 7).

Note: `seed_demo_data` creates synthetic Phase 2 records only (users, course offerings, enrolments, lectures). Research participants, attendance and marks must be entered by hand for the demonstration.
