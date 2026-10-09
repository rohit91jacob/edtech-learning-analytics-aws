select
    code_module,
    code_presentation,
    cast(id_student as integer) as id_student,
    cast(date_registration as integer) as registration_day,
    cast(date_unregistration as integer) as unregistration_day
from {{ source('oulad_silver', 'registrations') }}
