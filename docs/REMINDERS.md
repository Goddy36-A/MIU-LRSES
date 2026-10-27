# Lecture reminders (Phase 3)

## What this does, and what it does not
Reminders are **generated and delivered to the application's in-app notification system only**. A student sees
a reminder in the *Notifications* page (and the unread count in the top bar and sidebar) after signing in.

**Not implemented, and therefore not claimed:** browser/push notifications, email, SMS, WhatsApp or Telegram.
The unread badge refreshes about once a minute while a page is open; it is a page refresh, not a push message.
A student who never opens the system will not see a reminder.

## How the engine works
1. **Scheduling.** When a lecture is created, one reminder per *enrolled student x active interval* is stored
   as `Pending`, with `scheduled_for = start - interval`. Defaults: 24 hours, 1 hour, 15 minutes.
2. **Processing.** `python manage.py process_reminders` finds reminders whose time has come and marks them
   `Delivered` (that is what makes them appear in the student's inbox). Pending reminders are invisible to students.
3. **Every run also re-synchronises** all upcoming lectures with current enrolments and intervals. That is how
   students enrolled after the lecture was scheduled, edited intervals, and lectures created before Phase 3
   exist all get correct reminders. Reminders are re-derived from the lecture time, so editing
   `scheduled_for` by hand is undone by the next run (use `--no-sync` to bypass for testing).

### Statuses
| Status | Meaning |
|---|---|
| Pending | Scheduled; not yet due or not yet processed. Hidden from the recipient. |
| Delivered | Available in the recipient's in-app notifications. Can be read/unread. |
| Cancelled | No longer applicable: lecture cancelled, interval switched off, recipient left the course, or the reminder time had already passed after a reschedule. The reason is stored in the detail field. |
| Expired | Only became due after the lecture had started, so it was not delivered. |
| Failed | A delivery channel raised an error. Retried on later runs, up to 3 attempts in total. |

### Rules and defaults (assumptions to confirm)
* **No duplicates.** One reminder per recipient + lecture + interval, enforced by a database constraint as well as in code.
* **No reminders for moments already past.** A lecture booked 30 minutes ahead gets only the 15-minute reminder.
* **Late processing.** If the command did not run for a while, overdue reminders are still delivered while the
  lecture has not started. The text always states the *actual* time remaining ("starts in about 40 minutes").
* **Reschedule.** Pending reminders move to the new time. Reminders already delivered stay as history, labelled
  "Old time: lecture was rescheduled", and fresh reminders are scheduled for the new time. Intervals that have
  already passed for the new time are cancelled; if the lecture is later moved further out they are reactivated.
* **Cancel.** Pending reminders are cancelled; delivered ones stay (labelled "Lecture cancelled").
* **Schedule-change notices.** Reschedules and cancellations also create a *Schedule change* notice for every enrolled
  student, immediately delivered. These are ordinary academic communication, **not** part of the study
  intervention, and are sent regardless of any research group (see below).
* **Who receives reminders:** students with an *Enrolled* enrolment, an *Active* student status and an active account.
  Lecturers and administrators receive no reminders in this phase.
* **Switch-off.** Administrators can turn reminders off (Reminder settings). Nothing is delivered while off;
  pending reminders are kept and delivered (or expired) once switched back on.

### Research hook (used in Phase 5)
`apps/reminders/services.py` provides `register_recipient_filter(func)`. A filter receives the candidate students and
the lecture and returns the students who may receive *intervention reminders*. Phase 5 will register the control-group
exclusion here. Filters never apply to schedule-change notices, so control-group students still hear about cancellations.
Nothing in Phase 3 knows about research groups; no filter is registered yet, so every enrolled student currently receives reminders.

## Running the processor
```
python manage.py process_reminders             # normal run
python manage.py process_reminders --dry-run   # report how many are due; change nothing
python manage.py process_reminders --no-sync   # deliver due reminders without re-synchronising
```
Each normal run is recorded (Administrator > Processing runs): time, who/what started it, counts of due, delivered,
expired, cancelled, failed, and any error text. The command exits with an error code if any delivery failed, so Task
Scheduler shows the failure. Administrators can also press **Process due reminders now** on the Reminder settings page.

Overlapping runs are safe: each reminder is claimed with an atomic compare-and-swap before delivery, so two
simultaneous runs cannot both deliver it. (If a run is killed mid-reminder, that reminder is retried on the next run.)

## Scheduling on Windows (Task Scheduler)
The command only does work when something runs it. **If it is not scheduled, no reminders are delivered.**
Run it at least every 5 minutes (a 15-minute reminder can be up to one interval late).

1. Make sure the virtual environment exists (see README). The helper `scripts\process_reminders.bat` activates it,
   runs the command, and appends output to `logs\reminders.log`.
2. Open **Task Scheduler > Create Task...** (not "Basic Task").
3. **General:** name `MIU-LRSES reminders`; tick *Run whether user is logged on or not*.
4. **Triggers > New:** *Daily*, then tick *Repeat task every* **5 minutes** *for a duration of* **Indefinitely**.
5. **Actions > New:** *Start a program*. Program/script: the full path to `scripts\process_reminders.bat`.
   *Start in:* the project folder.
6. Save, enter your Windows password if asked, then right-click the task > **Run** and check `logs\reminders.log`.

Command-line equivalent (adjust the path; run in an elevated Command Prompt):
```
schtasks /Create /SC MINUTE /MO 5 /TN "MIU-LRSES reminders" /TR "C:\path\to\MIU-LRSES\scripts\process_reminders.bat"
```
**Verification status:** the command and its behaviour were tested on Linux. The Task Scheduler steps and the
`.bat` file were **not** run on Windows in this development environment; please verify them on your computer
using step 6, and report any path or virtual-environment problem.

## Adding a delivery channel later
`apps/reminders/channels.py` defines `DeliveryChannel`. Subclass it, implement `send(notification)` (raise on failure),
call `register_channel`, and add its name to `REMINDER_CHANNELS` in settings. A reminder is Delivered only if every
configured channel succeeds. Only `in_app` exists today, and an unknown channel name stops the run with an error.
A future external channel should record per-channel delivery so a retry does not re-send to a channel that already succeeded.

## Reminder interaction data (for the research phases)
Each notification stores `delivered_at` and `read_at`, so "was it read, and how long after delivery" can be derived
later (Phase 7 exports). Reading is the only interaction recorded; the system cannot know whether a student acted on a reminder.
