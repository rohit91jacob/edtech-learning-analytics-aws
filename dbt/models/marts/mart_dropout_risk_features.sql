-- Withdrawal-risk feature table: one row per enrolment still registered at the cut-off day,
-- with features that are observable by then, the eventual label, and the train/test split.
--
-- Leakage guards:
--   * clickstream features use whole course weeks strictly before the cut-off week;
--   * assessment features use submissions made before the cut-off day;
--   * enrolments that unregistered before the cut-off are excluded (their outcome is known);
--   * final_result is only used for the label.
{% set cutoff_day = var('risk_cutoff_day') | int %}
{% set cutoff_week = (cutoff_day // 7) | int %}

with enrolments as (
    select * from {{ ref('int_enrolments') }}
    where unregistration_day is null or unregistration_day >= {{ cutoff_day }}
),

weekly as (
    select * from {{ ref('stg_oulad__student_weekly_engagement') }}
    where course_week < {{ cutoff_week }}
),

clicks as (
    select
        code_module,
        code_presentation,
        id_student,
        sum(case when course_week < 0 then clicks else 0 end) as clicks_pre_start,
        sum(case when course_week >= 0 then clicks else 0 end) as clicks_to_cutoff,
        sum(case when course_week >= 0 then active_days else 0 end) as active_days_to_cutoff,
        {{ count_if('course_week >= 0') }} as active_weeks_to_cutoff,
        sum(case when course_week = {{ cutoff_week - 1 }} then clicks else 0 end) as clicks_last_week,
        max(last_day) as last_active_day
    from weekly
    group by code_module, code_presentation, id_student
),

activity_types as (
    select
        code_module,
        code_presentation,
        id_student,
        count(distinct activity_type) as activity_types_to_cutoff,
        sum(case when activity_type = 'forumng' then clicks else 0 end) as forum_clicks_to_cutoff,
        sum(case when activity_type in ('quiz', 'externalquiz') then clicks else 0 end) as quiz_clicks_to_cutoff
    from {{ ref('stg_oulad__student_weekly_activity') }}
    where course_week < {{ cutoff_week }}
    group by code_module, code_presentation, id_student
),

due as (
    select
        code_module,
        code_presentation,
        count(*) as assessments_due_by_cutoff
    from {{ ref('stg_oulad__assessments') }}
    where not is_exam and cutoff_day < {{ cutoff_day }}
    group by code_module, code_presentation
),

submissions as (
    select
        code_module,
        code_presentation,
        id_student,
        count(*) as submitted_by_cutoff,
        {{ count_if('is_on_time') }} as on_time_by_cutoff,
        avg(score) as avg_score_by_cutoff
    from {{ ref('int_assessment_submissions') }}
    where not is_banked and submitted_day < {{ cutoff_day }}
    group by code_module, code_presentation, id_student
)

select
    e.code_module,
    e.code_presentation,
    e.presentation_key,
    e.id_student,
    case when e.code_presentation = '{{ var("holdout_presentation") }}' then 'test' else 'train' end as split,
    -- demographics and history (sensitive attributes are kept for fairness slicing)
    e.domain,
    e.gender,
    e.age_band,
    e.imd_band,
    e.disability,
    e.highest_education,
    e.region,
    e.num_of_prev_attempts,
    e.studied_credits,
    -coalesce(e.registration_day, 0) as registration_lead_days,
    e.registration_day is null as registration_day_missing,
    -- clickstream
    coalesce(c.clicks_pre_start, 0) as clicks_pre_start,
    coalesce(c.clicks_to_cutoff, 0) as clicks_to_cutoff,
    coalesce(c.active_days_to_cutoff, 0) as active_days_to_cutoff,
    coalesce(c.active_weeks_to_cutoff, 0) as active_weeks_to_cutoff,
    coalesce(c.clicks_last_week, 0) as clicks_last_week,
    coalesce(t.activity_types_to_cutoff, 0) as activity_types_to_cutoff,
    coalesce(t.forum_clicks_to_cutoff, 0) as forum_clicks_to_cutoff,
    coalesce(t.quiz_clicks_to_cutoff, 0) as quiz_clicks_to_cutoff,
    case
        when c.last_active_day is null then {{ cutoff_day + 30 }}
        else {{ cutoff_day }} - c.last_active_day
    end as days_since_last_activity,
    c.last_active_day is null as no_activity_before_cutoff,
    -- assessments
    coalesce(d.assessments_due_by_cutoff, 0) as assessments_due_by_cutoff,
    coalesce(s.submitted_by_cutoff, 0) as submitted_by_cutoff,
    coalesce(s.on_time_by_cutoff, 0) as on_time_by_cutoff,
    coalesce(s.avg_score_by_cutoff, 0) as avg_score_by_cutoff,
    s.avg_score_by_cutoff is null as no_score_before_cutoff,
    greatest(coalesce(d.assessments_due_by_cutoff, 0) - coalesce(s.on_time_by_cutoff, 0), 0) as missed_by_cutoff,
    -- label (outcome at the end of the presentation)
    e.final_result,
    e.is_withdrawn as label_withdrawn
from enrolments as e
left join clicks as c
    on
        e.code_module = c.code_module
        and e.code_presentation = c.code_presentation
        and e.id_student = c.id_student
left join activity_types as t
    on
        e.code_module = t.code_module
        and e.code_presentation = t.code_presentation
        and e.id_student = t.id_student
left join due as d
    on e.code_module = d.code_module and e.code_presentation = d.code_presentation
left join submissions as s
    on
        e.code_module = s.code_module
        and e.code_presentation = s.code_presentation
        and e.id_student = s.id_student
