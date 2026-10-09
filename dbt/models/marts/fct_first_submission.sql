-- One row per enrolment: when the student first submitted an assessment (banked results excluded).
with enrolments as (
    select * from {{ ref('int_enrolments') }}
),

first_submission as (
    select
        code_module,
        code_presentation,
        id_student,
        min(submitted_day) as first_submission_day,
        count(*) as n_submissions
    from {{ ref('int_assessment_submissions') }}
    where not is_banked
    group by code_module, code_presentation, id_student
),

first_cutoff as (
    select
        code_module,
        code_presentation,
        min(cutoff_day) as first_cutoff_day
    from {{ ref('stg_oulad__assessments') }}
    where not is_exam
    group by code_module, code_presentation
)

select
    e.code_module,
    e.code_presentation,
    e.presentation_key,
    e.id_student,
    e.final_result,
    e.registration_cohort,
    e.registration_day,
    c.first_cutoff_day,
    f.first_submission_day,
    coalesce(f.n_submissions, 0) as n_submissions,
    f.first_submission_day is not null as has_submitted,
    -- Days from the later of presentation start and the student's registration.
    f.first_submission_day - greatest(coalesce(e.registration_day, 0), 0) as days_after_start_or_registration,
    case
        when f.first_submission_day is null then null
        else f.first_submission_day <= c.first_cutoff_day
    end as submitted_by_first_cutoff
from enrolments as e
left join first_submission as f
    on
        e.code_module = f.code_module
        and e.code_presentation = f.code_presentation
        and e.id_student = f.id_student
left join first_cutoff as c
    on e.code_module = c.code_module and e.code_presentation = c.code_presentation
