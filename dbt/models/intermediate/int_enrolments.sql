-- One row per student enrolment (student x module presentation): demographics, registration
-- timing, outcome flags and presentation attributes. The spine of every mart.
with students as (
    select * from {{ ref('stg_oulad__students') }}
),

registrations as (
    select * from {{ ref('stg_oulad__registrations') }}
),

courses as (
    select * from {{ ref('stg_oulad__courses') }}
),

domains as (
    select * from {{ ref('module_domains') }}
)

select
    s.code_module,
    s.code_presentation,
    c.presentation_key,
    s.id_student,
    d.domain,
    c.presentation_year,
    c.presentation_start,
    c.presentation_length_days,
    s.gender,
    s.region,
    s.highest_education,
    s.imd_band,
    s.age_band,
    s.num_of_prev_attempts,
    s.studied_credits,
    s.disability,
    s.is_disabled,
    s.final_result,
    s.final_result in ('Pass', 'Distinction') as is_pass,
    s.final_result = 'Distinction' as is_distinction,
    s.final_result = 'Fail' as is_fail,
    s.final_result = 'Withdrawn' as is_withdrawn,
    r.registration_day,
    r.unregistration_day,
    case
        when r.registration_day is null then 'unknown'
        when r.registration_day < -30 then 'early'
        when r.registration_day <= 0 then 'on_time'
        else 'late'
    end as registration_cohort
from students as s
inner join registrations as r
    on
        s.code_module = r.code_module
        and s.code_presentation = r.code_presentation
        and s.id_student = r.id_student
inner join courses as c
    on
        s.code_module = c.code_module
        and s.code_presentation = c.code_presentation
left join domains as d
    on s.code_module = d.code_module
