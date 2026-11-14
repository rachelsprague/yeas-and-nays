{#-
  Official social media accounts as links. The source records account names,
  not URLs; a value that doesn't look like an account name gets no link.
  YouTube values are a legacy username, an @handle, or a channel ID, and
  youtube.com/{value} resolves for the first two.
-#}

with social as (
    select * from {{ source('staged', 'legislator_social_media') }}
)

select
    bioguide_id,
    case when regexp_full_match(twitter, '[A-Za-z0-9_]{1,15}')
        then 'https://x.com/' || twitter end as x_url,
    case when regexp_full_match(facebook, '[A-Za-z0-9.\-]+')
        then 'https://www.facebook.com/' || facebook end as facebook_url,
    case when regexp_full_match(instagram, '[A-Za-z0-9_.]+')
        then 'https://www.instagram.com/' || instagram end as instagram_url,
    case
        when regexp_full_match(youtube_id, 'UC[A-Za-z0-9_\-]{22}')
            then 'https://www.youtube.com/channel/' || youtube_id
        when regexp_full_match(youtube, 'UC[A-Za-z0-9_\-]{22}')
            then 'https://www.youtube.com/channel/' || youtube
        when regexp_full_match(youtube, '@?[A-Za-z0-9_.\-]+')
            then 'https://www.youtube.com/' || youtube
    end as youtube_url,
    -- @user@server -> https://server/@user
    case when regexp_full_match(mastodon, '@?[A-Za-z0-9_]+@[A-Za-z0-9.\-]+\.[A-Za-z]+')
        then 'https://' || lower(split_part(mastodon, '@', -1))
            || '/@' || split_part(ltrim(mastodon, '@'), '@', 1)
    end as mastodon_url
from social
