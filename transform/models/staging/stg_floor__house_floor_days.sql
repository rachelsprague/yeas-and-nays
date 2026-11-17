-- Times are Eastern wall-clock times with no offset ("20261113T10:00:00",
-- "20261117T12:00"), kept as recorded like the vote times elsewhere. try_
-- functions: a malformed value becomes null instead of failing the build.
select
    cast(try_strptime(legislative_day, '%Y%m%d') as date) as legislative_day,
    try_strptime(convene_time, '%Y%m%dT%H:%M:%S') as convene_time_et,
    coalesce(finished = 'Yes', false) as adjourned,
    try_strptime(next_convene_time, '%Y%m%dT%H:%M') as next_convene_time_et,
    source_file
from {{ source('staged', 'house_floor_days') }}
