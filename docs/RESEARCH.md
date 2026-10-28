# Research module (Phase 5)

Planning figures (population 350, sample 156, 78 / 78, eight weeks) are **editable defaults** of the study settings.
They are not evidence of recruitment. No ethical approval is claimed: the study records an ethics status
(default "Not recorded") only as a person enters it. No data or findings are pre-loaded.

## Who sees what
| Role | Research access |
|---|---|
| Researcher | Everything below: study settings, outcomes, participants, consent, allocation, measurements, completeness. |
| System administrator | Study **settings** (create/edit, aggregate counts) only. No participant lists, codes, allocations or measurements, in the app or in Django Admin. |
| Lecturer, student | None (403). |
Superusers can read participant tables read-only in Django Admin; keep superuser accounts few. The student link is hidden there.

## Lifecycle (every step is an explicit researcher action)
1. **Register** a student: creates a participant with a random anonymous research code (`P-XXXXXX`). Not enrolment, no consent.
2. **Eligibility** (pending / eligible / not eligible) and **consent** (not asked / given + date / declined). The system flags,
   but does not decide, when a student is outside the configured eligible years.
3. **Enrol**: needs eligible + consent given; enrolment date not before consent date or in the future.
4. **Allocate** to intervention or control. The system **never randomises**. The researcher chooses the group, selects the method
   (assigned per protocol / randomised outside the system / other) and must write the procedure used. Re-allocation needs a reason,
   is flagged, keeps the earlier row, and is blocked once post-intervention data exist.
5. **Withdraw**: date, optional reason, and whether data collected so far are kept or excluded. History is kept.
Registration, consent, enrolment and withdrawal write `ParticipantEvent` rows; audit-log entries use the research code only
and never the group or any value.

## Control group and reminders
Reminders are the intervention. From allocation until the participant withdraws or the study is **Closed**, a control participant
receives no lecture reminders (filter registered with the reminder engine; pending reminders are cancelled at allocation and the
filter is re-applied at delivery). Not restricted: schedule-change notices (cancelled/moved lectures), non-participants, unallocated
participants, the intervention group. Withdrawn participants receive reminders again.
Decision for you: reminders already run system-wide. If the protocol needs a reminder-free baseline, switch reminders off in
Reminder settings during baseline.

## Measurements
Each `Measurement` = participant + outcome definition + period (baseline / post-intervention). Stored status: planned, collected,
missing (reason required), not applicable. Collected rows must have a value (within the outcome's range) and a collection date
(not in the future; post-intervention not before the recorded intervention start). The database enforces "value only when collected".
Shown states: **planned**, **not yet collected** (planned but the window has ended), **collected**, **missing**, **not applicable**,
**withdrawn**. Changing a collected value needs a reason; every change adds a `MeasurementRevision` (old and new value kept).
*Plan measurements* creates empty rows for enrolled participants only (idempotent; intervention-only outcomes only for the intervention group).

Windows: baseline start/end dates and the intervention start date are study settings. Post window = intervention start to the recorded
end, or start + configured weeks - 1 day. Unset dates mean "not set": nothing is assumed to have started or finished.

## System-calculated outcomes
Only for eligible, consenting, enrolled, non-withdrawn participants, only after the window has ended, never guessed:
| Outcome | Calculation |
|---|---|
| Attendance rate | Existing attendance rules over lectures held in the window; unrecorded lectures are not absences. |
| Punctuality rate | Existing punctuality rules over assignments due in the window with complete submission records. |
| Assessment score | Mean of per-course percentages (course weighting if entered, else simple mean) of marked items dated in the window; unmarked work is never zero. |
| Reminder read rate | Delivered reminders marked read / delivered reminders in the post window (intervention group only). |
If there is no valid data the row stays planned and the reason is shown. Recalculation records a revision. Each value stores the inputs used.

## Assumptions to confirm
1. One active study at a time (researcher pages work on it). 2. Administrators configure but do not see participant data.
3. Withdrawn participants are no longer restricted. 4. Control reminders stop at study closure. 5. Group targets must add up to the sample.
6. Questionnaire-based outcomes arrive in Phase 6; the statistics and exports in Phase 7 will exclude participants withdrawn with "exclude all data".
