{#-
  The House's latest legislative day: when it convened and, once it has
  adjourned, when it next convenes. Staging can hold earlier days this week;
  files are named by date, so the last is the latest. If its day didn't parse
  it's dropped, not replaced by an earlier day.
-#}

with latest as (
    select * from {{ ref('stg_floor__house_floor_days') }}
    qualify row_number() over (order by source_file desc) = 1
)

select legislative_day, convene_time_et, adjourned, next_convene_time_et
from latest
where legislative_day is not null
