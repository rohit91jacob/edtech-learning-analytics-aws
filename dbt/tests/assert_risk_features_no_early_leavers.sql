-- No enrolment that had already unregistered before the cut-off day may enter the risk table.
select f.presentation_key, f.id_student
from {{ ref('mart_dropout_risk_features') }} as f
inner join {{ ref('int_enrolments') }} as e
    on f.presentation_key = e.presentation_key and f.id_student = e.id_student
where e.unregistration_day < {{ var('risk_cutoff_day') }}
