# Database models (through Phase 4)

All tables are created by Django migrations. Foreign keys to history/records use PROTECT where deleting would lose data.

## accounts
- **User** (custom): username, names, email, password hash, `role` (admin/lecturer/student/researcher), is_active, is_staff (derived).
- **AuditLog**: timestamp, actor (+ username copy), action, target, details, ip_address. Append-only.

## academics
- **Programme**: code (unique), name, duration_years, is_active.
- **Course**: code (unique), title, programme -> Programme, year_of_study, credit_units, is_active.
- **AcademicYear**: name (unique), start_date, end_date, is_current (only one).
- **Semester**: academic_year -> AcademicYear, number (1/2), start/end dates within the year, is_current (only one). Unique (year, number).
- **StudentProfile**: user (1:1, role must be student), registration_number (unique), programme, year_of_study, status.
- **LecturerProfile**: user (1:1, role must be lecturer), staff_number (unique), department.
- **CourseOffering**: course, semester, lecturers (M2M LecturerProfile), is_active. Unique (course, semester).
- **Enrolment**: student, offering, status (enrolled/withdrawn), enrolled_on. Unique (student, offering).

## timetables
- **Venue**: name (unique), building, capacity, is_active.
- **LectureSession**: offering, lecturer, venue, start_at, end_at (aware datetimes), topic, status (scheduled/cancelled), cancellation_reason, created_by, created_at, updated_at.
- **LectureChange**: session, change_type (created/rescheduled/cancelled), old/new start, end and venue, reason, changed_by, changed_at.

## reminders
- **ReminderConfig**: single row (pk 1). reminders_enabled, updated_at, updated_by.
- **ReminderInterval**: minutes_before (unique, 1-10080), label, is_active. Seeded: 1440, 60, 15. Deactivated, never deleted.
- **Notification**: recipient -> User, session -> LectureSession, kind (reminder / schedule_change), interval -> ReminderInterval (reminders only),
  minutes_before (snapshot), change -> LectureChange (notices only), title, message, scheduled_for, created_at,
  status (pending/delivered/cancelled/expired/failed), status_detail, attempts, processed_at, delivered_at, read_at, superseded.
  Constraints: one non-superseded reminder per (recipient, session, interval); one change notice per (recipient, change).
  Recipients only ever see their own *delivered* rows.
- **ReminderRun**: one execution of the processor. started/finished, trigger (command/admin), triggered_by, status,
  sync_created/updated/cancelled, due_found, delivered, expired, cancelled, failed, skipped, notes.

## attendance
- **AttendanceRules**: single row (pk 1). late_counts_as_attended (default yes), excused_policy (exclude / attended / absent; default exclude), updated_by, updated_at.
- **AttendanceRecord**: session -> LectureSession, student -> StudentProfile, status (present/absent/late/excused), recorded_by, recorded_at, updated_by, updated_at.
  Unique (session, student): there can never be two records for the same student and lecture. No record = "not recorded" (never an absence).
- **AttendanceChange**: append-only audit trail. record, old_status (blank on first recording), new_status, reason, changed_by, changed_at. Written for every recording and every correction.

## performance
- **Assignment**: offering, title, instructions, deadline, max_marks, weight_percent (optional), records_complete, created_by, created_at.
- **Submission**: assignment, student, status (submitted / not_submitted / exempt), submitted_at, extended_deadline (individual extension), marks (optional, submitted work only), recorded_by, updated_at. Unique (assignment, student).
- **Assessment**: offering, title, kind (test/exam/practical/other), assessment_date, max_marks, weight_percent (optional), created_by, created_at.
- **AssessmentResult**: assessment, student, status (marked / absent "did not sit" / exempt), marks (required only when marked), recorded_by, updated_at. Unique (assessment, student).

Tables for research and questionnaires are added in later phases.
