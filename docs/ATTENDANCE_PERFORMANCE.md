# Attendance and academic performance (Phase 4)

This document defines exactly how attendance rates, assignment punctuality and academic performance are calculated,
and how missing data is handled. These are defaults chosen for this build; where your institution's policy differs,
the attendance rules can be changed by an administrator (**Attendance rules**), and the rest should be confirmed
against the approved research protocol before real data is collected. Nothing in this software contains real data.

## Who can do what
| Action | Administrator | Lecturer | Student | Researcher |
|---|---|---|---|---|
| Record / correct attendance | Any lecture | Lectures of courses assigned to them | No | No |
| View course and student attendance reports | All | Their courses only (404 otherwise) | No | No |
| View own attendance | - | - | Yes | No |
| Create assignments / assessments, record submissions and marks | Any course | Their courses only | No | No |
| View course performance report | All | Their courses only | No | No |
| View own deadlines, submission status and results | - | - | Yes (never anyone else's) | No |
| Change attendance calculation rules | Yes | No | No | No |

A researcher has no access to attendance, marks or submissions yet. Research exports of individual outcomes arrive in
Phase 5 and 7, behind consent and participant-code rules.

## Attendance
**Recording.** Open a lecture and choose *Take or correct attendance*. Statuses: Present, Absent, Late, Excused.
The register lists students currently enrolled in the course. A lecture can be recorded only after it has started and
not if it is cancelled. Leaving a student as *Not recorded* creates no record.

**One record per student and lecture** (database constraint). Saving the same values again changes nothing.

**Corrections.** Changing an already-recorded status needs a reason. Every first recording and every correction is
kept in an append-only history (who, when, old status, new status, reason) shown on the attendance page, and an audit
log entry is written. Records can be corrected but not deleted through the application.

**Held lecture.** Scheduled (not cancelled) and already started. A lecture counts for a student only if the student's
enrolment is active (not withdrawn) and the enrolment date is on or before the lecture date.

**Rate.**
```
attended    = present + late (if "late counts as attended") + excused (if policy = attended)
denominator = present + late + absent + excused (only if policy = attended or absent)
rate        = attended / denominator x 100   (one decimal place, half-up; "n/a" if the denominator is 0)
```
Defaults: late counts as attended; excused absences are excluded from the rate.

**Missing records.** A held lecture with no record is reported as *Not recorded* and is **never** treated as an
absence. It is left out of the rate and shown next to it, so data completeness is visible.

**Reports.** Student level (own page for students; staff open it from the course roster; a lecturer sees only their
own courses' figures), and course level (per student, per lecture, overall, with a bar chart).

## Assignments and punctuality
Assignments have a deadline, optional instructions, maximum marks and an optional weight.
Per student, lecturers record a submission status: *Submitted* (with time), *Not submitted*, or *Exempt*, an optional
individual **extension** deadline, and optional marks (submitted work only). "No record" leaves the student untouched.

**Effective deadline** = the student's extension if one exists, otherwise the assignment deadline.

| Situation | Treated as |
|---|---|
| Submitted at or before the effective deadline | On time |
| Submitted after the effective deadline | Late |
| Effective deadline passed, no submission, **records marked complete** | Not submitted (counts against punctuality) |
| Exempt | Excluded |
| Effective deadline not yet passed (including a granted extension) | Not yet due, excluded |
| Enrolment withdrawn, or enrolled after the deadline date | Excluded |

```
punctuality rate = on time / (on time + late + not submitted) x 100
```
**Records complete.** An assignment is included in punctuality rates only after its lecturer ticks *Submission records
are complete*. Until then nobody is counted late merely because a record was not entered yet; the report states how many
assignments are awaiting complete records.

## Assessments and marks
Assessments (test, examination, practical, other) have maximum marks, an optional date and an optional weight.
Per student: *Marked* (with marks), *Did not sit*, *Exempt*, or no record.

* Item percentage = marks / maximum x 100 (one decimal place, half-up).
* **Missing marks are never zero.** Unmarked, did-not-sit and exempt items are left out of averages.
* **Course percentage.** Courses do not share one weighting scheme, so weights are optional per item:
  * if any marked item has a weight: weighted mean over weighted items = sum(weight x percentage) / sum(weight),
    and the share of total weight already marked is shown; unweighted items are not used;
  * otherwise the simple mean of item percentages.
* No letter grades, pass marks or grade points are assumed. Only percentages are reported. If the approved protocol
  needs bands, they should be added as configuration in a later phase.
* Marks changes (including old and new value per student id) are written to the audit log.

## Reports and charts
* Attendance: course report with per-student bar chart; per-student and per-lecture tables.
* Performance: course report with class mean, median, distribution chart (10-point bands, 0-39 combined), per-student course
  percentage, method and punctuality.

## Assumptions and known limitations
* Assumption: attendance can be recorded from the moment a lecture starts.
* Assumption: a student with no submission record for an assignment still counts as "not submitted" once records are complete.
* Assumption: individual extensions are recorded per student; there is no group-wide extension (change the assignment deadline instead).
* Limitation: attendance and marks have no CSV import yet; entry is through the register and record pages.
* Limitation: enrolment history is by date only; a student withdrawn and later re-enrolled is treated by the current enrolment row.
* Limitation: the research-specific measurement windows (baseline and post-intervention) are not yet applied. The
  calculation functions already accept time windows so Phase 5 can use them without changing the rules.
