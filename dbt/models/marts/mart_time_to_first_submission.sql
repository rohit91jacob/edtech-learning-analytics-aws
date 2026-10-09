-- Time to first submission per module presentation and final result.
select
    code_module,
    code_presentation,
    presentation_key,
    final_result,
    count(*) as n_enrolments,
    {{ count_if('has_submitted') }} as n_submitted,
    {{ safe_divide(count_if('not has_submitted'), 'count(*)') }} as pct_never_submitted,
    {{ safe_divide(count_if('submitted_by_first_cutoff'), 'count(*)') }} as pct_submitted_by_first_cutoff,
    min(first_cutoff_day) as first_cutoff_day,
    {{ percentile('first_submission_day', 0.25) }} as p25_first_submission_day,
    {{ percentile('first_submission_day', 0.5) }} as median_first_submission_day,
    {{ percentile('first_submission_day', 0.75) }} as p75_first_submission_day,
    {{ percentile('days_after_start_or_registration', 0.5) }} as median_days_after_start_or_registration
from {{ ref('fct_first_submission') }}
group by code_module, code_presentation, presentation_key, final_result
