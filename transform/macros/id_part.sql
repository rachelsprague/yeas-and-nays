{#-
  A value as part of an ID: lower case, each run of anything but letters and
  digits as one hyphen, none at either end, e.g. 'S.Amdt. 6883' -> 's-amdt-6883'.
-#}
{% macro id_part(column) -%}
    trim(regexp_replace(lower({{ column }}), '[^a-z0-9]+', '-', 'g'), '-')
{%- endmacro %}
