with source as (
    select * from {{ source('staged', 'senate_votes') }}
),

typed as (
    select
        cast(congress as integer) as congress,
        cast(session as integer) as session,
        cast(vote_number as integer) as roll_number,
        strptime(vote_date, '%B %d, %Y, %I:%M %p') as vote_time_et,
        vote_question_text as question,
        vote_result as result,
        vote_result_text as result_text,
        majority_requirement,
        vote_title,
        document_type,
        document_name as measure_number,
        bill_type,
        bill_number,
        coalesce(document_title, vote_document_text) as measure_title,
        amendment_number,
        amendment_purpose,
        cast(yeas as integer) as yea_count,
        cast(nays as integer) as nay_count,
        -- Senate records leave <present/> and <absent/> empty when the count is zero.
        coalesce(cast(present as integer), 0) as present_count,
        coalesce(cast(absent as integer), 0) as not_voting_count,
        tie_breaker_by_whom as tie_breaker_by,
        tie_breaker_vote,
        source_file
    from source
)

select
    's' || congress || '-' || session || '-' || lpad(roll_number::varchar, 4, '0') as vote_id,
    'senate' as chamber,
    congress,
    session,
    roll_number,
    vote_time_et::date as vote_date,
    * exclude (congress, session, roll_number),
    'https://www.senate.gov/legislative/LIS/roll_call_votes/vote' || congress || session
        || '/vote_' || congress || '_' || session || '_' || lpad(roll_number::varchar, 5, '0') || '.htm' as source_url,
    'https://www.senate.gov/legislative/LIS/roll_call_votes/vote' || congress || session
        || '/vote_' || congress || '_' || session || '_' || lpad(roll_number::varchar, 5, '0') || '.xml' as xml_url
from typed
