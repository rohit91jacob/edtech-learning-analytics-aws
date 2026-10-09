-- Reconcile one mart cell against the Spark aggregate: active students in week 0 per presentation.
with mart as (
    select presentation_key, sum(active_students) as active
    from {{ ref('mart_engagement_weekly_cohorts') }}
    where cohort_dimension = 'final_result' and course_week = 0
    group by presentation_key
),

source as (
    select code_module || '_' || code_presentation as presentation_key, count(*) as active
    from {{ ref('stg_oulad__student_weekly_engagement') }}
    where course_week = 0
    group by code_module || '_' || code_presentation
)

select m.presentation_key, m.active, s.active as source_active
from mart as m
left join source as s on m.presentation_key = s.presentation_key
where m.active <> coalesce(s.active, 0)
