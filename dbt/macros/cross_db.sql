{# Small portability layer: the same models compile for DuckDB (local) and Athena/Trino (AWS). #}

{% macro safe_divide(numerator, denominator) -%}
    (cast({{ numerator }} as double) / nullif(cast({{ denominator }} as double), 0))
{%- endmacro %}

{% macro percentile(expression, fraction) -%}
    {{ return(adapter.dispatch('percentile', 'edtech')(expression, fraction)) }}
{%- endmacro %}

{% macro default__percentile(expression, fraction) -%}
    quantile_cont({{ expression }}, {{ fraction }})
{%- endmacro %}

{# Athena has no exact percentile aggregate; approx_percentile is a t-digest estimate. #}
{% macro athena__percentile(expression, fraction) -%}
    approx_percentile({{ expression }}, {{ fraction }})
{%- endmacro %}

{% macro count_if(condition) -%}
    sum(case when {{ condition }} then 1 else 0 end)
{%- endmacro %}
