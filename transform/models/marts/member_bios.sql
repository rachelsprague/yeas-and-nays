{#-
  One row per member with a biography in the newest Congressional Directory.
  The directory has no bioguide IDs, so a biography is matched to a member of
  the same chamber and state whose last name is in the printed name, as whole
  words, accents and punctuation aside ("Sánchez" matches "LINDA T. SÁNCHEZ").
  When a member matches more than one biography, or a biography more than one
  member (two members of a state's delegation with one last name), only a match
  on the member's own seat counts: district for the House, the state for the
  Senate. Matching by name rather than seat alone keeps a biography off a
  member who took the seat after the edition went to print, and keeps a
  continuing member's biography when redistricting moves them to a new
  district. A member with two matches on their own seat gets none. Members who
  joined after the edition, or left before it, have none
  (tests/members_without_bios.sql lists those in office when it was issued).
-#}

with bios as (
    select * from {{ ref('stg_directory__bios') }}
),

members as (
    select * from {{ ref('members') }}
),

matches as (
    select
        members.bioguide_id,
        bios.*,
        bios.district is not distinct from members.district as same_seat
    from members
    inner join bios
        on bios.state = members.state
        and bios.chamber = members.chamber
        and (
            contains({{ name_words('bios.printed_name') }}, {{ name_words('members.last_name') }})
            -- On the member's own seat, the first word of the last name will do: the 2026
            -- edition prints Hernández Rivera (D-PR) as "PABLO JOSE HERNANDEZ".
            or (
                bios.district is not distinct from members.district
                and contains({{ name_words('bios.printed_name') }},
                             ' ' || split_part(trim({{ name_words('members.last_name') }}), ' ', 1) || ' ')
            )
        )
),

counted as (
    select
        *,
        count(*) over (partition by bioguide_id) as bios_for_member,
        count(*) over (partition by state, chamber, district, printed_name) as members_for_bio
    from matches
)

select
    bioguide_id,
    edition,
    date_issued,
    printed_name,
    opening,
    education,
    professional_history,
    military_service
from counted
where same_seat or (bios_for_member = 1 and members_for_bio = 1)
qualify count(*) over (partition by bioguide_id) = 1
