# Database models (through Phase 2)

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

Tables for reminders, attendance, assignments, research and questionnaires are added in later phases.
