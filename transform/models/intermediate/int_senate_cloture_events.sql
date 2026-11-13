{#-
  Cloture motions filed and voted on, from the status lines of the Senate's
  daily floor activity. One row per event, e.g.

    "Cloture motion on the measure presented in Senate."                  filed
    "Cloture on the measure, as amended, invoked in Senate by Yea-Nay…"   voted
    "Cloture motion presented in Senate."  (on a nomination)              filed

  `target` is what cloture is on: "the measure", "the motion to proceed to the
  measure", "amendment SA 6883", or '' for the document itself (nominations).
-#}

with actions as (
    select * from {{ ref('stg_floor__senate_actions') }}
),

events as (
    select
        *,
        case
            when regexp_matches(status_text, '^Cloture motion( on .+?)? presented in Senate') then 'filed'
            when regexp_matches(status_text, '^Cloture( on .+?)? (not )?invoked in Senate') then 'voted'
            when regexp_matches(status_text, '^Cloture motion( on .+?)? withdrawn') then 'withdrawn'
        end as event,
        regexp_replace(
            regexp_extract(status_text, '^Cloture(?: motion)? on (.+?) (?:presented|not invoked|invoked|withdrawn)', 1),
            ', as amended,?$', ''
        ) as target
    from actions
)

select
    activity_date,
    status_order,
    docnum,
    document_prefix,
    bill_type,
    bill_number,
    amends,
    document_title,
    target,
    event,
    status_text
from events
where event is not null
