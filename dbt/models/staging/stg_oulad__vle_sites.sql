select
    cast(id_site as integer) as id_site,
    code_module,
    code_presentation,
    activity_type,
    cast(week_from as integer) as planned_week_from,
    cast(week_to as integer) as planned_week_to
from {{ source('oulad_silver', 'vle_sites') }}
