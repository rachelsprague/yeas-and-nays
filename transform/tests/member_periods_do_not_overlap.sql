-- A member can't be in two affiliation periods in the same chamber at once,
-- other than sharing a boundary day (one term ends the day the next begins).
select a.bioguide_id, a.chamber, a.period_start, a.period_end, b.period_start as other_start, b.period_end as other_end
from {{ ref('int_member_periods') }} as a
inner join {{ ref('int_member_periods') }} as b
    on a.bioguide_id = b.bioguide_id
    and a.chamber = b.chamber
    and a.period_start < b.period_start
    and b.period_start < a.period_end
where a.overlaps_congress and b.overlaps_congress
