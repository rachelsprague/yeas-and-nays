with source as (
    select * from {{ source('staged', 'house_votes') }}
),

typed as (
    select
        cast(congress as integer) as congress,
        cast(regexp_extract(session, '^(\d+)', 1) as integer) as session,
        cast(rollcall_num as integer) as roll_number,
        strptime(action_date, '%d-%b-%Y')::date as vote_date,
        strptime(action_date || ' ' || action_time_etz, '%d-%b-%Y %H:%M') as vote_time_et,
        vote_question as question,
        vote_type,
        vote_result as result,
        legis_num as measure_number,
        vote_desc as measure_title,
        amendment_num as amendment_number,
        amendment_author,
        cast(yea_total as integer) as yea_count,
        cast(nay_total as integer) as nay_count,
        cast(present_total as integer) as present_count,
        cast(not_voting_total as integer) as not_voting_count,
        source_file
    from source
)

select
    'h' || congress || '-' || session || '-' || lpad(roll_number::varchar, 4, '0') as vote_id,
    'house' as chamber,
    *,
    'https://clerk.house.gov/Votes/' || year(vote_date) || roll_number as source_url,
    'https://clerk.house.gov/evs/' || year(vote_date) || '/roll' || lpad(roll_number::varchar, 3, '0') || '.xml' as xml_url
from typed
