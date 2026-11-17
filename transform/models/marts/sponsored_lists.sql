{#-
  One row per member per Congress whose sponsored list has been fetched. A fetch that fails
  leaves no list, so a member missing here hasn't been fetched yet (the site
  leaves out their sponsored section), while one here with bill_count 0
  introduced nothing in that Congress.
-#}

select bioguide_id, congress, bill_count
from {{ ref('stg_congress_gov__sponsored_lists') }}
