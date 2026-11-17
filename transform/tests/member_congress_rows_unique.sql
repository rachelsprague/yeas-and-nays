-- Grain of the per-Congress member models: one row per member per Congress.
-- A re-elected member has a list and stats for each Congress they served in.
{% for model in ['member_stats', 'member_congresses', 'sponsored_lists', 'cosponsored_lists'] %}
select '{{ model }}' as model, bioguide_id, congress, count(*) as n
from {{ ref(model) }}
group by bioguide_id, congress
having count(*) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
