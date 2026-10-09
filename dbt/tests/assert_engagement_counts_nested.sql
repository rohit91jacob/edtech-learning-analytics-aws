-- Active students can never exceed enrolled; still-registered can never exceed enrolled.
select presentation_key, cohort_dimension, cohort_value, course_week
from {{ ref('mart_engagement_weekly_cohorts') }}
where active_students > enrolled or still_registered > enrolled
