-- floor_schedule drops a House item whose ID has no letters or digits (null,
-- or e.g. '--'), and a Senate cloture event whose docnum has none, since such
-- rows can't be told apart. This test is where they show, so a feed that stops
-- sending IDs is noticed. It reads only rows floor_schedule would otherwise
-- keep: rows dropped for another reason (removed, no week or date) aren't
-- counted, and a null Senate docnum is left to the not_null test on
-- stg_floor__senate_actions. It warns: the schedule is secondary to votes.
{{ config(severity='warn') }}

select 'stg_floor__house_items' as model, item_id as id, week_date as day
from {{ ref('stg_floor__house_items') }}
where removed_at_recorded is null
    and week_date is not null
    and {{ id_part('item_id') }} is null
union all
select 'int_senate_cloture_events', docnum, activity_date
from {{ ref('int_senate_cloture_events') }}
where activity_date is not null
    and status_order is not null
    and docnum is not null
    and {{ id_part('docnum') }} is null
