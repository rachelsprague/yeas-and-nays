{#- Each time the Senate convened this session, and when it was set to convene next. -#}

select legislative_day, convene_time_et, adjourn_time_et, next_convene_time_et
from {{ ref('stg_floor__senate_session_days') }}
