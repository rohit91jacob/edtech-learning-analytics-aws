-- Weekly VLE engagement curves per cohort. Grain: module presentation x cohort x course week.
-- Two cohort definitions are stacked: registration timing (known at enrolment) and final result
-- (known only afterwards, so descriptive, never a predictor).
{% set registered = 'unregistration_day is null or unregistration_day > course_week * 7' %}

with enrolments as (
    select * from {{ ref('int_enrolments') }}
),

cohorts as (
    select
        code_module,
        code_presentation,
        id_student,
        presentation_length_days,
        unregistration_day,
        'registration_timing' as cohort_dimension,
        registration_cohort as cohort_value
    from enrolments
    union all
    select
        code_module,
        code_presentation,
        id_student,
        presentation_length_days,
        unregistration_day,
        'final_result' as cohort_dimension,
        final_result as cohort_value
    from enrolments
),

grid as (
    select
        c.code_module,
        c.code_presentation,
        c.id_student,
        c.unregistration_day,
        c.cohort_dimension,
        c.cohort_value,
        w.course_week
    from cohorts as c
    cross join {{ ref('course_weeks') }} as w
    where w.course_week >= 0 and w.course_week * 7 < c.presentation_length_days
),

activity as (
    select * from {{ ref('stg_oulad__student_weekly_engagement') }}
),

joined as (
    select
        g.code_module,
        g.code_presentation,
        g.cohort_dimension,
        g.cohort_value,
        g.course_week,
        g.unregistration_day,
        a.clicks,
        a.active_days
    from grid as g
    left join activity as a
        on
            g.code_module = a.code_module
            and g.code_presentation = a.code_presentation
            and g.id_student = a.id_student
            and g.course_week = a.course_week
)

select
    code_module,
    code_presentation,
    code_module || '_' || code_presentation as presentation_key,
    cohort_dimension,
    cohort_value,
    course_week,
    count(*) as enrolled,
    {{ count_if(registered) }} as still_registered,
    {{ count_if('clicks > 0') }} as active_students,
    {{ safe_divide(count_if('clicks > 0'), 'count(*)') }} as pct_active_of_enrolled,
    {{ safe_divide(count_if('clicks > 0'), count_if(registered)) }} as pct_active_of_registered,
    {{ safe_divide('sum(clicks)', count_if('clicks > 0')) }} as avg_clicks_per_active,
    {{ percentile('clicks', 0.5) }} as median_clicks_per_active,
    {{ safe_divide('sum(active_days)', count_if('clicks > 0')) }} as avg_active_days_per_active
from joined
group by code_module, code_presentation, cohort_dimension, cohort_value, course_week
