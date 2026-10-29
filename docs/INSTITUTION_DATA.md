# Institution data

`python manage.py load_institution_data` loads the reference data that can be verified from Metropolitan International
University's own published pages. It is run automatically by the one-click setup, and is safe to run again: it never
changes or duplicates anything that already exists.

## About the institution (from miu.ac.ug, checked 30 October 2026)
- Private university accredited by Uganda's National Council for Higher Education; established November 2016.
- Campuses: Kisoro (main), Mbarara (Biharwe Division) and Kampala (Nakibinge Road, off Kampala-Hoima Road).
- Teaching uses blended learning: the university states that all programmes are developed as e-learning programmes
  and that teaching, learning and assessment run on its online e-learning platform. MIU-LRSES is a separate system and
  does not connect to that platform. Confirm with the university how the two will be used together in the study.
- Admissions: several intakes a year (January, May and August/September are mentioned on the university's pages).

## What is loaded
| Code | Programme | Duration |
|---|---|---|
| BBA | Bachelor of Business Administration | 3 years |
| BIT | Bachelor of Information Technology | 3 years |
| BSW | Bachelor of Social Work and Social Administration | 3 years |
| BCOM | Bachelor of Commerce | 3 years |
| BPAM | Bachelor of Public Administration and Management | 3 years |
| BJM | Bachelor of Journalism and Media Studies | 3 years |
| BTHM | Bachelor of Tourism and Hotel Management | 3 years |

These are the programmes that carry an official abbreviation and a three-year duration on the university's programme
and faculty pages. The research study profile is also created (only if no study exists yet) with the title from the
research proposal and its planning figures (population 350, sample 156, 78 intervention, 78 control, eight weeks), with
status *Planning*, ethics status *Not recorded* and **no dates**. The four standard outcome definitions are added and can
be edited.

## What is not loaded, and why
- **Academic years and semesters.** No verifiable semester calendar was found, and intakes differ, so no dates are assumed.
  Create them under Academic records using the Academic Registrar's calendar.
- **Courses (units) and course codes, venues, lecturers, students, enrolments.** Not published in a form that can be
  verified. Enter them from official records.
- **Attendance, marks, research participants, measurements and questionnaire responses.** These are collected data. They
  only ever come from real records, never from a loader.

## Programmes found but not loaded
Other programmes appear on the university's pages (for example Computer Science, Accounting and Finance, Business Computing,
Procurement and Logistics Management, Human Resource Management, Marketing, Economics, Agriculture and Rural Innovation,
Education, Laws, and Nursing Science at the Mbarara campus). They were left out because no official abbreviation was
found or because durations differ between pages. Add them under Academic records > Programmes with the codes the
Registrar uses.

## Cautions
- The university's web pages are not fully consistent (faculty names, some programme names and durations differ between
  pages). Treat this list as a starting point and check it against the Academic Registrar's current programme list.
- Tuition and fees are deliberately not stored.
- Ethical approval is not implied by anything in this software. Record the real status and reference on the study page.
