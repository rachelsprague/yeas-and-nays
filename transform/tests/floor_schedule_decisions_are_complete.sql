-- A decision without a roll call has its date, question and outcome, or none of
-- them, and only when there's no roll call. It warns, like the schedule's other
-- tests: the schedule is secondary to votes.
{{ config(severity='warn') }}

select *
from {{ ref('floor_schedule') }}
where (decided_date is null) != (decided_outcome is null)
    or (decided_question is null) != (decided_outcome is null)
    or (decided_outcome is not null and vote_id is not null)
