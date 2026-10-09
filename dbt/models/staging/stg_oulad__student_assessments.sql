select
    cast(id_assessment as integer) as id_assessment,
    cast(id_student as integer) as id_student,
    cast(date_submitted as integer) as submitted_day,
    cast(is_banked as boolean) as is_banked,
    cast(score as double) as score
from {{ source('oulad_silver', 'student_assessments') }}
