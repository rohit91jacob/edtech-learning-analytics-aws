select
    code_module,
    code_presentation,
    code_module || '_' || code_presentation as presentation_key,
    cast(module_presentation_length as integer) as presentation_length_days,
    cast(presentation_year as integer) as presentation_year,
    cast(presentation_start_month as integer) as presentation_start_month,
    case when code_presentation like '%B' then 'February' else 'October' end as presentation_start
from {{ source('oulad_silver', 'courses') }}
