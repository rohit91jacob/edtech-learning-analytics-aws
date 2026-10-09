select
    cast(id_assessment as integer) as id_assessment,
    code_module,
    code_presentation,
    assessment_type,
    -- Cut-off day relative to the presentation start. Missing for 11 exams: per the data
    -- descriptor those take place in the last week of the presentation.
    cast(date as integer) as cutoff_day,
    cast(weight as double) as weight_pct,
    assessment_type = 'Exam' as is_exam
from {{ source('oulad_silver', 'assessments') }}
