# Research data dictionary

Generated from the dataset definitions in `apps/analytics/exports.py` (`python manage.py export_data_dictionary`). Every CSV starts with a header row naming these fields, in this order. Empty cells mean "not applicable or not available", never zero. Files are comma-separated, UTF-8, with CRLF line endings. Dates are ISO (YYYY-MM-DD); date-times carry a UTC offset (Africa/Kampala is +03:00); yes/no fields are written `yes` or `no`.

No dataset contains names, registration numbers, emails, usernames, passwords, tokens or free text typed by researchers or participants. Text cells that start with `=`, `+`, `-` or `@` are prefixed with an apostrophe so spreadsheets do not run them as formulas.

## Participant study records (`participants`)

One row per participant whose data may be used (eligible, consent given, enrolled; withdrawn participants only if they chose to keep their data). Participants who declined, were ineligible, never enrolled, or withdrew with "exclude all data" are not listed.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `year_of_study` | Student's year of study as recorded in the system at export time. | 1 to 6 | Copied from the stored record. |
| `eligibility` | Eligibility decision recorded by the researcher. | eligible | Copied from the stored record. |
| `consent_status` | Consent status. | given | Copied from the stored record. |
| `consent_date` | Date consent was given. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `enrolled_on` | Date the participant was enrolled in the study. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `allocation_method` | How the latest allocation was made (the full procedure text is not exported). | manual, external_randomisation, other, or empty if not allocated | Copied from the stored record. |
| `allocation_date` | Date of the latest allocation. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `allocation_count` | Number of allocation records (more than 1 means the participant was re-allocated). | 0, 1, 2, ... | Copied from the stored record. |
| `reallocated` | Whether the participant was ever moved between groups. | yes / no | Copied from the stored record. |
| `withdrawn` | Whether the participant has withdrawn. | yes / no | Copied from the stored record. |
| `withdrawn_on` | Date of withdrawal. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `withdrawal_data_handling` | What the participant chose for data collected before withdrawal. | retain, or empty if not withdrawn | Copied from the stored record. |

## Attendance outcomes (`attendance`)

Lecture attendance rate measurements (baseline and post-intervention), including planned and missing rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `outcome_code` | Short code of the outcome definition (set by the researcher). | e.g. attendance-rate | Copied from the stored record. |
| `outcome_name` | Name of the outcome. | Text from the outcome definition | Copied from the stored record. |
| `outcome_kind` | Type of outcome. | attendance_rate, punctuality_rate, assessment_score, reminder_interaction, questionnaire_score, other | Copied from the stored record. |
| `unit` | Unit of the value. | e.g. percent, score, count | Copied from the stored record. |
| `period` | Measurement period. | baseline, post_intervention | Copied from the stored record. |
| `status` | Stored status of the measurement. | planned, collected, missing, not_applicable | Copied from the stored record. |
| `state` | Status as shown in the application, which also separates overdue and withdrawn rows. | collected, planned, not_yet_collected, missing, not_applicable, withdrawn | planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew. |
| `value` | The measured value. Empty unless the status is collected (never zero-filled). | Decimal number within the outcome's range, or empty | For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher. |
| `collected_on` | Date the value was collected or calculated. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `source` | How the value was obtained. | manual (entered by a researcher), system (calculated from system records), or empty | Copied from the stored record. |
| `calculation_detail` | Inputs the system used when it calculated the value (counts, rules applied). | Text, or empty for manual values | Copied from the stored record. |

## Assignment punctuality (`punctuality`)

Assignment punctuality rate measurements (baseline and post-intervention), including planned and missing rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `outcome_code` | Short code of the outcome definition (set by the researcher). | e.g. attendance-rate | Copied from the stored record. |
| `outcome_name` | Name of the outcome. | Text from the outcome definition | Copied from the stored record. |
| `outcome_kind` | Type of outcome. | attendance_rate, punctuality_rate, assessment_score, reminder_interaction, questionnaire_score, other | Copied from the stored record. |
| `unit` | Unit of the value. | e.g. percent, score, count | Copied from the stored record. |
| `period` | Measurement period. | baseline, post_intervention | Copied from the stored record. |
| `status` | Stored status of the measurement. | planned, collected, missing, not_applicable | Copied from the stored record. |
| `state` | Status as shown in the application, which also separates overdue and withdrawn rows. | collected, planned, not_yet_collected, missing, not_applicable, withdrawn | planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew. |
| `value` | The measured value. Empty unless the status is collected (never zero-filled). | Decimal number within the outcome's range, or empty | For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher. |
| `collected_on` | Date the value was collected or calculated. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `source` | How the value was obtained. | manual (entered by a researcher), system (calculated from system records), or empty | Copied from the stored record. |
| `calculation_detail` | Inputs the system used when it calculated the value (counts, rules applied). | Text, or empty for manual values | Copied from the stored record. |

## Academic performance (`performance`)

Academic assessment score measurements (baseline and post-intervention), including planned and missing rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `outcome_code` | Short code of the outcome definition (set by the researcher). | e.g. attendance-rate | Copied from the stored record. |
| `outcome_name` | Name of the outcome. | Text from the outcome definition | Copied from the stored record. |
| `outcome_kind` | Type of outcome. | attendance_rate, punctuality_rate, assessment_score, reminder_interaction, questionnaire_score, other | Copied from the stored record. |
| `unit` | Unit of the value. | e.g. percent, score, count | Copied from the stored record. |
| `period` | Measurement period. | baseline, post_intervention | Copied from the stored record. |
| `status` | Stored status of the measurement. | planned, collected, missing, not_applicable | Copied from the stored record. |
| `state` | Status as shown in the application, which also separates overdue and withdrawn rows. | collected, planned, not_yet_collected, missing, not_applicable, withdrawn | planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew. |
| `value` | The measured value. Empty unless the status is collected (never zero-filled). | Decimal number within the outcome's range, or empty | For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher. |
| `collected_on` | Date the value was collected or calculated. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `source` | How the value was obtained. | manual (entered by a researcher), system (calculated from system records), or empty | Copied from the stored record. |
| `calculation_detail` | Inputs the system used when it calculated the value (counts, rules applied). | Text, or empty for manual values | Copied from the stored record. |

## Baseline measurements (`baseline`)

Every baseline measurement of every outcome, including planned, missing and not-applicable rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `outcome_code` | Short code of the outcome definition (set by the researcher). | e.g. attendance-rate | Copied from the stored record. |
| `outcome_name` | Name of the outcome. | Text from the outcome definition | Copied from the stored record. |
| `outcome_kind` | Type of outcome. | attendance_rate, punctuality_rate, assessment_score, reminder_interaction, questionnaire_score, other | Copied from the stored record. |
| `unit` | Unit of the value. | e.g. percent, score, count | Copied from the stored record. |
| `period` | Measurement period. | baseline, post_intervention | Copied from the stored record. |
| `status` | Stored status of the measurement. | planned, collected, missing, not_applicable | Copied from the stored record. |
| `state` | Status as shown in the application, which also separates overdue and withdrawn rows. | collected, planned, not_yet_collected, missing, not_applicable, withdrawn | planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew. |
| `value` | The measured value. Empty unless the status is collected (never zero-filled). | Decimal number within the outcome's range, or empty | For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher. |
| `collected_on` | Date the value was collected or calculated. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `source` | How the value was obtained. | manual (entered by a researcher), system (calculated from system records), or empty | Copied from the stored record. |
| `calculation_detail` | Inputs the system used when it calculated the value (counts, rules applied). | Text, or empty for manual values | Copied from the stored record. |

## Post-intervention measurements (`post_intervention`)

Every post-intervention measurement of every outcome, including planned, missing and not-applicable rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `outcome_code` | Short code of the outcome definition (set by the researcher). | e.g. attendance-rate | Copied from the stored record. |
| `outcome_name` | Name of the outcome. | Text from the outcome definition | Copied from the stored record. |
| `outcome_kind` | Type of outcome. | attendance_rate, punctuality_rate, assessment_score, reminder_interaction, questionnaire_score, other | Copied from the stored record. |
| `unit` | Unit of the value. | e.g. percent, score, count | Copied from the stored record. |
| `period` | Measurement period. | baseline, post_intervention | Copied from the stored record. |
| `status` | Stored status of the measurement. | planned, collected, missing, not_applicable | Copied from the stored record. |
| `state` | Status as shown in the application, which also separates overdue and withdrawn rows. | collected, planned, not_yet_collected, missing, not_applicable, withdrawn | planned = expected, not collected yet; not_yet_collected = planned but its window has ended; withdrawn = participant withdrew. |
| `value` | The measured value. Empty unless the status is collected (never zero-filled). | Decimal number within the outcome's range, or empty | For system-calculated outcomes see calculation_detail and docs/ATTENDANCE_PERFORMANCE.md; otherwise entered by a researcher. |
| `collected_on` | Date the value was collected or calculated. | ISO date YYYY-MM-DD, or empty | Copied from the stored record. |
| `source` | How the value was obtained. | manual (entered by a researcher), system (calculated from system records), or empty | Copied from the stored record. |
| `calculation_detail` | Inputs the system used when it calculated the value (counts, rules applied). | Text, or empty for manual values | Copied from the stored record. |

## Questionnaire responses (`questionnaire_responses`)

One row per question per submitted response (so skipped questions appear as unanswered). Free-text answers are not exported.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `questionnaire_id` | Identifier of the questionnaire. | Integer | Copied from the stored record. |
| `questionnaire_title` | Title of the questionnaire. | Text | Copied from the stored record. |
| `questionnaire_period` | Measurement period the questionnaire is tied to. | baseline, post_intervention, or empty | Copied from the stored record. |
| `submitted_at` | When the participant submitted the response. | ISO date-time with UTC offset (Africa/Kampala is +03:00), or empty | Copied from the stored record. |
| `question_id` | Identifier of the question. | Integer | Copied from the stored record. |
| `question_order` | Position of the question in the questionnaire. | 1, 2, ... | Copied from the stored record. |
| `question_text` | The question as asked. | Text | Copied from the stored record. |
| `question_type` | Type of question. | likert, choice, text | Copied from the stored record. |
| `construct` | Technology Acceptance Model construct the item measures. | PU, PEOU, BI, or empty | Copied from the stored record. |
| `reverse_scored` | Whether a Likert item is negatively worded and flipped for construct scores. | yes / no | Copied from the stored record. |
| `answered` | Whether the participant answered this question. | yes / no | Copied from the stored record. |
| `likert_value` | The answer as given on the five-point scale. | 1 Strongly disagree, 2 Disagree, 3 Neither, 4 Agree, 5 Strongly agree; empty if not a Likert answer | Copied from the stored record. |
| `scored_value` | Likert value used for scoring. | 1 to 5, or empty | 6 minus likert_value for reverse-scored items; otherwise equal to likert_value. |
| `option_label` | Selected option of a multiple-choice question. | Text, or empty | Copied from the stored record. |
| `text_provided` | For free-text questions, whether any text was written (the text itself is not exported). | yes / no, or empty for other types | Copied from the stored record. |

## TAM construct scores (`construct_scores`)

One row per submitted response and Technology Acceptance Model construct present in the questionnaire.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `questionnaire_id` | Identifier of the questionnaire. | Integer | Copied from the stored record. |
| `questionnaire_title` | Title of the questionnaire. | Text | Copied from the stored record. |
| `questionnaire_period` | Measurement period the questionnaire is tied to. | baseline, post_intervention, or empty | Copied from the stored record. |
| `submitted_at` | When the participant submitted the response. | ISO date-time with UTC offset (Africa/Kampala is +03:00), or empty | Copied from the stored record. |
| `construct` | Technology Acceptance Model construct. | PU (Perceived Usefulness), PEOU (Perceived Ease of Use), BI (Behavioural Intention) | Copied from the stored record. |
| `items_in_construct` | Number of Likert items in the construct. | Integer | Copied from the stored record. |
| `score` | Construct score, empty when any item of the construct was not answered (nothing is estimated). | 1.0 to 5.0, or empty | Mean of the construct's Likert items after reverse scoring (6 minus value for reverse-scored items). |
| `complete` | Whether every item of the construct was answered. | yes / no | Copied from the stored record. |

## Reminder interaction events (`reminder_events`)

One row per lecture reminder delivered to a participant (to their in-app notifications), within the post-intervention window if set, otherwise all delivered reminders. Control-group participants are not sent reminders, so they normally have no rows.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `research_code` | Anonymous participant identifier assigned when the student was registered in the study. It is not derived from the student's name or number. | P- followed by 6 letters/digits, e.g. P-7KQ2MX | Copied from the stored record. |
| `group` | The participant's current study group. | intervention, control, or empty (enrolled but not yet allocated) | Latest allocation recorded by the researcher; the system never randomises. |
| `course_code` | Code of the course the lecture belongs to. | e.g. BIT101 | Copied from the stored record. |
| `lecture_date` | Date of the lecture the reminder was about (Africa/Kampala). | ISO date YYYY-MM-DD | Copied from the stored record. |
| `minutes_before` | How long before the lecture the reminder was scheduled. | Integer minutes, e.g. 1440, 60, 15 | Copied from the stored record. |
| `delivered_at` | When the reminder became visible in the participant's notifications. | ISO date-time with UTC offset (Africa/Kampala is +03:00), or empty | Copied from the stored record. |
| `read_at` | When the participant opened (marked read) the reminder. | ISO date-time with UTC offset (Africa/Kampala is +03:00), or empty | Copied from the stored record. |
| `is_read` | Whether the reminder was opened. | yes / no | Copied from the stored record. |
| `minutes_to_read` | Minutes between delivery and opening. | Decimal number, or empty if unread | (read_at - delivered_at) in minutes, one decimal place. |

## Data quality report (`data_quality_report`)

Findings of the automatic checks. The checks only report; they never change the data.

| Field | Meaning | Permitted values | How calculated |
|---|---|---|---|
| `severity` | Seriousness of the finding. | error (an inconsistency to fix before analysis), warning (missing or incomplete data) | Copied from the stored record. |
| `code` | Short code of the check. | Text | Copied from the stored record. |
| `message` | What was found. | Text | Copied from the stored record. |
| `count` | Number of participants (or records) affected. | Integer | Copied from the stored record. |
| `example_research_codes` | Up to 10 research codes affected, separated by semicolons. | Text | Copied from the stored record. |
