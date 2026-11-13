{#-
  Each time the Senate convened this session, and when it was set to convene
  next. A malformed row (null after try_strptime) is dropped, so it can't
  become the "latest" session and hide the next convene time.
-#}

select legislative_day, convene_time_et, adjourn_time_et, next_convene_time_et
from {{ ref('stg_floor__senate_session_days') }}
where convene_time_et is not null
