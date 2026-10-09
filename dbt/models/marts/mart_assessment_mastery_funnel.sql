-- Mastery funnel per assessment: enrolled -> submitted -> passed (score >= pass mark) ->
-- mastered (score >= mastery threshold). Banked results (carried over from an earlier
-- presentation) are counted separately and excluded from the funnel.
{% set registered_at_cutoff = 'e.unregistration_day is null or e.unregistration_day > coalesce(a.cutoff_day, e.presentation_length_days)' %}

with assessments as (
    select
        *,
        row_number() over (
            partition by code_module, code_presentation
            order by coalesce(cutoff_day, 100000), id_assessment
        ) as assessment_seq
    from {{ ref('stg_oulad__assessments') }}
),

enrolments as (
    select
        code_module,
        code_presentation,
        count(*) as enrolled
    from {{ ref('int_enrolments') }}
    group by code_module, code_presentation
),

registered as (
    select
        a.id_assessment,
        {{ count_if(registered_at_cutoff) }} as registered_at_cutoff
    from assessments as a
    inner join {{ ref('int_enrolments') }} as e
        on a.code_module = e.code_module and a.code_presentation = e.code_presentation
    group by a.id_assessment
),

results as (
    select
        id_assessment,
        {{ count_if('not is_banked') }} as submitted,
        {{ count_if('not is_banked and is_on_time') }} as submitted_on_time,
        {{ count_if('not is_banked and is_passed') }} as passed,
        {{ count_if('not is_banked and is_mastered') }} as mastered,
        {{ count_if('is_banked') }} as banked,
        avg(case when not is_banked then score end) as avg_score,
        {{ percentile('case when not is_banked then score end', 0.5) }} as median_score
    from {{ ref('int_assessment_submissions') }}
    group by id_assessment
)

select
    a.code_module,
    a.code_presentation,
    a.code_module || '_' || a.code_presentation as presentation_key,
    a.id_assessment,
    a.assessment_seq,
    a.assessment_type,
    a.cutoff_day,
    a.weight_pct,
    -- Zero-weight TMAs/CMAs are formative (all of GGG's; FFF's 0% CMAs; BBB 2014J's first TMA).
    a.weight_pct = 0 and not a.is_exam as is_formative,
    e.enrolled,
    coalesce(g.registered_at_cutoff, 0) as registered_at_cutoff,
    coalesce(r.submitted, 0) as submitted,
    coalesce(r.submitted_on_time, 0) as submitted_on_time,
    coalesce(r.passed, 0) as passed,
    coalesce(r.mastered, 0) as mastered,
    coalesce(r.banked, 0) as banked,
    {{ safe_divide('coalesce(r.submitted, 0)', 'e.enrolled') }} as submission_rate,
    {{ safe_divide('coalesce(r.submitted, 0)', 'g.registered_at_cutoff') }} as submission_rate_of_registered,
    {{ safe_divide('r.passed', 'r.submitted') }} as pass_rate_of_submitted,
    {{ safe_divide('r.mastered', 'r.submitted') }} as mastery_rate_of_submitted,
    {{ safe_divide('coalesce(r.mastered, 0)', 'e.enrolled') }} as mastery_rate_of_enrolled,
    r.avg_score,
    r.median_score,
    coalesce(r.submitted, 0) > 0 as has_results
from assessments as a
inner join enrolments as e
    on a.code_module = e.code_module and a.code_presentation = e.code_presentation
left join registered as g on a.id_assessment = g.id_assessment
left join results as r on a.id_assessment = r.id_assessment
