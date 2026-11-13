{#-
  What may come up for a vote, one row per item, from each chamber's own
  floor records. Neither is a promise: items are often moved or dropped.

  House: the measures on the Majority Leader's weekly floor schedule (this
  week and next, when published), grouped by the procedure they're listed
  under. Items removed from the schedule are left out.

  Senate: cloture motions filed and not yet voted on, from the daily floor
  activity. Under Senate Rule XXII a filed cloture motion is voted on after
  an intervening day unless the Senate agrees otherwise.

  vote_id links an item to the roll call that followed: for the House, the
  first roll call on the measure in its scheduled week; for the Senate, the
  first cloture roll call on it after the motion was filed (it can appear
  before the day's floor activity is posted).
-#}

with house_items as (
    select * from {{ ref('stg_floor__house_items') }}
    where removed_at is null
),

votes as (
    select * from {{ ref('int_votes_unioned') }}
),

house as (
    select
        'house' as chamber,
        'h-' || strftime(items.week_date, '%Y-%m-%d') || '-' || items.item_id as item_id,
        items.week_date,
        null::date as filed_date,
        items.category,
        items.category_order,
        items.item_order,
        null::varchar as question,
        trim(items.measure_number) as measure_number,
        items.bill_type,
        items.bill_number,
        items.title,
        null::varchar as amends,
        {{ congress_gov_url('items.congress', 'items.bill_type', 'items.bill_number') }} as congress_gov_url,
        votes.vote_id,
        votes.vote_date
    from house_items as items
    left join votes
        on votes.chamber = 'house'
        and votes.congress = items.congress
        and votes.bill_type = items.bill_type
        and votes.bill_number = items.bill_number
        and votes.vote_date between items.week_date and items.week_date + 6
    qualify row_number() over (partition by items.week_date, items.item_id order by votes.vote_time_et, votes.vote_id) = 1
),

-- The latest cloture event for each document and target; still pending if it's the filing.
latest_cloture as (
    select * from {{ ref('int_senate_cloture_events') }}
    qualify row_number() over (partition by docnum, target order by activity_date desc, status_order desc) = 1
),

filed as (
    select
        *,
        -- The question as the Senate records it on the roll call.
        case
            when target = 'the motion to proceed to the measure' then 'On Cloture on the Motion to Proceed'
            else 'On the Cloture Motion'
        end as question
    from latest_cloture
    where event = 'filed'
),

senate as (
    select
        'senate' as chamber,
        's-' || filed.docnum || case filed.target
            when 'the motion to proceed to the measure' then '-proceed'
            when 'the measure' then '-measure'
            else ''
        end as item_id,
        null::date as week_date,
        filed.activity_date as filed_date,
        null::varchar as category,
        null::integer as category_order,
        null::integer as item_order,
        filed.question,
        filed.docnum as measure_number,
        filed.bill_type,
        filed.bill_number,
        filed.document_title as title,
        filed.amends,
        {{ congress_gov_url(var('congress'), 'filed.bill_type', 'filed.bill_number') }} as congress_gov_url,
        votes.vote_id,
        votes.vote_date
    from filed
    left join votes
        on votes.chamber = 'senate'
        and votes.question ilike '%cloture%'
        and votes.vote_date >= filed.activity_date
        and case
            when filed.document_prefix = 'SA' then votes.amendment_number = filed.docnum
            when filed.target = 'the motion to proceed to the measure'
                then votes.measure_number = filed.docnum and votes.question ilike '%motion to proceed%'
            else votes.measure_number = filed.docnum
                and votes.amendment_number is null
                and votes.question not ilike '%motion to proceed%'
        end
    qualify row_number() over (partition by filed.docnum, filed.target order by votes.vote_time_et, votes.vote_id) = 1
)

select * from house
union all by name
select * from senate
