-- question and outcome are set only when the line records a final decision on the
-- measure taken without a roll call: "On passage Passed by voice vote." Postponed
-- votes start "POSTPONED PROCEEDINGS", and don't match. Times are Eastern. try_
-- functions: a malformed value becomes null instead of failing the build.
{%- set decision -%}
    '^(On (?:motion (?:to|that the House) suspend the rules and .+|passage.*|agreeing to the (?:resolution|conference report).*)) ((?:Agreed to|Passed|Failed) (?:by voice vote|without objection))\.?$'
{%- endset %}

select
    try_cast(congress as integer) as congress,
    action_id,
    action_code,
    try_strptime(action_time, '%Y%m%dT%H:%M:%S') as action_time_et,
    measure_number,
    bill_type,
    bill_number,
    action_text,
    nullif(regexp_extract(action_text, {{ decision }}, 1, 'i'), '') as question,
    nullif(regexp_extract(action_text, {{ decision }}, 2, 'i'), '') as outcome,
    source_file
from {{ source('staged', 'house_floor_actions') }}
