# Administrator guide

Status: covers Phases 1-6. Analytics and CSV exports (Phase 7) are **not built yet**. Detailed rules live in `REMINDERS.md`, `ATTENDANCE_PERFORMANCE.md`, `RESEARCH.md` and `QUESTIONNAIRES.md`.

## Sign in and orientation
Sign in at `/login/`. The sidebar groups **Academic records**, **Timetable** and **Administration**.
The dashboard shows account and academic counts, a chart of accounts by role, and recent audit activity.

## Recommended setup order
1. **Academic years** then **Semesters** (semester dates must fall inside the year; only one year and one semester can be "current").
2. **Programmes**, then **Courses** (each course belongs to one programme).
3. **Lecturers** and **Students** - *Register* creates the sign-in account and the profile together. Give the person their username and password securely; they can change it from the user menu.
4. **Course offerings** - choose a course, a semester and one or more lecturers.
5. Open an offering and use **Enrol students** (bulk), or add single records under **Enrolments**. Set an enrolment to *Withdrawn* instead of deleting it.
6. **Venues**.
7. **Lectures** - schedule lectures. The system refuses a lecture that overlaps another one for the same lecturer, venue, course, or any enrolled student, and says which.

## Changing the timetable
Open a lecture: **Edit details** changes the topic only; **Reschedule** changes time/venue (reason required); **Cancel** needs a reason. Each change is kept in the lecture's change history and in the audit log. Cancelled lectures cannot be edited or rescheduled - schedule a new one.

## Accounts and safety
- **User accounts**: change a person's role or deactivate them. You cannot demote or deactivate yourself.
- **Audit log**: logins, failed logins (username only), account and record changes, lecture changes. It cannot be edited.
- **Database admin** (`/django-admin/`): for corrections the main screens do not offer. Lecture times in the database admin are read-only.
- Deactivate records rather than deleting them; records that other records depend on are protected from deletion.

## Reminders (sidebar: Reminders)
- **Reminder settings**: switch reminders on/off and edit the intervals (defaults 24 hours, 1 hour, 15 minutes). **Process due reminders now** runs the processor immediately.
- **Scheduled reminders** lists every reminder and its status; **Processing runs** shows each run's counts and any error.
- Reminders are delivered **only to the in-app Notifications page** (no email, SMS, WhatsApp or browser push). Nothing is delivered unless `python manage.py process_reminders` is run regularly: schedule it with Windows Task Scheduler as described in `REMINDERS.md`.

## Attendance and performance (sidebar: Attendance and performance)
- **Attendance rules**: late handling and excused-absence policy (documented defaults: late counts as attended; excused absences are excluded from the rate; missing records are never treated as absences).
- **Assignments** and **Assessments**: you can view and manage every course's items; lecturers manage their own. Missing marks are never zero.
- Calculation rules and assumptions: `ATTENDANCE_PERFORMANCE.md`.

## Research (sidebar: Research)
- You can create and edit the **study settings** (planning figures 350 / 156 / 78 / 78 / eight weeks are editable defaults, not evidence of recruitment) and see aggregate counts.
- You **cannot** see participant lists, research codes, group allocations or measurements. That separation is deliberate; see `RESEARCH.md`.

## Analytics and CSV exports **(not built yet - Phase 7)**
