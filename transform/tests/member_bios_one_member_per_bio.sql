-- A Congressional Directory biography describes one person, so it's on one
-- member's page at most. Two members sharing one means the matching in
-- member_bios gave a member someone else's biography.
select edition, printed_name, count(*) as members
from {{ ref('member_bios') }}
group by edition, printed_name
having count(*) > 1
