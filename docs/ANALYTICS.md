# Analytics, statistics and exports (Phase 7)

App `analytics` (no database tables of its own: everything is calculated from the research, questionnaire and reminder records).
**Researchers only.** Administrators, lecturers and students get 403. Administrators still see the aggregate counts on *Study settings*
(unchanged from Phase 5); this is a deliberate reading of "administrators must not see individual participant research data" - confirm it
fits your protocol. Nothing here contains findings: with no data every page says "analysis not yet available".

## Pages (researcher menu: Analytics)
| Page | What it shows |
|---|---|
| Research dashboard | Enrolled, consent, withdrawal; participants by group (chart); baseline and post-intervention completeness; outcomes by group and period with n, mean, SD, median, range and confidence interval (chart); reminder interaction; questionnaire response rates; TAM construct summaries; data-quality alert. |
| Statistical analysis | For each outcome: baseline comparability, post-intervention comparison, change-from-baseline comparison and paired before/after tests per group. For each TAM construct: summaries, Cronbach's alpha and a group comparison. |
| Data exports | Nine CSV datasets plus a data-quality report, with row counts and the data-quality checks. |
| Data dictionary | Every exported field: meaning, permitted values, how calculated (page and CSV). |

## Which data are used
Only participants who are **eligible, have given consent and are enrolled**. A withdrawn participant is used only if they chose "keep data
collected before withdrawal", and only data dated on or before the withdrawal date. "Exclude all data" (or no recorded choice) removes the
participant from every statistic and export. Only **collected** measurements enter a statistic: planned, missing and not-applicable rows are
counted as missing and never turned into zeros or filled in. Participants not yet allocated to a group are in no comparison. Withdrawn, declined
and ineligible people never appear in any export.

## When tests are shown
Each group needs at least **`min_analysis_n`** observations (pairs, for before/after tests). It is a study setting (*Study settings*, default 10, minimum 4):
set it according to the approved analysis plan. Below it the page shows "Analysis not yet available", the counts, and descriptive summaries only.
The significance level is also the study setting (default 0.05); confidence intervals use 1 minus that level.

## Methods
| Question | Primary test (chosen automatically) | Also shown (sensitivity) | Effect size |
|---|---|---|---|
| Two independent groups (post-intervention, baseline comparability, change scores, construct scores) | Welch's t-test **or** Mann-Whitney U | the other one | Hedges' g (CI) for Welch; rank-biserial correlation and P(intervention higher) for Mann-Whitney; mean difference with CI |
| Baseline vs post, within one group | Paired t-test **or** Wilcoxon signed-rank | the other one | Cohen's d_z (CI); matched-pairs rank-biserial |
| Scale reliability | Cronbach's alpha on participants who answered every item of the construct | | |

**Choosing the primary test.** t-test if every group has at least 30 observations (30 pairs) *or* at least 20 and a D'Agostino-Pearson normality screen
does not reject normality (p >= 0.05) in each group (in the differences, for pairs); otherwise the rank-based test. With fewer than 20 observations normality
cannot be assessed reliably, so the rank-based test is primary. The reason is printed next to every result. Both tests are always reported, so you can see
whether the choice matters. Two-sided p-values throughout.

**Implementation.** Standard textbook formulas in plain Python (`apps/analytics/stats.py`); no extra packages. Exact p-values for Mann-Whitney (no ties, groups
of at most 20) and Wilcoxon (no ties, at most 25 non-zero differences); otherwise a normal approximation with tie and continuity corrections. Zero differences are
dropped in the Wilcoxon test (reported). Results were cross-checked against SciPy during development (several hundred random cases, relative difference below 1e-7)
and reference values are frozen in `apps/analytics/test_stats.py`.

## Reading results correctly
- Group allocation is recorded by the researcher; the system does not randomise. A result is an **association**, never proof that reminders caused a change.
  A p-value above or below the significance level does not show that an effect is present or absent.
- Many outcomes are tested and **no correction for multiple testing** is applied. Pre-specify a primary outcome in the analysis plan.
- *Change from baseline* compares raw change scores. Adjusting for baseline (ANCOVA) is not implemented; it is often preferred and would need a statistician's decision.
- Baseline comparability is shown so that a pre-existing difference between groups is visible. It is not a test of the intervention.
- Reminder interaction counts reminders delivered to in-app notifications and whether they were opened. Opened does not mean the student acted on it.
- Cronbach's alpha needs at least 2 items and 2 complete responses; it is not estimated otherwise. Construct scores are never estimated for missing items.

## Exports (CSV)
Datasets: participant study records; attendance outcomes; assignment punctuality; academic performance; baseline measurements; post-intervention measurements;
questionnaire responses; TAM construct scores; reminder interaction events; plus a data-quality report. Field-by-field description: `DATA_DICTIONARY.md`
(generated from the code, so it cannot drift; a test fails if it is out of date: run `python manage.py export_data_dictionary`).
- Participants appear as their **research code**. No name, registration number, email, username, password or token is exported; only year of study as a covariate.
- **No free text** is exported (research notes, missing-value reasons, free-text answers), because it may contain identifying details.
- Values are written exactly as stored (never rounded, imputed or corrected). Empty cell = not applicable or not available, never zero.
- Rows for planned, overdue, missing and withdrawn measurements are included with their state so missing data are visible.
- Text cells starting with `=`, `+`, `-` or `@` are prefixed with an apostrophe so spreadsheets do not run them as formulas (numbers are untouched).
- Downloads are POST-only with CSRF protection, sent as attachments with `Cache-Control: no-store`, and each is written to the audit log (dataset and row count only).
- Format: comma separated, UTF-8 (no byte-order mark), CRLF line endings, ISO dates, date-times with a +03:00 offset. Excel on Windows opens the files; use *Data > From Text/CSV* with UTF-8 if accents look wrong.
- Handle the files as confidential research data. Group membership plus year of study can identify people in small cohorts; store and share accordingly.

## Data-quality checks (reported, never auto-fixed)
Errors to fix before analysis: duplicate research codes, measurements or answers; group without an allocation record or different from the latest allocation;
intervention-only outcome collected for a control participant; **control participant delivered reminders after allocation**; participant re-allocated after post data;
consent after enrolment, withdrawal before enrolment, future dates; post-intervention data before the intervention start; baseline on/after the start; data collected after withdrawal;
response before assignment. Notes: enrolled but not allocated; no collected data yet; overdue planned measurements; questionnaires past due; withdrawal without a recorded data choice.

## Assumptions to confirm
1. Researchers only; administrators keep aggregate counts (see above). 2. Default minimum of 10 observations per group before tests. 3. The rule for choosing the primary test (30 / 20 / normality screen).
4. Change-score comparison rather than ANCOVA. 5. No multiplicity correction. 6. Withdrawn participants who keep their data are used only up to the withdrawal date.
7. Only year of study is exported as a participant characteristic. 8. Free text is excluded from exports.

## Limitations
No ANCOVA, mixed models, survival or multiplicity adjustment; no sample-size or power calculation (the proposal's 156 / 78 / 78 are targets only); no intention-to-treat versus per-protocol distinction;
no handling of clustering (students in the same course); normality screening has low power below about 20 observations. Have a statistician confirm the analysis plan before reporting any result.
