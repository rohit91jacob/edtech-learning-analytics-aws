select
    code_module,
    code_presentation,
    cast(id_student as integer) as id_student,
    gender,
    region,
    highest_education,
    coalesce(imd_band, 'Unknown') as imd_band,
    age_band,
    cast(num_of_prev_attempts as integer) as num_of_prev_attempts,
    cast(studied_credits as integer) as studied_credits,
    disability,
    cast(is_disabled as boolean) as is_disabled,
    final_result
from {{ source('oulad_silver', 'students') }}
