-- Sanity check on positions per vote: 435 House seats plus up to 6 delegates
-- (who vote in the Committee of the Whole) / 100 Senate seats, minus
-- vacancies. A count outside this range likely means a parse problem.
{{ config(severity='warn') }}

select vote_id, chamber, member_count
from {{ ref('votes') }}
where (chamber = 'house' and member_count not between 420 and 441)
   or (chamber = 'senate' and member_count not between 95 and 100)
