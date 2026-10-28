# Researcher guide

Status: covers Phases 1-6 (study, participants, measurements, questionnaires). **Group analytics, statistical tests and CSV exports are Phase 7 and are not built yet.**
Full rules, assumptions and limits: `RESEARCH.md` and `QUESTIONNAIRES.md`. This software does not claim ethical approval and contains no research findings; planning figures
(population 350, sample 156, 78 per group, eight weeks) are editable defaults from the proposal.

## Your menu
**Study**: Study settings, Outcome definitions. **Participants**: Participants. **Data**: Measurements, Data completeness, Questionnaires.

## Typical workflow
1. **Study settings**: confirm or edit the settings, ethics status, baseline dates and intervention start. Only one study is active at a time; without an active study the research pages send you to Study settings.
2. **Outcome definitions**: define what is measured (attendance rate, punctuality, assessment score, reminder read rate, questionnaire-based outcomes).
3. **Participants**: register a student (a random research code is created; this is not consent or enrolment), record eligibility and consent, then enrol, allocate to intervention or control (you choose the group, the method and write the procedure - the system never randomises), and record withdrawals with whether data are kept or excluded.
4. **Measurements**: *Plan measurements* creates empty baseline/post rows; record collected values with the collection date, or mark missing with a reason. System-calculated outcomes are filled only when the window has ended and valid data exist. Changing a collected value needs a reason and keeps the earlier value.
5. **Data completeness**: planned vs collected vs missing vs not applicable vs withdrawn, by period and group.
6. **Questionnaires**: create questionnaires with Likert, multiple-choice and text items for TAM constructs (Perceived Usefulness, Perceived Ease of Use, Behavioural Intention); example items are labelled as examples requiring your approval. Assign to participants, then review response completeness.

## Controls built in
- Control-group participants receive no lecture reminders while allocated and not withdrawn and the study is open; schedule-change notices (cancelled/moved lectures) are still sent.
- You cannot see marks or attendance directly; they enter the study only through the calculated measurements for consenting, enrolled participants.
- Administrators can edit study settings but cannot see participant data.
- Superusers can read participant tables (read-only) in Django Admin; keep superuser accounts few.

## Not available yet (Phase 7)
Dashboards with group comparisons, statistical tests with effect sizes and confidence intervals, CSV exports, and the data dictionary.
