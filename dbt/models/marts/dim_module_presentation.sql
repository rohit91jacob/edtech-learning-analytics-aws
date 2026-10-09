-- One row per module presentation with its size and outcome mix.
with courses as (
    select * from {{ ref('stg_oulad__courses') }}
),

enrolments as (
    select * from {{ ref('int_enrolments') }}
),

assessments as (
    select
        code_module,
        code_presentation,
        {{ count_if("assessment_type = 'TMA'") }} as n_tma,
        {{ count_if("assessment_type = 'CMA'") }} as n_cma,
        {{ count_if("assessment_type = 'Exam'") }} as n_exam
    from {{ ref('stg_oulad__assessments') }}
    group by code_module, code_presentation
),

outcomes as (
    select
        code_module,
        code_presentation,
        count(*) as n_enrolments,
        {{ count_if('is_pass') }} as n_pass,
        {{ count_if('is_withdrawn') }} as n_withdrawn,
        {{ count_if('is_fail') }} as n_fail
    from enrolments
    group by code_module, code_presentation
)

select
    c.presentation_key,
    c.code_module,
    c.code_presentation,
    d.domain,
    c.presentation_year,
    c.presentation_start,
    c.presentation_length_days,
    coalesce(o.n_enrolments, 0) as n_enrolments,
    coalesce(a.n_tma, 0) as n_tma,
    coalesce(a.n_cma, 0) as n_cma,
    coalesce(a.n_exam, 0) as n_exam,
    {{ safe_divide('o.n_pass', 'o.n_enrolments') }} as pass_rate,
    {{ safe_divide('o.n_fail', 'o.n_enrolments') }} as fail_rate,
    {{ safe_divide('o.n_withdrawn', 'o.n_enrolments') }} as withdrawal_rate
from courses as c
left join {{ ref('module_domains') }} as d on c.code_module = d.code_module
left join outcomes as o
    on c.code_module = o.code_module and c.code_presentation = o.code_presentation
left join assessments as a
    on c.code_module = a.code_module and c.code_presentation = a.code_presentation
