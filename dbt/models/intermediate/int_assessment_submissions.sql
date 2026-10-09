-- One row per submitted assessment result, with the assessment's cut-off and the pass/mastery flags.
with results as (
    select * from {{ ref('stg_oulad__student_assessments') }}
),

assessments as (
    select * from {{ ref('stg_oulad__assessments') }}
)

select
    r.id_assessment,
    r.id_student,
    a.code_module,
    a.code_presentation,
    a.assessment_type,
    a.is_exam,
    a.cutoff_day,
    a.weight_pct,
    r.submitted_day,
    r.is_banked,
    r.score,
    case when a.cutoff_day is null then null else r.submitted_day <= a.cutoff_day end as is_on_time,
    r.score >= {{ var('pass_threshold') }} as is_passed,
    r.score >= {{ var('mastery_threshold') }} as is_mastered
from results as r
inner join assessments as a
    on r.id_assessment = a.id_assessment
