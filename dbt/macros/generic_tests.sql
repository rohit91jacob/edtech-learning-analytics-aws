{# Generic tests kept in-repo so the project needs no dbt packages (dbt deps) to build. #}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{% test value_between(model, column_name, min_value=none, max_value=none) %}
select {{ column_name }}
from {{ model }}
where
    {% if min_value is not none %}{{ column_name }} < {{ min_value }}{% else %}false{% endif %}
    {% if max_value is not none %}or {{ column_name }} > {{ max_value }}{% endif %}
{% endtest %}
