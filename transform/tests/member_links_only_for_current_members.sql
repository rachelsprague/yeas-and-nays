-- Former members' records keep office links that no longer work; the members mart leaves them out.
select bioguide_id
from {{ ref('members') }}
where not is_current
    and coalesce(
        website_url, contact_form_url, phone, office,
        x_url, facebook_url, instagram_url, youtube_url, mastodon_url
    ) is not null
