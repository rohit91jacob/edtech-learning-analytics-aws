-- Every assessment funnel narrows: enrolled >= submitted >= passed >= mastered.
select id_assessment, enrolled, submitted, passed, mastered
from {{ ref('mart_assessment_mastery_funnel') }}
where not (enrolled >= submitted and submitted >= passed and passed >= mastered)
