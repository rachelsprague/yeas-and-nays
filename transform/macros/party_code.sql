{#- Party name as written in congress-legislators -> one-letter code used in vote records. -#}
{% macro party_code(column) -%}
    case {{ column }}
        when 'Republican' then 'R'
        when 'Democrat' then 'D'
        when 'Independent' then 'I'
        when 'Libertarian' then 'L'
        else {{ column }}
    end
{%- endmacro %}
