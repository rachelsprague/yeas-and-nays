{#-
  The House's latest legislative day: when it convened and, once it has
  adjourned, when it next convenes. A row whose day didn't parse is dropped.
-#}

select legislative_day, convene_time_et, adjourned, next_convene_time_et
from {{ ref('stg_floor__house_floor_days') }}
where legislative_day is not null
