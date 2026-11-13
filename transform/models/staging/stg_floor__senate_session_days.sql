-- Times are recorded in Eastern time with an offset ("2026-11-16T15:00:00-05:00");
-- keep the Eastern wall-clock time, like the vote times elsewhere.
select
    cast(legislative_day as date) as legislative_day,
    strptime(left(convene_time, 19), '%Y-%m-%dT%H:%M:%S') as convene_time_et,
    strptime(left(adjourn_time, 19), '%Y-%m-%dT%H:%M:%S') as adjourn_time_et,
    strptime(left(next_convene_time, 19), '%Y-%m-%dT%H:%M:%S') as next_convene_time_et,
    source_file
from {{ source('staged', 'senate_session_days') }}
