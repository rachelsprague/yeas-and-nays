{#-
  One row per bill or resolution per step it has reached on its path from
  introduction to law, with the first and last date of that step, for the
  vote page's path. From three sources:

  - bills: the introduced date (and the "Introduced in House" action, for a
    bill whose details aren't fetched yet).
  - Congress.gov actions recorded by the Library of Congress (source system
    9), whose action codes mark milestones (8000 passed in the House, 17000
    passed in the Senate, 28000 presented to the President, ...). Actions of
    type Committee are reports and discharges. Actions on resolving
    differences between the chambers come from any source.
  - This site's own roll calls: a passage vote that carried, a passage vote
    that failed, a vote on concurring in the other chamber's amendment or
    on a conference report, and a veto override vote. Congress.gov adds its
    milestone codes days after the action, so the votes fill that gap.
-#}

with actions as (
    select * from {{ ref('stg_congress_gov__bill_actions') }}
),

from_library_of_congress as (
    select
        congress, bill_type, bill_number, action_date,
        case
            when action_type = 'IntroReferral' and regexp_matches(action_text, '^(Introduced|Submitted) in (the )?(House|Senate)', 'i')
                then 'introduced'
            when action_type = 'Committee' then 'committee'
            when action_code = '8000' then 'passed_house'
            when action_code = '9000' then 'failed_house'
            when action_code = '17000' then 'passed_senate'
            when action_code = '18000' then 'failed_senate'
            when action_code = '28000' then 'presented'
            when action_code = '31000' then 'vetoed'
            when action_text ilike 'Pocket vetoed%' then 'pocket_vetoed'
            when regexp_matches(action_text, '^Passed (House|Senate) over veto', 'i')
                then 'override_passed_' || lower(regexp_extract(action_text, '(House|Senate)', 1))
            when regexp_matches(action_text, '^Failed of passage in (House|Senate) over veto', 'i')
                then 'override_failed_' || lower(regexp_extract(action_text, '(House|Senate)', 1))
            when action_code = '36000' or regexp_matches(action_text, '^Became (Public|Private) Law', 'i')
                then 'became_law'
        end as milestone
    from actions
    where source_system_code = '9'
),

from_resolving_differences as (
    select congress, bill_type, bill_number, action_date, 'differences' as milestone
    from actions
    where action_type = 'ResolvingDifferences' or action_text ilike 'Resolving differences%'
),

votes as (
    select vote_id, chamber, congress, bill_type, bill_number, vote_date, question, carried
    from {{ ref('votes') }}
    where bill_type is not null and carried is not null
),

from_votes as (
    select
        congress, bill_type, bill_number, vote_date as action_date,
        case
            when question like '%Objections of the President%'
                or regexp_matches(question, '^On (Overriding the Veto|the Veto Message)')
                then (case when carried then 'override_passed_' else 'override_failed_' end) || chamber
            when (chamber = 'house' and regexp_matches(question,
                    '^(On Passage|On Agreeing to the Resolution(, as Amended)?|On Motion to Suspend the Rules and (Pass|Agree)(, as Amended)?)$'))
                or (chamber = 'senate' and regexp_matches(question,
                    '^On (Passage of the Bill|the Joint Resolution|the Concurrent Resolution|the Resolution)\b'))
                then case
                    when carried then 'passed_' || chamber
                    -- A failed suspension vote can be followed by passage under a rule.
                    when question not like 'On Motion to Suspend%' then 'failed_' || chamber
                end
            when carried and (regexp_matches(question, '^On (the )?Motion to (Suspend the Rules and )?Concur')
                or regexp_matches(question, '^On (Agreeing to )?the Conference Report'))
                then 'differences'
        end as milestone
    from votes
),

introduced as (
    select congress, bill_type, bill_number, introduced_date as action_date, 'introduced' as milestone
    from {{ ref('bills') }}
    where introduced_date is not null
),

all_milestones as (
    select * from from_library_of_congress
    union all by name
    select * from from_resolving_differences
    union all by name
    select * from from_votes
    union all by name
    select * from introduced
)

select
    congress || '-' || bill_type || '-' || bill_number || ':' || milestone as milestone_id,
    congress || '-' || bill_type || '-' || bill_number as bill_id,
    congress,
    bill_type,
    bill_number,
    milestone,
    min(action_date) as first_date,
    max(action_date) as last_date
from all_milestones
where milestone is not null and action_date is not null
group by all
