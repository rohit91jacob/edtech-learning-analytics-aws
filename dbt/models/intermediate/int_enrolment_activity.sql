-- Whole-presentation clickstream summary per enrolment (from the Spark weekly table).
select
    code_module,
    code_presentation,
    id_student,
    sum(clicks) as total_clicks,
    sum(active_days) as total_active_days,
    {{ count_if('course_week >= 0') }} as active_weeks,
    sum(case when course_week < 0 then clicks else 0 end) as pre_start_clicks,
    min(first_day) as first_active_day,
    max(last_day) as last_active_day
from {{ ref('stg_oulad__student_weekly_engagement') }}
group by code_module, code_presentation, id_student
