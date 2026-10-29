# Questionnaires and TAM (Phase 6)

App `questionnaires`. Researchers write every item. The system ships with **no pre-written questionnaire content**: a questionnaire
cannot be opened until a researcher has reviewed and approved its items. "Approve" means the researcher reviewed the items; it is not ethical approval.

## Who can do what
| Role | Access |
|---|---|
| Researcher | Create and edit questionnaires and questions, approve, open, close, duplicate, assign, read responses (by research code), reports. |
| Student | See and answer only questionnaires assigned to them, and read their own submitted answers. |
| Administrator, lecturer | None (403). Questionnaire data are individual research data. Django Admin: read-only, superusers only, participant link hidden. |

## Lifecycle
1. **Draft**: items editable. Any edit withdraws the earlier approval. 2. **Approve** items. 3. **Open** (needs approval, at least one question,
at least two options on every multiple-choice question). 4. **Assign** to enrolled, consenting, non-withdrawn participants: all, intervention
only or control only. Nothing is assigned automatically; assignment is idempotent, so run it again after enrolling more people.
5. **Close**. A closed questionnaire can be reopened. Once opened, items cannot be changed: **duplicate** it to make a corrected draft
(responses to the original are never altered).

## Question types
Five-point Likert (1 Strongly disagree ... 5 Strongly agree), multiple choice (one answer, options written one per line), optional free text.
Likert items can be tagged PU / PEOU / BI and can be reverse scored (flipped as 6 - value for construct scores).

## Answering
Own assignment only, only while open. Drafts may be partial ("save and finish later"). Submission needs every required question; if anything
is missing or invalid nothing is submitted and the message names the questions. A submitted response is **locked** (no edits, no re-submission);
there is currently no "re-open a response" feature. Timestamps stored: started, last updated, submitted. Answers are stored once per question (database rule).
Student pages show no research code and no group. Audit-log entries for questionnaires name the questionnaire and counts only, never participants.

## Reports (descriptive only; no tests, no conclusions)
- **Response rate** = submitted / assigned participants who have not withdrawn. Withdrawn participants are listed separately.
- **Usable responses** = submitted, excluding participants who withdrew with "exclude all of this participant's data". Drafts are never used.
- **Per question**: answered, skipped, % answered; Likert counts and mean; multiple-choice counts. Free text is read one response at a time.
- **Construct score** = mean of the construct's Likert items after reverse scoring, only if every item of that construct was answered
  (otherwise "incomplete", counted but not estimated). Shown per group with n, mean, SD (only when n >= 2), min and max, plus a Chart.js bar chart.
- Phase 7 adds inferential statistics, reliability and exports.

## Assumptions to confirm
1. Both groups can be assigned questionnaires (the intervention rule only stops *lecture reminders* to the control group). Choose "intervention only" for TAM items about the reminder system.
2. A questionnaire can be tied to one measurement period (baseline / post-intervention) for later comparisons.
3. Locked submissions and locked items after opening, to protect data integrity (see above).
4. Questionnaire scores are not yet copied into Phase 5 `Measurement` rows; Phase 7 reads responses directly.
5. Participants are told nothing by notification when a questionnaire is assigned: they see it under Questionnaires and a count on their dashboard.
