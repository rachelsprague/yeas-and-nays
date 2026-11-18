{{ config(severity='warn') }}
-- Members in office now, and when the newest Congressional Directory was
-- issued, with no biography, though the directory prints one for their seat: a
-- name the matching in member_bios missed, or a directory format the parser no
-- longer reads. Members who took office later (a special election, say) have
-- none until the next edition. Warns, because bios are secondary to votes.
select members.bioguide_id, members.member_label
from {{ ref('members') }} as members
where members.is_current
  and members.bioguide_id not in (select bioguide_id from {{ ref('member_bios') }})
  and exists (
      select 1
      from {{ ref('stg_directory__bios') }} as bios
      where bios.state = members.state
        and bios.chamber = members.chamber
        and bios.district is not distinct from members.district
        and members.served_from <= bios.date_issued
  )
