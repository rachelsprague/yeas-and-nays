{#-
  Map a position as recorded (House: Aye/No or Yea/Nay; Senate: Yea/Nay;
  impeachment trials: Guilty/Not Guilty) to yes / no / present / not_voting.
  Anything else, such as a candidate's name in an Election of the Speaker,
  becomes 'other'. A singular test checks 'other' only appears on those votes.
-#}
{% macro normalize_position(column) -%}
    case
        when {{ column }} in ('Yea', 'Aye', 'Guilty') then 'yes'
        when {{ column }} in ('Nay', 'No', 'Not Guilty') then 'no'
        when {{ column }} like 'Present%' then 'present'
        when {{ column }} = 'Not Voting' then 'not_voting'
        else 'other'
    end
{%- endmacro %}
