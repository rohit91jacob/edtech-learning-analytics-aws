-- Outcome rates by sensitive attribute: age band, IMD (deprivation) band and declared disability.
-- Grain: slice dimension x slice value, plus one 'overall' row. Gaps are percentage points versus
-- the overall rate. These are descriptive differences in outcomes, not evidence of bias in
-- teaching or marking: the bands are coarse (generalised by the release's k-anonymity step) and
-- confounded with each other and with module choice and study load.
with enrolments as (
    select * from {{ ref('int_enrolments') }}
),

scores as (
    select
        code_module,
        code_presentation,
        id_student,
        avg(score) as avg_score
    from {{ ref('int_assessment_submissions') }}
    where not is_banked and not is_exam
    group by code_module, code_presentation, id_student
),

base as (
    select
        e.*,
        s.avg_score
    from enrolments as e
    left join scores as s
        on
            e.code_module = s.code_module
            and e.code_presentation = s.code_presentation
            and e.id_student = s.id_student
),

slices as (
    select 'overall' as slice_dimension, 'all' as slice_value, base.* from base
    union all
    select 'age_band' as slice_dimension, age_band as slice_value, base.* from base
    union all
    select 'imd_band' as slice_dimension, imd_band as slice_value, base.* from base
    union all
    select 'disability' as slice_dimension, disability as slice_value, base.* from base
),

aggregated as (
    select
        slice_dimension,
        slice_value,
        count(*) as n_enrolments,
        {{ safe_divide(count_if('is_pass'), 'count(*)') }} as pass_rate,
        {{ safe_divide(count_if('is_distinction'), 'count(*)') }} as distinction_rate,
        {{ safe_divide(count_if('is_fail'), 'count(*)') }} as fail_rate,
        {{ safe_divide(count_if('is_withdrawn'), 'count(*)') }} as withdrawal_rate,
        avg(avg_score) as avg_assessment_score
    from slices
    group by slice_dimension, slice_value
),

overall as (
    select * from aggregated where slice_dimension = 'overall'
)

select
    a.slice_dimension,
    a.slice_value,
    a.n_enrolments,
    {{ safe_divide('a.n_enrolments', 'o.n_enrolments') }} as share_of_enrolments,
    a.pass_rate,
    a.distinction_rate,
    a.fail_rate,
    a.withdrawal_rate,
    a.avg_assessment_score,
    (a.pass_rate - o.pass_rate) * 100 as pass_rate_gap_pp,
    (a.withdrawal_rate - o.withdrawal_rate) * 100 as withdrawal_rate_gap_pp,
    a.n_enrolments < {{ var('min_slice_size') }} as small_sample
from aggregated as a
cross join overall as o
