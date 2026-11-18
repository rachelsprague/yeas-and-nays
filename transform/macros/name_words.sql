{#-
  A name as capital-letter words with a space at each end, accents and
  punctuation dropped, so one name can be found inside another as whole words:
  'Kamlager-Dove' -> ' KAMLAGER DOVE ', 'LINDA T. SÁNCHEZ' -> ' LINDA T SANCHEZ '.
-#}
{% macro name_words(expr) -%}
    (' ' || trim(regexp_replace(upper(strip_accents({{ expr }})), '[^A-Z]+', ' ', 'g')) || ' ')
{%- endmacro %}
