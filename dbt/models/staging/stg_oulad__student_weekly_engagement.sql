select
    code_module,
    code_presentation,
    cast(id_student as integer) as id_student,
    cast(course_week as integer) as course_week,
    cast(clicks as bigint) as clicks,
    cast(active_days as integer) as active_days,
    cast(distinct_sites as integer) as distinct_sites,
    cast(distinct_activity_types as integer) as distinct_activity_types,
    cast(first_day as integer) as first_day,
    cast(last_day as integer) as last_day
from {{ source('oulad_silver', 'student_weekly_engagement') }}
