{#-
  One row per member whose cosponsored list has been fetched. Lists fill in
  over several pipeline runs, so a member missing here hasn't been fetched yet
  (the site leaves out their cosponsored section), while one here with
  bill_count 0 cosponsored nothing this Congress.
-#}

select bioguide_id, congress, bill_count
from {{ ref('stg_congress_gov__cosponsored_lists') }}
