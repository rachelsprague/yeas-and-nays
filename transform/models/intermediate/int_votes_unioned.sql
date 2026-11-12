{#- House and Senate votes in one shape. Chamber-specific fields are null for the other chamber. -#}

with house as (
    select
        vote_id, chamber, congress, session, roll_number, vote_date, vote_time_et,
        question, result,
        null::varchar as result_text,
        vote_type,
        null::varchar as majority_requirement,
        null::varchar as vote_title,
        measure_number, measure_title,
        amendment_number, amendment_author,
        null::varchar as amendment_purpose,
        yea_count, nay_count, present_count, not_voting_count,
        null::varchar as tie_breaker_by,
        null::varchar as tie_breaker_vote,
        source_url, xml_url
    from {{ ref('stg_house__votes') }}
),

senate as (
    select
        vote_id, chamber, congress, session, roll_number, vote_date, vote_time_et,
        question, result, result_text,
        null::varchar as vote_type,
        majority_requirement, vote_title,
        measure_number, measure_title,
        amendment_number,
        null::varchar as amendment_author,
        amendment_purpose,
        yea_count, nay_count, present_count, not_voting_count,
        tie_breaker_by, tie_breaker_vote,
        source_url, xml_url
    from {{ ref('stg_senate__votes') }}
)

select * from house
union all by name
select * from senate
