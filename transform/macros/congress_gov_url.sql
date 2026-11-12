{#-
  Congress.gov page for a bill or resolution, from its API bill type and
  number, e.g. ('hres', '1655') -> .../bill/119th-congress/house-resolution/1655.
  Null when there's no bill (nominations, quorum calls).
-#}
{% macro congress_gov_url(congress, bill_type, bill_number) -%}
    case when {{ bill_type }} is not null then
        'https://www.congress.gov/bill/' || {{ congress }} || 'th-congress/'
        || case {{ bill_type }}
            when 'hr' then 'house-bill'
            when 's' then 'senate-bill'
            when 'hres' then 'house-resolution'
            when 'sres' then 'senate-resolution'
            when 'hjres' then 'house-joint-resolution'
            when 'sjres' then 'senate-joint-resolution'
            when 'hconres' then 'house-concurrent-resolution'
            when 'sconres' then 'senate-concurrent-resolution'
        end
        || '/' || {{ bill_number }}
    end
{%- endmacro %}
