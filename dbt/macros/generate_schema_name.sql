{#
  Locally (DuckDB) models land in plain schemas: staging, intermediate, marts.
  On Athena each schema is a Glue database, so it is prefixed with the target schema
  (edtech_dev_staging, edtech_dev_marts, ...) to stay unique inside the account.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.type == 'athena' -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
