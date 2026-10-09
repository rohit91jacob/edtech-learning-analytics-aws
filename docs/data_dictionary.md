# Data dictionary

Days are **relative to the presentation start** (day 0), as in the source; negative days are before
the start. A *presentation* is one run of a module (`2013J` = started October 2013, `B` =
February). An *enrolment* is one student on one presentation (`code_module, code_presentation,
id_student`); the same `id_student` can appear in several presentations.

## Raw zone (`raw/oulad/version=<sha256[:16]>/`)

The seven CSV files of the release, byte-for-byte, plus `_manifest.json` (sha256, bytes and row
count per file, source URL, licence). `CURRENT` names the version the pipeline reads. In AWS this
is `s3://<project>-<env>-raw-<account>/oulad/`.

## Silver (Iceberg, namespace `silver`; Glue database `<project>_<env>_silver` on AWS)

All tables carry `_raw_version`. Values `""` (figshare) and `"?"` (UCI mirror) become NULL.

| Table | Grain | Source | Notes |
|---|---|---|---|
| `courses` | presentation | courses.csv | `module_presentation_length` (days); derived `presentation_year`, `presentation_start_month` (2 or 10) |
| `assessments` | assessment | assessments.csv | `assessment_type` TMA (tutor-marked), CMA (computer-marked), Exam; `date` = cut-off day (NULL for 11 exams: "last week of the presentation"); `weight` % |
| `vle_sites` | VLE material | vle.csv | `activity_type` (20 values: resource, oucontent, forumng, quiz, ...); planned `week_from`/`week_to` (mostly NULL) |
| `students` | enrolment | studentInfo.csv | demographics, `num_of_prev_attempts`, `studied_credits`, `final_result` (Pass, Distinction, Fail, Withdrawn); `imd_band` "10-20" normalised to "10-20%"; derived `is_disabled` |
| `registrations` | enrolment | studentRegistration.csv | `date_registration`, `date_unregistration` (NULL if never unregistered) |
| `student_assessments` | assessment result | studentAssessment.csv | `date_submitted`, `is_banked` (carried over from an earlier presentation), `score` 0-100 (NULL for 173 rows) |
| `student_vle` | daily clicks on one material | studentVle.csv | 10,655,280 rows, partitioned by module and presentation. Not unique on (enrolment, site, date): the release has 1,614,505 such groups with more than one row; rows are kept and summed downstream |
| `student_weekly_activity` | enrolment x course week x activity type | Spark aggregate of `student_vle` + `vle_sites` | `course_week = floor(date / 7)`; `clicks`, `active_days` (distinct days), `distinct_sites`, `log_rows`, `first_day`, `last_day` |
| `student_weekly_engagement` | enrolment x course week | Spark aggregate of `student_vle` | same measures across all activity types (computed from the clickstream, because distinct days cannot be summed) |
| `ops_load_audit` | silver table | silver job | raw vs silver row counts and cast failures (the `load_*` DQ checks read it) |
| `ops_dq_results` | check x run | DQ job | appended every run: name, layer, severity, violations, passed, run_id, checked_at |

## dbt (DuckDB locally; Athena on AWS)

### Staging (views)

`stg_oulad__*`: one per silver table, renamed and typed (`date` -> `cutoff_day`, `submitted_day`,
`registration_day`, ...). `imd_band` NULL becomes `Unknown`.

### Intermediate

| Model | Grain | Key columns |
|---|---|---|
| `int_enrolments` | enrolment | demographics, `domain` (seed), `is_pass` (Pass or Distinction), `is_distinction`, `is_fail`, `is_withdrawn`, `registration_day`, `unregistration_day`, `registration_cohort` |
| `int_assessment_submissions` | assessment result | `is_on_time` (`submitted_day <= cutoff_day`), `is_passed` (score >= 40), `is_mastered` (score >= `mastery_threshold`, default 70) |
| `int_enrolment_activity` | enrolment | whole-presentation clicks, active days, active weeks, pre-start clicks |

`registration_cohort`: `early` (registered more than 30 days before the start), `on_time` (0-30
days before), `late` (after the start), `unknown` (no registration day, 45 enrolments).

### Marts

| Mart | Grain | What it answers |
|---|---|---|
| `dim_module_presentation` | presentation | size, assessment counts, pass / fail / withdrawal rates |
| `mart_engagement_weekly_cohorts` | presentation x cohort x course week | `enrolled`, `still_registered` (not unregistered before the week), `active_students` (>= 1 click), `pct_active_of_enrolled`, `pct_active_of_registered`, clicks per active student. `cohort_dimension` = `registration_timing` or `final_result` |
| `mart_assessment_mastery_funnel` | assessment | `enrolled` -> `submitted` -> `passed` -> `mastered`; `registered_at_cutoff`, `submitted_on_time`, `banked` (excluded from the funnel), rates, `avg_score`, `median_score`, `is_formative` (0% weight), `has_results` |
| `fct_first_submission` | enrolment | `first_submission_day`, `n_submissions`, `days_after_start_or_registration`, `submitted_by_first_cutoff` |
| `mart_time_to_first_submission` | presentation x final result | share never submitting, quartiles of the first-submission day |
| `mart_dropout_risk_features` | enrolment still registered on `risk_cutoff_day` (default 28) | features from course weeks before the cut-off week and submissions before the cut-off day; `label_withdrawn`; `split` = `test` for `holdout_presentation` (2014J) |
| `mart_vle_activity_effectiveness` | module x activity type | among enrolments that did not withdraw: `usage_rate`, `pass_rate_users`, `pass_rate_non_users`, `pass_rate_lift`, `small_sample` |
| `mart_outcome_fairness_slices` | slice dimension x value | `age_band`, `imd_band`, `disability` and `overall`: pass, distinction, fail and withdrawal rates, gaps in percentage points vs overall, `small_sample` (< 100) |

### Definitions

* **Active** in a week: at least one VLE click that course week.
* **Pass mark**: score >= 40 (the data descriptor: "lower than 40 is interpreted as Fail").
* **Mastered**: score >= 70. This is *this project's* threshold for a Khan-style "mastery" stage,
  not an OU rule. Configurable with `EDTECH_MASTERY_THRESHOLD`.
* **Withdrawal** (model label): `final_result = 'Withdrawn'`. 93 withdrawn enrolments have no
  unregistration day; they stay positives.
* **Percentiles**: exact (`quantile_cont`) on DuckDB, `approx_percentile` on Athena.

## Model outputs (DuckDB schema `ml`)

| Table | Content |
|---|---|
| `risk_model_metrics` | metric / value (JSON) pairs: AUCs, CI, base rates, threshold, recall, precision, features, seed |
| `risk_model_slices` | held-out metrics per age band, IMD band and disability: n, base rate, mean predicted risk, calibration gap, AUC (n >= 50), TPR, FPR, precision, flag rate |
| `risk_model_per_module` | the same per module |
| `risk_model_coefficients` | standardised logistic-regression coefficients |

## Ops files (`ops/`)

`executions/<name>.json` (local state-machine history), `dq_results_gold.json`,
`verification.json`, `risk_model.json`.
