-- Which VLE activity types go with passing? Grain: module x activity type.
--
-- Population: enrolments that stayed to the end (final_result <> 'Withdrawn'), so every row has a
-- pass/fail outcome and usage is not just a proxy for how long someone stayed registered.
-- This is an observational association, not a causal effect: motivated students use more of
-- everything. Read pass_rate_lift as "users vs non-users", never as "using X raises pass rates".
with completers as (
    select * from {{ ref('int_enrolments') }}
    where not is_withdrawn
),

usage as (
    select
        code_module,
        code_presentation,
        id_student,
        activity_type,
        sum(clicks) as clicks,
        sum(active_days) as active_days
    from {{ ref('stg_oulad__student_weekly_activity') }}
    group by code_module, code_presentation, id_student, activity_type
),

types_offered as (
    select
        code_module,
        activity_type,
        count(distinct id_site) as n_sites,
        count(distinct code_presentation) as n_presentations_offered
    from {{ ref('stg_oulad__vle_sites') }}
    group by code_module, activity_type
),

module_size as (
    select
        code_module,
        count(*) as n_completers,
        {{ count_if('is_pass') }} as n_pass
    from completers
    group by code_module
),

users as (
    select
        c.code_module,
        u.activity_type,
        count(*) as n_users,
        {{ count_if('c.is_pass') }} as n_users_pass,
        sum(u.clicks) as user_clicks,
        {{ percentile('u.clicks', 0.5) }} as median_clicks_per_user,
        avg(case when c.is_pass then u.clicks end) as avg_clicks_passers,
        avg(case when not c.is_pass then u.clicks end) as avg_clicks_non_passers
    from completers as c
    inner join usage as u
        on
            c.code_module = u.code_module
            and c.code_presentation = u.code_presentation
            and c.id_student = u.id_student
    group by c.code_module, u.activity_type
),

-- Only completers whose presentation offered the activity type count as potential users.
offered_population as (
    select
        c.code_module,
        s.activity_type,
        count(distinct c.code_presentation || '|' || cast(c.id_student as varchar)) as n_offered,
        count(distinct case when c.is_pass then c.code_presentation || '|' || cast(c.id_student as varchar) end) as n_offered_pass
    from completers as c
    inner join (
        select distinct code_module, code_presentation, activity_type
        from {{ ref('stg_oulad__vle_sites') }}
    ) as s
        on c.code_module = s.code_module and c.code_presentation = s.code_presentation
    group by c.code_module, s.activity_type
)

select
    t.code_module,
    t.activity_type,
    t.n_sites,
    t.n_presentations_offered,
    m.n_completers,
    coalesce(p.n_offered, 0) as n_offered,
    coalesce(u.n_users, 0) as n_users,
    {{ safe_divide('coalesce(u.n_users, 0)', 'p.n_offered') }} as usage_rate,
    u.median_clicks_per_user,
    {{ safe_divide('u.n_users_pass', 'u.n_users') }} as pass_rate_users,
    {{ safe_divide('p.n_offered_pass - coalesce(u.n_users_pass, 0)', 'p.n_offered - coalesce(u.n_users, 0)') }} as pass_rate_non_users,
    {{ safe_divide('u.n_users_pass', 'u.n_users') }}
    - {{ safe_divide('p.n_offered_pass - coalesce(u.n_users_pass, 0)', 'p.n_offered - coalesce(u.n_users, 0)') }} as pass_rate_lift,
    u.avg_clicks_passers,
    u.avg_clicks_non_passers,
    {{ safe_divide('u.avg_clicks_passers', 'u.avg_clicks_non_passers') }} as clicks_ratio_passers_vs_non_passers,
    (p.n_offered - coalesce(u.n_users, 0)) < {{ var('min_slice_size') }}
    or coalesce(u.n_users, 0) < {{ var('min_slice_size') }} as small_sample
from types_offered as t
inner join module_size as m on t.code_module = m.code_module
left join offered_population as p
    on t.code_module = p.code_module and t.activity_type = p.activity_type
left join users as u
    on t.code_module = u.code_module and t.activity_type = u.activity_type
