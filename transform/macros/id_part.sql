{#-
  A value as part of an ID: lower case, each run of anything but letters and
  digits as one hyphen, none at either end, e.g. 'S.Amdt. 6883' -> 's-amdt-6883'.
  Null if nothing is left (e.g. '--'), so concat_ws('-', ...) skips it rather
  than leaving a bare hyphen. Values the source formats two ways ('H.R. 4',
  'H.R.4') give the same part.
-#}
{% macro id_part(column) -%}
    nullif(trim(regexp_replace(lower({{ column }}), '[^a-z0-9]+', '-', 'g'), '-'), '')
{%- endmacro %}
