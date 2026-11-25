# Loads the pipeline's JSON (data/out/) and generates a page per vote and per
# member. All counts and definitions come from the pipeline; this file only
# joins and arranges them for display.
#
#   site.data["meta"]      data/out/meta.json
#   site.data["votes"]     data/out/votes.json, newest first, each with a url
#   site.data["members"]   data/out/members.json, sorted by name, each with a url
#   site.data["leads"]     the newest vote overall and per chamber, prepared for display
#   site.data["vote_volume"]  roll calls per week by chamber and kind of vote (Yan.vote_volume)
#   site.data["policy_volume"]  roll calls by policy area, chamber and kind of vote (Yan.policy_volume)
#   site.data["district_map"]  site/_maps/{congress}.json with each district's member (Yan.district_map)
#   site.data["zip_lookup"]  the URL of that map's ZIP code lookup, or nil when there's none
#   site.data["home"]      the home page's modules: week, closest, against, areas
#
# Routes: /votes/{congress}/{chamber}/{session}/{roll}/ (roll numbers restart
# each session) and /members/{bioguide_id}/.

require "date"
require "json"

module Yan
  PARTY_NAMES = { "D" => "Democrat", "I" => "Independent", "R" => "Republican" }.freeze
  PARTIES = PARTY_NAMES.keys.freeze # alphabetical: the one ordering rule
  CHAMBER_NAMES = { "house" => "House", "senate" => "Senate" }.freeze
  STATE_NAMES = {
    "AK" => "Alaska", "AL" => "Alabama", "AR" => "Arkansas", "AS" => "American Samoa", "AZ" => "Arizona",
    "CA" => "California", "CO" => "Colorado", "CT" => "Connecticut", "DC" => "District of Columbia",
    "DE" => "Delaware", "FL" => "Florida", "GA" => "Georgia", "GU" => "Guam", "HI" => "Hawaii", "IA" => "Iowa",
    "ID" => "Idaho", "IL" => "Illinois", "IN" => "Indiana", "KS" => "Kansas", "KY" => "Kentucky",
    "LA" => "Louisiana", "MA" => "Massachusetts", "MD" => "Maryland", "ME" => "Maine", "MI" => "Michigan",
    "MN" => "Minnesota", "MO" => "Missouri", "MP" => "Northern Mariana Islands", "MS" => "Mississippi",
    "MT" => "Montana", "NC" => "North Carolina", "ND" => "North Dakota", "NE" => "Nebraska",
    "NH" => "New Hampshire", "NJ" => "New Jersey", "NM" => "New Mexico", "NV" => "Nevada", "NY" => "New York",
    "OH" => "Ohio", "OK" => "Oklahoma", "OR" => "Oregon", "PA" => "Pennsylvania", "PR" => "Puerto Rico",
    "RI" => "Rhode Island", "SC" => "South Carolina", "SD" => "South Dakota", "TN" => "Tennessee",
    "TX" => "Texas", "UT" => "Utah", "VA" => "Virginia", "VI" => "U.S. Virgin Islands", "VT" => "Vermont",
    "WA" => "Washington", "WI" => "Wisconsin", "WV" => "West Virginia", "WY" => "Wyoming"
  }.freeze

  # Mirrors transform/macros/normalize_position.sql.
  def self.position_kind(raw)
    case raw
    when "Yea", "Aye", "Guilty" then "yes"
    when "Nay", "No", "Not Guilty" then "no"
    when /\APresent/ then "present"
    when "Not Voting" then "not_voting"
    else "other"
    end
  end

  # Legend mark for a position: Yea solid, Nay striped, Not Voting open box.
  MARKS = { "yes" => "yea", "no" => "nay", "present" => "present", "not_voting" => "nv" }.freeze

  # The House records a bare "Passed", "Failed" or "Agreed to", which on its
  # own reads as the fate of the measure. Tie it to the question voted on:
  # "Motion to Refer: Passed". Senate results already name their subject
  # ("Motion to Proceed Agreed to", "Nomination Confirmed").
  BARE_RESULTS = ["Passed", "Failed", "Agreed to"].freeze

  # A Speaker election's result is the Clerk's short name for the top
  # candidate ("Johnson (LA)"), recorded even on a ballot that elects no one,
  # so it reads "Most votes: Mike Johnson (R-LA-4)" when the member is known.
  def self.result_label(v, members_by_id = {})
    if (m = members_by_id[v["result_bioguide_id"]])
      return "Most votes: #{member_name(m)} (#{m["party"]}-#{seat(m)})"
    end
    return v["result"] unless BARE_RESULTS.include?(v["result"])

    "#{v["question"].sub(/\AOn (the )?/, "")}: #{v["result"]}"
  end

  # A vote page's description (meta and link-card text): "House roll call
  # 317, Nov. 10, 2026. Motion to Refer: Passed, 211 Yea · 204 Nay · 18 Not
  # Voting." Present and Not Voting only when nonzero, and a tie the Vice
  # President broke named after the tally, as in bot posts.
  def self.vote_description(view)
    v = view["vote"]
    tally = view["tally"].select { |t| t["count"].positive? || %w[yea nay].include?(t["mark"]) }
                         .map { |t| "#{t["count"]} #{t["label"]}" }
    unless v["tie_breaker_by"].to_s.empty? || v["tie_breaker_vote"].to_s.empty?
      tally << "Vice President voted #{v["tie_breaker_vote"]} to break the tie"
    end
    tally = tally.join(" · ")
    "#{CHAMBER_NAMES[v["chamber"]]} roll call #{v["roll_number"]}, #{Filters.ap_date(v["vote_date"])}. " \
      "#{v["result_label"]}, #{tally}."
  end

  # The plain-language definition for a vote's question, from _data/procedures.yml.
  # Measure-type notes ("Bills become law if…") go with passage votes.
  def self.procedure(v, procedures)
    q = (procedures["questions"] || []).find do |p|
      Regexp.new(p["match"], Regexp::IGNORECASE).match?(v["question"].to_s) &&
        (p["title"].nil? || Regexp.new(p["title"], Regexp::IGNORECASE).match?(v["measure_title"].to_s))
    end
    return nil unless q

    note = (procedures["measures"] || []).find { |m| m["types"].include?(v["bill_type"]) }
    { "key" => q["key"], "term" => q["term"], "definition" => q["definition"], "more" => q["more"],
      "measure_note" => (%w[passage suspend].include?(q["key"]) && note) ? note["definition"] : nil }
  end

  # The dictionary page's entries: every question, kind of measure and other
  # floor term in procedures.yml, in A-Z order by term, each with its `see`
  # keys resolved to [{ "key", "term" }] (an unknown key raises, so a typo
  # stops the build rather than linking nowhere).
  def self.dictionary(procedures)
    entries = %w[questions measures terms].flat_map { |list| procedures[list] || [] }
    by_key = entries.to_h { |e| [e["key"], e] }
    entries.sort_by { |e| e["term"].downcase }.map do |e|
      see = (e["see"] || []).map { |k| { "key" => k, "term" => by_key.fetch(k)["term"] } }
      e.slice("key", "term", "definition", "more").merge("see" => see)
    end
  end

  # The House schedule's heading without its "Items that may be considered"
  # lead-in: "Under suspension of the rules", "Pursuant to a rule", or nil.
  def self.schedule_category(category)
    rest = category.to_s.sub(/\AItems that may be considered\s*/, "")
    rest.empty? ? nil : rest[0].upcase + rest[1..]
  end

  # "3 p.m.", "10:30 a.m.", "noon"
  def self.clock_label(t)
    return "noon" if t.hour == 12 && t.minute.zero?

    hour = t.hour % 12
    hour = 12 if hour.zero?
    "#{hour}#{t.minute.zero? ? "" : format(":%02d", t.minute)} #{t.hour < 12 ? "a.m." : "p.m."}"
  end

  # "2026-11-16T15:00:00" (Eastern) -> "Monday, Nov. 16, 2026, at 3 p.m. ET"
  def self.convene_label(iso)
    t = DateTime.strptime(iso, "%Y-%m-%dT%H:%M:%S")
    "#{Date::DAYNAMES[t.wday]}, #{Filters.ap_date(t)}, at #{clock_label(t)} ET"
  end

  # Each chamber's official live floor pages, for the home page's floor band.
  # The House's is the Clerk's YouTube stream: live.house.gov's player
  # doesn't play on phones.
  LIVE_FLOOR = {
    "senate" => { "watch_url" => "https://www.senate.gov/floor/", "watch_label" => "Floor webcast",
                  "floor_url" => "https://www.senate.gov/legislative/floor_activity_pail.htm",
                  "floor_label" => "Floor proceedings" },
    "house" => { "watch_url" => "https://www.youtube.com/USHouseClerk/live", "watch_label" => "Floor video",
                 "floor_url" => "https://clerk.house.gov/FloorSummary", "floor_label" => "Floor summary" }
  }.freeze

  # One line per chamber for the home page's floor band, from the export's
  # floor_status: when it convened if it hadn't adjourned as of the data,
  # else when it's next set to convene (left out when that's a pro forma
  # session). The page shows a line only from its time on (live-floor.js),
  # since the site is rebuilt hourly and the Senate's file changes only when
  # it adjourns. Times carry their Eastern offset, so the label reads in ET.
  # "in_session" only when the data shows the chamber convened, not when the
  # line comes from a scheduled time.
  def self.live_floor(status)
    return [] unless status

    %w[senate house].filter_map do |chamber|
      s = status[chamber] or next
      at, verb = if s["convened_at"]
                   [s["convened_at"], "Convened"]
                 elsif s["next_convene_at"] && s["next_convene_pro_forma"] != true
                   [s["next_convene_at"], "Scheduled to convene"]
                 end
      next unless at

      t = DateTime.iso8601(at)
      LIVE_FLOOR[chamber].merge("chamber" => chamber, "name" => CHAMBER_NAMES[chamber], "from" => t.iso8601,
                                "label" => "#{verb} at #{clock_label(t)} ET", "in_session" => verb == "Convened")
    rescue Date::Error
      next
    end
  end

  # The Senate's next convene time, or nil once it has passed (a failed
  # fetch can leave a stale one). `now` is the build time in ET; a Date reads
  # as its midnight. Both are ET wall-clock times, so their ISO strings
  # compare in time order.
  def self.upcoming_convene(iso, now)
    iso unless iso.nil? || iso < now.strftime("%Y-%m-%dT%H:%M:%S")
  end

  # The floor schedule for display. Each item links to its roll call once
  # there is one (else to Congress.gov, when it's a bill or resolution).
  # "Coming up" lists items without a roll call yet, and for the House only
  # the newest published week: by the time the next week's schedule is out,
  # the current week's floor business is mostly done. A convene time already
  # past `now` (the build time in ET) is left out.
  def self.schedule_view(schedule, votes_by_id, now)
    items = schedule["items"].map do |item|
      vote = item["vote_id"] && votes_by_id[item["vote_id"]]
      item.merge("chamber_name" => CHAMBER_NAMES[item["chamber"]],
                 "category_label" => schedule_category(item["category"]),
                 "vote_url" => vote && vote["url"],
                 "result_label" => vote && vote["result_label"])
    end
    house, senate = items.partition { |i| i["chamber"] == "house" }
    # Week -> heading -> items, in the schedule's own order.
    house_weeks = house.group_by { |i| i["week_date"] }.map do |week, rows|
      groups = rows.group_by { |i| i["category"] }.map { |category, r| { "category" => category, "items" => r } }
      { "week_date" => week, "groups" => groups }
    end
    next_convene = upcoming_convene(schedule["senate_next_convene_et"], now)
    latest_week = house_weeks.last
    {
      "upcoming_senate" => senate.reject { |i| i["vote_id"] },
      "upcoming_house" => house.select { |i| i["week_date"] == latest_week["week_date"] && !i["vote_id"] },
      "upcoming_week" => latest_week && latest_week["week_date"],
      "house_weeks" => house_weeks,
      "senate" => senate,
      "senate_next_convene" => next_convene && convene_label(next_convene)
    }
  end

  CALENDAR_WEEKS_BACK = 2

  # The floor schedule as weeks of days, for /schedule/. The sources give no
  # day for an upcoming vote (the House lists measures by week; a Senate
  # cloture vote follows its motion by rule, not on a set date), so a day
  # holds only what is dated: the roll calls taken that day, and the time
  # the Senate is next due to convene. Items still to come are listed under
  # their week until its Friday has passed. Weeks run from CALENDAR_WEEKS_BACK
  # weeks before today's through the latest week anything is scheduled for;
  # Saturdays and Sundays appear only when a vote was taken or the Senate
  # convenes on them.
  # `view` is schedule_view's result; `votes` need url and result_label.
  # `now` is the build time in ET (a Date reads as its midnight).
  def self.schedule_calendar(view, votes, now, next_convene_iso)
    today = now.to_date
    monday = ->(d) { d - ((d.wday - 1) % 7) }
    this_week = monday.call(today)
    next_convene_iso = upcoming_convene(next_convene_iso, now)
    convene = next_convene_iso && DateTime.strptime(next_convene_iso, "%Y-%m-%dT%H:%M:%S")
    house_weeks = (view["house_weeks"] || []).select { |w| w["week_date"] }
    listed_weeks = [convene && monday.call(convene.to_date),
                    *house_weeks.map { |w| Date.parse(w["week_date"]) }].compact
    last_week = [this_week, *listed_weeks].max
    first_week = this_week - (7 * CALENDAR_WEEKS_BACK)
    span = (first_week.to_s..(last_week + 6).to_s)
    taken = votes.select { |v| span.cover?(v["vote_date"]) }
                 .sort_by { |v| [v["congress"], v["session"], v["roll_number"]] }
                 .group_by { |v| [v["vote_date"], v["chamber"]] }
    # On a weekend, open on the coming week if anything is listed for it,
    # unless the Senate still convenes this weekend: its time and pending
    # cloture motions are on this week.
    weekend = today.saturday? || today.sunday?
    convenes_this_week = convene && monday.call(convene.to_date) == this_week
    default = weekend && !convenes_this_week && listed_weeks.include?(this_week + 7) ? this_week + 7 : this_week
    # Pending cloture motions go in the week the Senate next convenes.
    senate_week = convene ? monday.call(convene.to_date) : default

    weeks = (first_week..last_week).step(7).map do |mon|
      days = (mon..(mon + 6)).select do |d|
        d.wday.between?(1, 5) || taken.key?([d.to_s, "house"]) || taken.key?([d.to_s, "senate"]) ||
          d == convene&.to_date
      end
      days = days.map do |d|
        roll_calls = ->(chamber) do
          (taken[[d.to_s, chamber]] || []).map do |v|
            { "url" => v["url"], "label" => v["measure_label"] || v["question"], "result_label" => v["result_label"] }
          end
        end
        { "date" => d.to_s, "weekday" => Date::ABBR_DAYNAMES[d.wday],
          "label" => "#{Filters::AP_MONTHS[d.month - 1]} #{d.day}",
          "when" => if d < today then "past" elsif d == today then "today" else "future" end,
          "senate" => roll_calls.call("senate"), "house" => roll_calls.call("house"),
          "convene" => d == convene&.to_date ? "#{clock_label(convene)} ET" : nil }
      end
      house_week = house_weeks.find { |w| w["week_date"] == mon.to_s }
      # A House item listed but never put to a roll call (a voice vote, or it
      # didn't come up) drops off once its week's Friday has passed.
      house_pending = if house_week && mon + 4 >= today
                        house_week["groups"].map { |g| g.merge("items" => g["items"].reject { |i| i["vote_id"] }) }
                                            .reject { |g| g["items"].empty? }
                      else
                        []
                      end
      { "week_date" => mon.to_s, "label" => "Week of #{Filters.ap_date(mon)}",
        "tab" => { this_week => "This week", this_week + 7 => "Next week" }
                   .fetch(mon, "#{Filters::AP_MONTHS[mon.month - 1]} #{mon.day}"),
        "days" => days, "roll_calls" => days.sum { |d| d["senate"].size + d["house"].size },
        "senate_pending" => mon == senate_week ? view["upcoming_senate"] || [] : [],
        "house_pending" => house_pending }
    end
    { "weeks" => weeks, "default_week" => default.to_s }
  end

  # Stops the build on a field that isn't a positive integer or a known
  # chamber, rather than writing it into the page's path.
  def self.vote_url(v)
    ok = %w[congress session roll_number].all? { |k| v[k].is_a?(Integer) && v[k].positive? }
    raise ArgumentError, "vote #{v["vote_id"].inspect}: bad URL fields" unless ok && CHAMBER_NAMES.key?(v["chamber"])

    "/votes/#{v["congress"]}/#{v["chamber"]}/#{v["session"]}/#{v["roll_number"]}/"
  end

  def self.member_url(id)
    "/members/#{id}/"
  end

  # One Congress's bills from a member's sponsored or cosponsored lists (one group per
  # fetched Congress), or nil when that Congress's list hasn't been fetched. Files exported
  # before the lists were grouped hold one Congress's bills as a plain list, returned as is,
  # so a site build between this change and the next export still shows them.
  def self.congress_bills(lists, congress)
    return lists unless lists&.first&.key?("bills")

    group = lists.find { |l| l["congress"].to_i == congress.to_i }
    group && group["bills"]
  end

  # The other Congresses' groups ({ "congress", "bills" }), newest first; none for an
  # ungrouped list.
  def self.earlier_congress_bills(lists, congress)
    return [] unless lists&.first&.key?("bills")

    lists.reject { |l| l["congress"].to_i == congress.to_i }.sort_by { |l| -l["congress"].to_i }
  end

  def self.member_name(m)
    m["official_full_name"] || [m["first_name"], m["last_name"]].compact.join(" ")
  end

  # "KY-4" for House, "KY" for Senate and at-large House seats.
  def self.seat(m)
    m["chamber"] == "house" && m["district"].to_i.positive? ? "#{m["state"]}-#{m["district"]}" : m["state"]
  end

  # "Kentucky, 4th District", "Wyoming, At Large", "Kentucky" (Senate).
  def self.where(m)
    state = STATE_NAMES.fetch(m["state"], m["state"])
    return state unless m["chamber"] == "house"

    d = m["district"].to_i
    d.positive? ? "#{state}, #{Filters.ordinal(d)} District" : "#{state}, At Large"
  end

  ORDINAL_WORDS = %w[first second third fourth fifth sixth seventh eighth ninth].freeze

  # The member page's service line, from every term congress-legislators lists:
  # "Serving a third term in the House; first term began in 2021." or, for a
  # former member, "Served 3 terms in the House; ...", plus "Also served in the Senate,
  # 2013–2019." Nil without term data. Ordinals are spelled out through ninth (AP style).
  def self.service_line(m)
    terms = m["chamber_terms"].to_i
    return nil unless terms.positive? && m["chamber_first_term_start"]

    chamber, other = m["chamber"] == "senate" ? %w[Senate House] : %w[House Senate]
    line = if m["is_current"]
             nth = ORDINAL_WORDS[terms - 1] || Filters.ordinal(terms)
             article = nth.start_with?("eighth", "8", "11", "18") ? "an" : "a"
             "Serving #{article} #{nth} term in the #{chamber}"
           else
             "Served #{terms} #{terms == 1 ? "term" : "terms"} in the #{chamber}"
           end
    # The year only: a term filled by special election starts with its Congress, before
    # the member took office.
    line += "; first term began in #{m["chamber_first_term_start"].to_s[0, 4]}."
    from, to = m["other_chamber_from_year"], m["other_chamber_to_year"]
    line += " Also served in the #{other}, #{from == to ? from : "#{from}–#{to}"}." if from && to
    line
  end

  # A Congressional Directory biography for the member page: the opening as a sentence
  # ("Of Oakland, CA; born in ..."), the labeled fields as rows, and the edition's GovInfo
  # page for the credit line. Nil without one.
  def self.member_bio(bio)
    return nil unless bio && bio["opening"]

    rows = [["Education", bio["education"]], ["Career", bio["professional_history"]],
            ["Military service", bio["military_service"]]].select { |_, text| text }
    { "opening" => "#{bio["opening"][0].upcase}#{bio["opening"][1..]}.",
      "rows" => rows.map { |label, text| { "label" => label, "text" => text } },
      "date_issued" => bio["date_issued"],
      "source_url" => "https://www.govinfo.gov/app/details/#{bio["edition"]}" }
  end

  # The /find/ district map: shapes from site/_maps/{congress}.json
  # (scripts/build_district_map.py), each paired with the district's current
  # representative. "people" holds what the map's card shows for each seat,
  # with the state's senators. Nil when there's no map for this Congress.
  def self.district_map(map, members)
    return nil unless map

    card = ->(m) { { "name" => m["name"], "id" => m["bioguide_id"], "party" => m["party"] } }
    current = members.select { |m| m["is_current"] && m["is_voting_member"] }
    reps = current.select { |m| m["chamber"] == "house" }.to_h { |m| [[m["state"], m["district"].to_i], m] }
    senators = current.select { |m| m["chamber"] == "senate" }.group_by { |m| m["state"] }

    people = {}
    districts = map["districts"].map do |d|
      seat = { "chamber" => "house", "state" => d["state"], "district" => d["district"] }
      key = seat(seat)
      rep = reps[[d["state"], d["district"]]]
      people[key] = { "where" => where(seat), "rep" => rep && card.call(rep),
                      "senators" => (senators[d["state"]] || []).map(&card),
                      "places" => d["places"] || [], "more_places" => d["more_places"].to_i }
      { "seat" => key, "d" => d["d"], "where" => people[key]["where"],
        "rep_name" => rep && rep["name"], "rep_party" => rep && rep["party"],
        "url" => rep ? rep["url"] : "/members/?state=#{d["state"]}" }
    end
    { "width" => map["width"], "height" => map["height"], "borders" => map["borders"],
      "cities" => map["cities"] || [], "districts" => districts,
      # Every "<" escaped, so nothing in a name can end or confuse the script tag.
      "people_json" => JSON.generate(people).gsub("<", "\\u003c") }
  end

  # Official social media accounts, in one fixed order for every member.
  # "icon" names the mark in _includes/account_icon.html.
  ACCOUNTS = [["x_url", "X", "x"], ["facebook_url", "Facebook", "facebook"], ["instagram_url", "Instagram", "instagram"],
              ["youtube_url", "YouTube", "youtube"], ["mastodon_url", "Mastodon", "mastodon"],
              ["bluesky_url", "Bluesky", "bluesky"]].freeze

  def self.accounts(m)
    ACCOUNTS.filter_map { |key, label, icon| m[key] && { "label" => label, "url" => m[key], "icon" => icon } }
  end

  # A link from the data, kept only as a web address: escaping keeps it inside
  # its href, but a "javascript:" or other scheme would still run when clicked.
  def self.web_url(url)
    url if url.is_a?(String) && url.match?(%r{\Ahttps?://}i)
  end

  # A Congress.gov bill page's text tab: "/text" ends the path, ahead of any
  # query or fragment ("…/house-bill/1?s=1" -> "…/house-bill/1/text?s=1").
  def self.text_url(url)
    url && url.sub(%r{/?(?=[?#]|\z)}, "/text")
  end

  # Member fields that hold links, website first (website_label reads it).
  MEMBER_LINKS = ["website_url", "contact_form_url", *ACCOUNTS.map(&:first)].freeze

  # "https://www.example.house.gov/" -> "example.house.gov"
  def self.website_label(url)
    url && url.sub(%r{\Ahttps?://(www\.)?}, "").chomp("/")
  end

  # The words this vote recorded for yes and no: Yea/Nay, Aye/No or Guilty/Not Guilty.
  def self.words(positions)
    seen = positions.values.uniq
    yes = (%w[Aye Guilty] & seen).first || "Yea"
    no = { "Aye" => "No", "Guilty" => "Not Guilty" }.fetch(yes, "Nay")
    { "yes" => yes, "no" => no }
  end

  GRID_COLS = 25 # squares per row, the same in both chambers so their sizes compare
  GRID_PITCH = 12 # px from one square to the next: a 10px square and a 2px gap

  # One square per member, a block per party: Yea, then Nay, Present and Not
  # voting, filled row by row. Each run of one position is a group the include
  # draws with that position's mark; x and y are the square's top-left corner.
  def self.party_grid(by_party, words)
    by_party.map do |p|
      i = 0
      runs = [["yea", words["yes"], p["yes"]], ["nay", words["no"], p["no"]],
              ["present", "Present", p["present"]], ["nv", "Not Voting", p["not_voting"]]].filter_map do |mark, label, n|
        next if n.zero?
        cells = Array.new(n) do
          cell = { "x" => (i % GRID_COLS) * GRID_PITCH, "y" => (i / GRID_COLS) * GRID_PITCH }
          i += 1
          cell
        end
        { "mark" => mark, "label" => label, "count" => n, "cells" => cells }
      end
      rows = (i + GRID_COLS - 1) / GRID_COLS
      { "party" => p["party"], "name" => p["name"], "runs" => runs,
        "width" => [i, GRID_COLS].min * GRID_PITCH - 2, "height" => rows * GRID_PITCH - 2 }
    end.reject { |g| g["runs"].empty? }
  end

  TERRITORIES = %w[AS DC GU MP PR VI].freeze

  # The vote page map and by-state table for one vote. "seats" is what the map draws
  # (site/assets/js/vote-map.js): for each House seat ("KY-4", "WY") or Senate
  # state ("KY"), its members' marks in last-name order and a hover title. DC
  # and the territories aren't on the map (their delegates can't vote on the
  # House floor) but are in the table; "unmapped" counts them, with members of
  # no known state, for a note. Members are as of the vote (members_as_of).
  def self.state_map(chamber, positions, members_by_id, words)
    return nil if positions.empty?

    labels = { "yes" => words["yes"], "no" => words["no"], "present" => "Present", "not_voting" => "Not Voting" }
    house = chamber == "house"
    counts = Hash.new { |h, k| h[k] = Hash.new(0) }
    seats = {}
    unmapped = 0
    positions.sort_by { |id, _| [members_by_id.dig(id, "last_name").to_s, id] }.each do |id, raw|
      m = members_by_id[id] || {}
      kind = position_kind(raw)
      counts[m["state"]][kind] += 1 if STATE_NAMES.key?(m["state"])
      if !STATE_NAMES.key?(m["state"]) || TERRITORIES.include?(m["state"]) || (house && m["chamber"] != "house")
        unmapped += 1
        next
      end
      s = seats[house ? seat(m) : m["state"]] ||= { "where" => house ? where(m) : STATE_NAMES[m["state"]], "marks" => [], "who" => [] }
      s["marks"] << MARKS[kind]
      s["who"] << "#{member_name(m)} (#{m["party"]}), #{labels[kind]}"
    end
    seats = seats.transform_values { |s| { "marks" => s["marks"], "title" => "#{s["where"]}: #{s["who"].join("; ")}" } }
    {
      "chamber" => chamber, "unmapped" => unmapped,
      # Every "<" escaped, so nothing in a name can end or confuse the script tag.
      "seats_json" => JSON.generate(seats).gsub("<", "\\u003c"),
      # The text version: one row per state, by name.
      "table" => counts.sort_by { |state, _| STATE_NAMES[state] }.map do |state, c|
        { "name" => STATE_NAMES[state], "yes" => c["yes"], "no" => c["no"], "present" => c["present"], "not_voting" => c["not_voting"] }
      end
    }
  end

  # Kinds of vote on the floor activity chart, bottom of each stack first.
  # Questions group by their procedures.yml key; a key not listed here, or a
  # question with no definition, counts as procedural and other.
  VOTE_KINDS = [
    { "key" => "passage", "label" => "Passage",
      "procedures" => %w[passage suspend concur concur_amendment veto_override expel] },
    { "key" => "amendment", "label" => "Amendments", "procedures" => %w[amendment] },
    { "key" => "nomination", "label" => "Nominations", "procedures" => %w[nomination] },
    { "key" => "procedural", "label" => "Procedural and other", "procedures" => [] }
  ].freeze

  def self.vote_kind(procedure_key)
    (VOTE_KINDS.find { |k| k["procedures"].include?(procedure_key) } || VOTE_KINDS.last)["key"]
  end

  VOLUME_SLOT = 8 # chart units per week: a 6-unit bar and a 2-unit gap
  VOLUME_HEIGHT = 200 # px; the chart stretches to the page width, not its height

  # Roll calls per week (Monday to Sunday), by chamber and kind of vote, for
  # the floor activity page. Both chambers share the same weeks and scale, so
  # their bars compare. Weeks with no roll calls are kept, as gaps. Each week
  # carries its stacked segments (y from the top, in chart units) and a
  # one-line summary for the hover caption and the table.
  # A bar's counts by kind for the hover box (activity.js): "passage:4,procedural:5",
  # in VOTE_KINDS order, kinds with none left out.
  def self.kind_counts(counts)
    VOTE_KINDS.filter_map { |k| "#{k["key"]}:#{counts[k["key"]]}" if counts[k["key"]].positive? }.join(",")
  end

  # The Monday that starts a vote's week.
  def self.week_of(v)
    d = Date.parse(v["vote_date"])
    d - ((d.wday + 6) % 7)
  end

  def self.vote_volume(votes)
    return nil if votes.empty?

    week_of = method(:week_of)
    counts = Hash.new { |h, k| h[k] = Hash.new(0) }
    votes.each { |v| counts[[v["chamber"], week_of.call(v)]][vote_kind(v.dig("procedure", "key"))] += 1 }
    first, last = votes.map(&week_of).minmax
    weeks = first.step(last, 7).to_a
    top = counts.values.map { |c| c.values.sum }.max
    step = top > 50 ? 20 : top > 20 ? 10 : 5
    y_max = (top.to_f / step).ceil * step
    scale = VOLUME_HEIGHT.to_f / y_max

    chambers = CHAMBER_NAMES.filter_map do |chamber, name|
      totals = Hash.new(0)
      rows = weeks.each_with_index.map do |start, i|
        c = counts.fetch([chamber, start], Hash.new(0))
        y = VOLUME_HEIGHT.to_f
        segments = VOTE_KINDS.filter_map do |k|
          n = c.fetch(k["key"], 0)
          next if n.zero?

          totals[k["key"]] += n
          h = n * scale
          y -= h
          # A 1px surface gap above each segment; a single roll call stays visible,
          # rising from the segment's bottom so it never drops below the baseline.
          height = [h - 1, 1].max
          { "kind" => k["key"], "y" => [y + h - height, 0].max.round(1), "h" => height.round(1) }
        end
        total = c.values.sum
        parts = VOTE_KINDS.filter_map { |k| "#{k["label"]} #{c[k["key"]]}" if c[k["key"]].positive? }
        { "start" => start.iso8601, "x" => i * VOLUME_SLOT, "total" => total, "segments" => segments,
          "counts" => VOTE_KINDS.to_h { |k| [k["key"], c.fetch(k["key"], 0)] },
          "head" => "#{name} · week of #{Filters.ap_date(start)}", "kind_counts" => kind_counts(c),
          "summary" => "Week of #{Filters.ap_date(start)}: " +
            (total.zero? ? "no roll calls" : "#{total} roll call#{"s" unless total == 1} · #{parts.join(" · ")}") }
      end
      next if totals.empty?

      { "chamber" => chamber, "name" => name, "weeks" => rows, "total" => totals.values.sum,
        "totals" => VOTE_KINDS.to_h { |k| [k["key"], totals[k["key"]]] } }
    end

    {
      "kinds" => VOTE_KINDS.map { |k| k.slice("key", "label") },
      "chambers" => chambers, "width" => weeks.size * VOLUME_SLOT, "height" => VOLUME_HEIGHT,
      "first_week" => first.iso8601, "last_week" => last.iso8601,
      # Gridlines and their labels, bottom first; y in chart units from the top.
      "y_ticks" => (0..y_max).step(step).map { |n| { "value" => n, "y" => (VOLUME_HEIGHT - n * scale).round(1) } },
      # A tick at the week holding each month's 1st; January (with its year) and July are labeled.
      "x_ticks" => weeks.each_with_index.filter_map do |start, i|
        month = start + 6
        next unless month.day <= 7

        label = { 1 => "Jan. #{month.year}", 7 => "July" }[month.month]
        { "pct" => (100.0 * i / weeks.size).round(2), "label" => label }
      end
    }
  end

  # Every roll call, newest first, in the short form the floor activity page
  # fetches (/activity/rollcalls.json) to list a clicked bar's roll calls:
  # week ("w", a Monday), chamber, policy area row ("a", nil before the export
  # carries policy_area) and kind to filter by, plus what each line shows.
  # activity.js writes these as text, never HTML.
  def self.activity_votes(votes)
    with_areas = votes.any? { |v| v.key?("policy_area") }
    votes.map do |v|
      question = [v["question"], (v["measure_label"] unless v["question"].to_s.include?(v["measure_label"].to_s))].compact.join(" · ")
      # The title line, as vote pages show it; with no title (a Speaker election),
      # the question is the title and isn't repeated above it ("q" nil).
      title = [v["measure_title"], v["vote_title"]].find { |t| !t.to_s.strip.empty? }
      { "u" => v["url"], "c" => v["chamber"], "w" => week_of(v).iso8601,
        "a" => with_areas ? policy_row(v) : nil, "k" => vote_kind(v.dig("procedure", "key")),
        "d" => Filters.ap_date(v["vote_date"]), "r" => v["roll_number"],
        "q" => title && question, "t" => title || question, "s" => v["result_label"] }
    end
  end

  # Rows on the policy area chart for votes that can't have a policy area,
  # listed after the areas themselves.
  NO_AREA = ["Nominations", "No bill recorded", "Not yet assigned"].freeze

  # A vote's row on the policy area chart: the CRS policy area of its bill;
  # nominations (PN numbers, including cloture on them) and votes that record
  # no bill have their own rows, as do bills CRS hasn't assigned an area yet.
  def self.policy_row(v)
    return v["measure_number"].to_s.start_with?("PN") ? "Nominations" : "No bill recorded" unless v["bill_type"]

    v["policy_area"].to_s.empty? ? "Not yet assigned" : v["policy_area"]
  end

  # Roll calls by policy area and chamber, stacked by kind of vote, for the
  # floor activity page. Areas run from most roll calls in both chambers to
  # fewest; both chambers share one scale (width in percent of the largest
  # chamber's area). The NO_AREA rows have no subject to compare, so they're
  # counted ("other") rather than drawn, where a long Nominations row would
  # flatten every area; the table lists all rows. Nil until the export
  # carries policy_area, or when no vote has an area to draw.
  def self.policy_volume(votes)
    return nil unless votes.any? { |v| v.key?("policy_area") }

    counts = Hash.new { |h, k| h[k] = Hash.new(0) }
    votes.each { |v| counts[[policy_row(v), v["chamber"]]][vote_kind(v.dig("procedure", "key"))] += 1 }
    rows = counts.keys.map(&:first).uniq
    total = ->(row, chamber = nil) { counts.sum { |(r, c), k| r == row && (chamber.nil? || c == chamber) ? k.values.sum : 0 } }
    areas = (rows - NO_AREA).sort_by { |r| [-total.call(r), r] }
    return nil if areas.empty?

    other = NO_AREA & rows
    max = counts.reject { |(r, _), _| NO_AREA.include?(r) }.values.map { |k| k.values.sum }.max || 1
    present = CHAMBER_NAMES.select { |chamber, _| counts.keys.any? { |(_, c)| c == chamber } }

    drawn = counts.reject { |(r, _), _| NO_AREA.include?(r) }.values.flat_map(&:keys).uniq
    {
      # The legend: only kinds some area's bar has (nominations have no bill, so no area).
      "kinds" => VOTE_KINDS.select { |k| drawn.include?(k["key"]) }.map { |k| k.slice("key", "label") },
      "area_count" => areas.size,
      "other" => other.map do |row|
        { "area" => row, "counts" => present.filter_map { |c, name| "#{name} #{total.call(row, c)}" if total.call(row, c).positive? }.join(", ") }
      end,
      "chambers" => present.map do |chamber, name|
        { "chamber" => chamber, "name" => name, "rows" => areas.map do |row|
          c = counts.fetch([row, chamber], Hash.new(0))
          n = c.values.sum
          parts = VOTE_KINDS.filter_map { |k| "#{k["label"]} #{c[k["key"]]}" if c[k["key"]].positive? }
          { "area" => row, "total" => n, "pct" => (100.0 * n / max).round(2),
            "head" => "#{row} · #{name}", "kind_counts" => kind_counts(c),
            "segments" => VOTE_KINDS.filter_map do |k|
              { "kind" => k["key"], "pct" => (100.0 * c[k["key"]] / n).round(2) } if c[k["key"]].positive?
            end,
            "summary" => "#{row}, #{name}: " +
              (n.zero? ? "no roll calls" : "#{n} roll call#{"s" unless n == 1} · #{parts.join(" · ")}") }
        end }
      end,
      # The text version: one row per area, both chambers, then the NO_AREA rows.
      "table" => (areas + other).map { |row| { "area" => row, "house" => total.call(row, "house"), "senate" => total.call(row, "senate"), "total" => total.call(row) } }
    }
  end

  # ---- Home page modules ----
  # Each list holds its first rows from each chamber, so the chamber tabs
  # still fill it; the page shows HOME_ROWS[key] at a time (data-limit).

  HOME_ROWS = { "closest" => 3, "against" => 5 }.freeze
  HOME_DAYS = 30 # closest votes: the days ending on the newest vote's date
  HOME_WEEKS = 26 # this week's chart: weeks shown, ending with the newest
  HOME_AREAS = 6
  SHARE_WORDS = { "1/2" => "a majority of those voting", "2/3" => "two-thirds of those voting",
                  "3/5" => "three-fifths of senators" }.freeze

  # The first n rows of each chamber, in the order given.
  def self.per_chamber(rows, n)
    seen = Hash.new(0)
    rows.select { |r| (seen[r["vote"]["chamber"]] += 1) <= n }
  end

  # Votes whose Yeas came nearest the Yeas needed to carry them (yeas_needed),
  # nearest first, then newest, with the words each vote recorded (Yea or
  # Aye). A tie the Vice President broke counts as nearest: yeas_needed
  # leaves the tie-breaking vote out, and the page names the tie-break
  # instead. Nil until the export carries yeas_needed.
  def self.closest_votes(votes, views = {}, n = HOME_ROWS["closest"])
    return nil unless votes.any? { |v| v.key?("yeas_needed") }

    through = votes.map { |v| Date.parse(v["vote_date"]) }.max
    since = through - (HOME_DAYS - 1)
    rows = votes.each_with_index.filter_map do |v, i|
      next unless v["yeas_needed"] && Date.parse(v["vote_date"]) >= since

      cast = v["yea_count"] + v["nay_count"]
      gap = v["tie_breaker_by"] ? 0 : (v["yea_count"] - v["yeas_needed"]).abs
      { "vote" => v, "gap" => gap, "order" => i,
        "needed" => v["yeas_needed"], "share" => SHARE_WORDS[v["required_share"]],
        "words" => views.dig(v["vote_id"], "words") || { "yes" => "Yea", "no" => "Nay" },
        "yea_pct" => (100.0 * v["yea_count"] / cast).round(1),
        "tick_pct" => [100.0 * v["yeas_needed"] / cast, 100].min.round(1) }
    end
    rows.sort_by! { |r| [r["gap"], r["order"]] }
    # "Oct. 14 through Nov. 12, 2026"; the first year too when they differ.
    from = Filters.ap_date(since)
    from = from.delete_suffix(", #{since.year}") if since.year == through.year
    { "since" => since.iso8601, "through" => through.iso8601,
      "range" => "#{from} through #{Filters.ap_date(through)}",
      "rows" => per_chamber(rows, n).map { |r| r.except("gap", "order") } }
  end

  # Votes the bot posts on which any member voted against their party's
  # majority, newest first, with the members' names when there are 1 to 5
  # (the bot's party-break line). Nil until the export carries bot_posts.
  def self.against_votes(votes, views, n = HOME_ROWS["against"])
    return nil unless votes.any? { |v| v.key?("bot_posts") }

    rows = votes.filter_map do |v|
      next unless v["bot_posts"] && v["against_party_majority_count"].to_i.positive?

      against = views.dig(v["vote_id"], "against") || []
      { "vote" => v, "count" => v["against_party_majority_count"],
        "names" => against.size.between?(1, 5) ? against : [] }
    end
    per_chamber(rows, n)
  end

  # The newest week's roll calls by chamber, with bars for the HOME_WEEKS
  # weeks ending with it (heights in percent of the tallest), from vote_volume.
  def self.home_week(vol, weeks = HOME_WEEKS)
    return nil unless vol

    shown = vol["chambers"].map { |c| [c, c["weeks"].last(weeks)] }
    return nil if shown.empty?

    top = [shown.flat_map { |_, w| w.map { |x| x["total"] } }.max.to_i, 1].max
    first = shown.first[1].first["start"]
    {
      "start" => vol["last_week"], "first" => first,
      "chambers" => shown.map do |c, w|
        { "chamber" => c["chamber"], "name" => c["name"], "total" => w.last["total"],
          "label" => "#{c["name"]} roll calls per week, week of #{Filters.ap_date(first)} " \
                     "to week of #{Filters.ap_date(vol["last_week"])}: #{w.map { |x| x["total"] }.join(", ")}",
          "bars" => w.map { |x| { "pct" => (100.0 * x["total"] / top).round(1) } } }
      end
    }
  end

  # The policy areas with the most roll calls this Congress, from policy_volume.
  def self.home_areas(pv, n = HOME_AREAS)
    return nil unless pv

    rows = pv["table"].first([n, pv["area_count"]].min)
    top = rows.first["total"]
    rows.map { |r| r.merge("pct" => (100.0 * r["total"] / top).round(1)) }
  end

  MEMBER_AREAS = 8

  # "Health" -> "health", "Armed Forces and National Security" -> "armed-forces-and-national-security".
  def self.area_slug(area) = area.downcase.gsub(/[^a-z0-9]+/, "-").gsub(/\A-|-\z/, "")

  # A member's bill list by CRS policy area, most first (ties by name), with bills
  # CRS hasn't assigned an area yet last. The first n rows show; the rest sit under
  # "more", unless that's only one or two. Each row's slug is the filter value its bills carry (b["area_slug"]),
  # and pct sizes its bar against the largest area.
  def self.member_areas(bills, n = MEMBER_AREAS)
    return nil if bills.nil? || bills.empty?

    counts = Hash.new(0)
    bills.each do |b|
      b["area"] = b["policy_area"].to_s.empty? ? "Not yet assigned" : b["policy_area"]
      b["area_slug"] = area_slug(b["area"])
      counts[b["area"]] += 1
    end
    unassigned = counts.delete("Not yet assigned")
    rows = counts.sort_by { |a, c| [-c, a] }
    rows << ["Not yet assigned", unassigned] if unassigned
    top = rows.map(&:last).max
    rows = rows.map { |a, c| { "area" => a, "slug" => area_slug(a), "count" => c, "pct" => (100.0 * c / top).round(1) } }
    # Folding away one or two areas saves no room.
    n = rows.size if rows.size <= n + 2
    { "shown" => rows.first(n), "more" => rows.drop(n) }
  end

  # "2026-03" for a vote.
  def self.month_of(v) = v["vote_date"].to_s[0, 7]

  # Each chamber and Congress's months, first roll call to last, as "YYYY-MM",
  # including months with none (an August recess).
  def self.chamber_months(votes)
    votes.group_by { |v| [v["chamber"], v["congress"].to_i] }.transform_values do |vs|
      first, last = vs.map { |v| Date.parse("#{month_of(v)}-01") }.minmax
      months = []
      while first <= last
        months << first.strftime("%Y-%m")
        first = first.next_month
      end
      months
    end
  end

  # A member's roll calls per month in one Congress: cast (any response but Not
  # Voting) and missed, over all of the chamber's months, so a month before they took
  # office or with no roll calls shows none. Heights are percent of the chamber's
  # busiest month for this member; labels name January and the first month's year.
  def self.member_months(list, months)
    return nil if months.nil? || list.empty?

    counts = Hash.new { |h, k| h[k] = { "cast" => 0, "missed" => 0 } }
    list.each { |p| counts[month_of(p["vote"])][p["position"] == "Not Voting" ? "missed" : "cast"] += 1 }
    top = [counts.values.map { |c| c["cast"] + c["missed"] }.max.to_i, 1].max
    rows = months.each_with_index.map do |ym, i|
      c = counts.fetch(ym, { "cast" => 0, "missed" => 0 })
      year, month = ym.split("-").map(&:to_i)
      name = Filters::AP_MONTHS[month - 1]
      { "month" => ym, "name" => "#{name} #{year}", "cast" => c["cast"], "missed" => c["missed"],
        "total" => c["cast"] + c["missed"],
        "cast_pct" => (100.0 * c["cast"] / top).round(1), "missed_pct" => (100.0 * c["missed"] / top).round(1),
        "initial" => name[0], "year" => (month == 1 || i.zero?) ? year : nil }
    end
    { "months" => rows, "max" => top, "first" => rows.first["name"], "last" => rows.last["name"] }
  end

  # The median of a list of numbers, to one decimal; nil for none.
  def self.median(xs)
    return nil if xs.empty?

    s = xs.sort
    mid = s.size / 2
    (s.size.odd? ? s[mid] : (s[mid - 1] + s[mid]) / 2.0).round(1)
  end

  # Per chamber, the members its medians count: those with roll calls in the given
  # Congress (their last), and at least a tenth as many as the member with the most,
  # so a few roll calls don't weigh the same as a full term. A share, not a fixed
  # number, so medians show from a Congress's first roll call.
  def self.median_members(members, congress)
    in_congress = members.select { |m| m["roll_calls"].to_i.positive? && m["last_congress"].to_i == congress.to_i }
    CHAMBER_NAMES.to_h do |chamber, _|
      ms = in_congress.select { |m| m["chamber"] == chamber }
      most = ms.map { |m| m["roll_calls"].to_i }.max
      [chamber, ms.select { |m| m["roll_calls"].to_i * 10 >= most }]
    end
  end

  # Per chamber, the median missed-votes and with-party-majority rates of its
  # median_members, so a profile can show one beside the member's own.
  def self.chamber_medians(members, congress)
    counted = median_members(members, congress)
    CHAMBER_NAMES.to_h do |chamber, name|
      ms = counted[chamber]
      [chamber, { "name" => name, "members" => ms.size,
                  "missed_votes_pct" => median(ms.map { |m| m["missed_votes_pct"].to_f }),
                  "with_party_majority_pct" => median(ms.filter_map { |m| m["with_party_majority_pct"]&.to_f }) }]
    end
  end

  # The tags src/yan/export/summary_html.py keeps, always bare (no attributes).
  SUMMARY_TAGS = %w[p ul ol li strong em b i br sub sup].freeze
  SUMMARY_TOKEN = %r{</?(?:#{SUMMARY_TAGS.join("|")})>|[<>]}

  # The vote page inserts a CRS summary as HTML. The pipeline's update job
  # already reduced it to SUMMARY_TAGS, but that job runs third-party code, so
  # the site build checks again: those bare tags pass, and any other < or >
  # is escaped, so nothing else in the data can become markup. Tags are also
  # balanced, so none reaches past the summary: a closing tag closes the tags
  # opened since its own (as a browser does), one with nothing to close is
  # escaped, and tags left open are closed at the end. Not a string, or not
  # valid UTF-8 (which would stop the build): no text.
  def self.summary_html(html)
    return nil unless html.is_a?(String) && html.valid_encoding?

    open = []
    out = html.gsub(SUMMARY_TOKEN) do |t|
      if (tag = t[%r{\A</(\w+)>\z}, 1])
        next "&lt;/#{tag}&gt;" unless (i = open.rindex(tag))

        open.slice!(i..).reverse.map { |o| "</#{o}>" }.join
      elsif (tag = t[/\A<(\w+)>\z/, 1])
        open << tag unless tag == "br"
        t
      else
        { "<" => "&lt;", ">" => "&gt;" }.fetch(t)
      end
    end
    out + open.reverse.map { |o| "</#{o}>" }.join
  end

  # Entities that only make whitespace or nothing visible: &nbsp;, &ensp;,
  # &emsp;, &thinsp;, &zwnj;, &zwj;, &shy;, &lrm;, &rlm; and the tab, line
  # break, carriage return, space, no-break space, soft hyphen, en space, em
  # space, thin space, zero-width space, zero-width non-joiner, zero-width
  # joiner, left-to-right and right-to-left marks, line and paragraph
  # separators, word joiner and byte order mark as numbers. Also those
  # characters written out that [[:space:]] doesn't match: soft hyphen,
  # zero-width space, non-joiner and joiner, the two marks, word joiner and
  # byte order mark.
  BLANK_ENTITY = Regexp.union(
    /&(?:nbsp|ensp|emsp|thinsp|zwnj|zwj|shy|lrm|rlm);/i,
    /&#0*(?:9|10|13|32|160|173|8194|8195|8201|8203|8204|8205|8206|8207|8232|8233|8288|65279);/,
    /&#x0*(?:9|a|d|20|a0|ad|2002|2003|2009|200b|200c|200d|200e|200f|2028|2029|2060|feff);/i,
    /[\u00AD\u200B-\u200F\u2060\uFEFF]/
  )

  # The steps on a measure's path (src/yan/export/bill_path.py) and their
  # links into /how/bills/. Only known statuses and anchors pass; a date that
  # isn't an ISO date is left out rather than stopping the build.
  PATH_STATUSES = %w[done failed skipped in_progress upcoming].freeze
  PATH_ANCHORS = %w[introduced committee first-chamber second-chamber differences president override].freeze

  def self.bill_path_view(path)
    steps = path.is_a?(Hash) && path["steps"]
    return nil unless steps.is_a?(Array) && !steps.empty?

    view = steps.filter_map do |s|
      next unless s.is_a?(Hash) && PATH_STATUSES.include?(s["status"]) && s["label"].is_a?(String)

      { "label" => s["label"], "status" => s["status"], "current" => s["current"] == true,
        "date" => (s["date"] if s["date"].is_a?(String) && s["date"].match?(/\A\d{4}-\d{2}-\d{2}\z/)),
        "anchor" => (s["anchor"] if PATH_ANCHORS.include?(s["anchor"])) }
    end
    view.empty? ? nil : view
  end

  # A CRS summary as the vote page shows it, or nil when it has no text
  # (only tags, whitespace or the invisible text above), which reads as no
  # summary. A version date that isn't an ISO date, or a blank version
  # label, is left out rather than stopping the build.
  def self.summary_view(s)
    return nil unless s.is_a?(Hash) && (html = summary_html(s["html"]))
    return nil if html.match?(%r{\A(?:[[:space:]\0]|</?\w+>|#{BLANK_ENTITY})*\z})

    date = begin
      Date.iso8601(s["version_date"]) if s["version_date"].is_a?(String)
    rescue Date::Error
      nil
    end
    version = s["version"].gsub(/\A[[:space:]]+|[[:space:]]+\z/, "") if s["version"].is_a?(String)
    s.merge("html" => html, "version" => (version unless version.to_s.empty?), "version_date" => date)
  end

  # Members by id with the party, caucus and seat they had on the vote's date.
  # The vote file lists only those whose latest differ; older files list none.
  def self.members_as_of(doc, members_by_id)
    (doc["members_as_of_vote"] || {}).each_with_object(members_by_id.dup) do |(id, as_of), h|
      m = (h[id] || {}).merge(as_of)
      h[id] = m.merge("seat" => seat(m))
    end
  end

  # Everything the tally, by-party and against-majority blocks need for one vote.
  # members_by_id is as of the vote (members_as_of), except latest_by_id, the
  # fallback for the sponsor.
  def self.vote_view(vote, doc, members_by_id, latest_by_id = members_by_id)
    words = words(doc["positions"])
    counts = Hash.new(0)
    other = Hash.new(0)
    doc["positions"].each_value do |raw|
      kind = position_kind(raw)
      counts[kind] += 1
      other[raw] += 1 if kind == "other"
    end

    tally = []
    # Election of the Speaker: tallied by candidate, in descending order.
    other.sort_by { |name, n| [-n, name] }.each { |name, n| tally << { "label" => name, "count" => n } }
    tally << { "label" => words["yes"], "count" => counts["yes"], "mark" => "yea" } if other.empty? || counts["yes"].positive?
    tally << { "label" => words["no"], "count" => counts["no"], "mark" => "nay" } if other.empty? || counts["no"].positive?
    tally << { "label" => "Present", "count" => counts["present"], "mark" => "present" }
    tally << { "label" => "Not Voting", "count" => counts["not_voting"], "mark" => "nv" }

    total = doc["positions"].size
    pct = ->(n) { total.zero? ? 0 : (100.0 * n / total).round(1) }

    by_party = PARTIES.filter_map do |p|
      t = doc["party_totals"][p] or next
      { "party" => p, "name" => PARTY_NAMES[p], "yes" => t.fetch("yes", 0), "no" => t.fetch("no", 0),
        "present" => t.fetch("present", 0), "not_voting" => t.fetch("not_voting", 0),
        "other" => t.fetch("other", 0) }
    end

    against = doc["against_party_majority"].map do |a|
      m = members_by_id[a["bioguide_id"]] || {}
      caucus = m["caucus_party"]
      majority = doc["caucus_majority_position"][caucus]
      { "name" => member_name(m), "url" => member_url(a["bioguide_id"]),
        "code" => "#{m["party"]}-#{seat(m)}", "position" => a["position"],
        "caucus" => caucus, "majority" => majority && words[majority],
        "sort" => [m["last_name"].to_s, m["first_name"].to_s] }
    end.sort_by { |a| a.delete("sort") }

    # Party and seat when the measure was introduced; the member's latest in data without those columns.
    introduced = vote["sponsor_party"] && %w[party chamber state district].to_h { |k| [k, vote["sponsor_#{k}"]] }
    sponsor = (m = latest_by_id[vote["sponsor_bioguide_id"]]) && {
      "name" => member_name(m), "url" => member_url(m["bioguide_id"]),
      "code" => "#{(introduced || m)["party"]}-#{seat(introduced || m)}"
    }

    {
      "vote" => vote, "words" => words, "sponsor" => sponsor, "tally" => tally, "has_other" => !other.empty?,
      "total" => total, "yes_pct" => pct.call(counts["yes"]), "no_pct" => pct.call(counts["no"]),
      "by_party" => by_party, "party_grid" => other.empty? ? party_grid(by_party, words) : [],
      "state_map" => other.empty? ? state_map(vote["chamber"], doc["positions"], members_by_id, words) : nil,
      "against" => against, "share" => SHARE_WORDS[vote["required_share"]],
      "summary" => summary_view(doc["summary"]),
      "bill_path" => bill_path_view(doc["path"])
    }
  end

  class VotePage < Jekyll::PageWithoutAFile
    def initialize(site, view, rows)
      vote = view["vote"]
      super(site, site.source, vote["url"], "index.html")
      data.merge!(view)
      data["layout"] = "vote"
      data["title"] = "#{CHAMBER_NAMES[vote["chamber"]]} roll call #{vote["roll_number"]}, #{vote["vote_date"]}"
      # Link cards lead with the official title, as the page's heading does (vote_title.html).
      # Same fallback as there: blank and whitespace-only titles are skipped.
      data["og_title"] = [vote["measure_title"], vote["vote_title"], vote["question"]].map { |t| t.to_s.strip }.find { |t| !t.empty? }
      data["description"] = Yan.vote_description(view)
      card = "#{site.config.fetch("yan_cards", "assets/cards")}/#{vote["vote_id"]}.png"
      if File.exist?(File.join(site.source, card))
        data["og_image"] = "/#{card}"
        data["og_image_alt"] = "#{data["og_title"]}: #{data["description"]}"
      end
      data["nav"] = "votes"
      data["rows"] = rows
      data["states"] = rows.map { |r| r["state"] }.uniq.sort
      # Record order: Yea, Nay, Present, Not Voting (candidates first in a Speaker election).
      data["position_options"] = view["tally"].map { |t| t["label"] } & rows.map { |r| r["position"] }
    end
  end

  class MemberPage < Jekyll::PageWithoutAFile
    def initialize(site, member, recent, bills)
      super(site, site.source, member["url"], "index.html")
      data.merge!(bills)
      data["layout"] = "member"
      data["title"] = member["name"]
      data["nav"] = "members"
      data["member"] = member
      data["recent"] = recent
    end
  end

  # /activity/rollcalls.json (Yan.activity_votes), as plain JSON with no layout.
  class ActivityVotesFile < Jekyll::PageWithoutAFile
    def initialize(site, rows)
      super(site, site.source, "activity", "rollcalls.json")
      self.content = JSON.generate({ "votes" => rows })
      data["layout"] = nil
      data["sitemap"] = false
      # Titles are data: a "{{" in one must not run as Liquid.
      data["render_with_liquid"] = false
    end
  end

  class Generator < Jekyll::Generator
    safe true
    priority :highest

    RECENT_VOTES = 50

    def generate(site)
      dir = File.expand_path(site.config.fetch("yan_data", "../data/out"), site.source)
      read = ->(path) { JSON.parse(File.read(File.join(dir, path))) }
      read_optional = ->(path) { File.exist?(File.join(dir, path)) ? read.call(path) : nil }

      meta = read.call("meta.json")
      members = read.call("members.json")["members"]
      votes = read.call("votes.json")["votes"]

      members.each do |m|
        MEMBER_LINKS.each { |key| m[key] = Yan.web_url(m[key]) if m.key?(key) }
        m["url"] = Yan.member_url(m["bioguide_id"])
        m["name"] = Yan.member_name(m)
        m["seat"] = Yan.seat(m)
        m["party_name"] = PARTY_NAMES[m["party"]]
        m["state_name"] = STATE_NAMES.fetch(m["state"], m["state"])
        m["initials"] = "#{m["first_name"].to_s[0]}#{m["last_name"].to_s[0]}"
        m["chamber_name"] = m["chamber"] == "senate" ? "U.S. Senate" : "U.S. House"
        m["where"] = Yan.where(m)
        m["service_line"] = Yan.service_line(m)
        m["accounts"] = Yan.accounts(m)
        m["website_label"] = Yan.website_label(m["website_url"])
        # Exports before per-Congress stats had neither field: their stats are meta's Congress.
        m["last_congress"] ||= meta["congress"]
        m["earlier_congresses"] = (m["congresses"] || []).select do |c|
          c["congress"].to_i != m["last_congress"].to_i && c["roll_calls"]
        end
      end
      medians = Yan.chamber_medians(members, meta["congress"])
      Yan.median_members(members, meta["congress"]).each_value { |ms| ms.each { |m| m["in_median"] = true } }
      members.each { |m| m["median"] = medians[m["chamber"]] if m["last_congress"].to_i == meta["congress"].to_i }
      members.sort_by! { |m| [m["last_name"].to_s, m["first_name"].to_s, m["bioguide_id"]] }
      by_id = members.to_h { |m| [m["bioguide_id"], m] }

      positions_by_member = Hash.new { |h, k| h[k] = [] }
      views = {}
      votes.each do |v|
        v["url"] = Yan.vote_url(v)
        v["source_url"] = Yan.web_url(v["source_url"])
        v["congress_gov_url"] = Yan.web_url(v["congress_gov_url"])
        v["congress_gov_text_url"] = Yan.text_url(v["congress_gov_url"])
        v["chamber_name"] = CHAMBER_NAMES[v["chamber"]]
        v["procedure"] = Yan.procedure(v, site.data["procedures"] || {})
        doc = read.call("votes/#{v["vote_id"]}.json")
        as_of = Yan.members_as_of(doc, by_id)
        v["result_label"] = Yan.result_label(v, as_of)
        view = Yan.vote_view(v, doc, as_of, by_id)
        # The vote page map's shapes (scripts/build_vote_map.py); the table shows either way.
        # A file without members_as_of_vote has only latest districts, so just meta's Congress gets a map.
        map_src = "/assets/maps/#{v["congress"].to_i}.json"
        seats_known = doc.key?("members_as_of_vote") || v["congress"].to_i == meta["congress"].to_i
        if view["state_map"] && seats_known && File.exist?(File.join(site.source, map_src))
          view["state_map"]["src"] = map_src
        end
        views[v["vote_id"]] = view

        against_ids = doc["against_party_majority"].to_h { |a| [a["bioguide_id"], true] }
        rows = doc["positions"].map do |id, raw|
          m = as_of[id] || {}
          kind = Yan.position_kind(raw)
          positions_by_member[id] << { "vote" => v, "position" => raw, "against" => against_ids.key?(id),
                                       "caucus" => m["caucus_party"],
                                       "majority" => (mp = doc["caucus_majority_position"][m["caucus_party"]]) && view["words"][mp] }
          { "id" => id, "name" => m["name"], "sort" => [m["last_name"].to_s, m["first_name"].to_s],
            "party" => m["party"], "state" => m["state"], "seat" => m["seat"],
            "position" => raw, "mark" => MARKS[kind] }
        end
        rows.sort_by! { |r| r["sort"] }
        rows.each { |r| r.delete("sort") }
        site.pages << VotePage.new(site, view, rows)
      end

      votes_by_id = votes.to_h { |v| [v["vote_id"], v] }
      chamber_months = Yan.chamber_months(votes)

      # Newest first already (votes.json order), so each member's list is too.
      members.each do |m|
        list = positions_by_member[m["bioguide_id"]]
        next if list.empty?

        recent = list.each_with_index.select { |p, i| i < RECENT_VOTES || p["against"] }.map do |p, i|
          p.merge("recent" => i < RECENT_VOTES)
        end
        bills = read_optional.call("members/#{m["bioguide_id"]}.json") || {}
        # The last Congress's list is nil until first fetched; the page leaves it out, and
        # shows only earlier Congresses' lists, if any.
        lists = %w[sponsored cosponsored].each_with_object({}) do |kind, h|
          h[kind] = Yan.congress_bills(bills[kind], m["last_congress"])
          h["#{kind}_earlier"] = Yan.earlier_congress_bills(bills[kind], m["last_congress"])
        end
        [*lists["sponsored"], *lists["cosponsored"],
         *(lists["sponsored_earlier"] + lists["cosponsored_earlier"]).flat_map { |g| g["bills"] }].each do |b|
          b["congress_gov_url"] = Yan.web_url(b["congress_gov_url"])
          vote = b["latest_vote_id"] && votes_by_id[b["latest_vote_id"]]
          b["vote_url"] = vote && vote["url"]
        end
        lists["sponsored_areas"] = Yan.member_areas(lists["sponsored"])
        lists["cosponsored_areas"] = Yan.member_areas(lists["cosponsored"])
        lists["bio"] = Yan.member_bio(bills["bio"])
        congress = m["last_congress"].to_i
        lists["months"] = Yan.member_months(list.select { |p| p["vote"]["congress"].to_i == congress && p["vote"]["chamber"] == m["chamber"] },
                                            chamber_months[[m["chamber"], congress]])
        m["has_page"] = true
        site.pages << MemberPage.new(site, m, recent, lists)
      end

      # Absent until the pipeline first ingests the floor schedules.
      schedule = read_optional.call("floor_schedule.json") || { "items" => [] }
      schedule["items"].each { |item| item["congress_gov_url"] = Yan.web_url(item["congress_gov_url"]) }
      site.data["schedule"] = Yan.schedule_view(schedule, votes_by_id, site.time)
      site.data["live_floor"] = Yan.live_floor(schedule["floor_status"])
      # site.time is Eastern (timezone in _config.yml), the floor's own clock.
      site.data["schedule_calendar"] = Yan.schedule_calendar(site.data["schedule"], votes, site.time,
                                                             schedule["senate_next_convene_et"])

      site.data["meta"] = meta
      site.data["dictionary"] = Yan.dictionary(site.data["procedures"] || {})
      site.data["members"] = members
      map_file = File.join(site.source, "_maps", "#{meta["congress"]}.json")
      site.data["district_map"] = Yan.district_map(File.exist?(map_file) && JSON.parse(File.read(map_file)), members)
      # The map's ZIP code lookup (scripts/build_zip_lookup.py), fetched by the browser on a search.
      zip_file = "/assets/maps/zip-#{meta["congress"]}.json"
      site.data["zip_lookup"] = zip_file if File.exist?(File.join(site.source, zip_file))
      site.data["votes"] = votes
      site.data["vote_volume"] = Yan.vote_volume(votes)
      site.data["policy_volume"] = Yan.policy_volume(votes)
      site.pages << ActivityVotesFile.new(site, Yan.activity_votes(votes))
      site.data["leads"] = {
        "all" => views[votes.first["vote_id"]],
        "house" => (v = votes.find { |x| x["chamber"] == "house" }) && views[v["vote_id"]],
        "senate" => (v = votes.find { |x| x["chamber"] == "senate" }) && views[v["vote_id"]]
      }
      site.data["home"] = {
        "week" => Yan.home_week(site.data["vote_volume"]),
        "closest" => Yan.closest_votes(votes, views),
        "against" => Yan.against_votes(votes, views),
        "areas" => Yan.home_areas(site.data["policy_volume"])
      }
    end
  end

  module Filters
    AP_MONTHS = %w[Jan. Feb. March April May June July Aug. Sept. Oct. Nov. Dec.].freeze

    # AP style date: "Nov. 10, 2026".
    def ap_date(input)
      d = input.is_a?(String) ? Date.parse(input) : input.to_date
      "#{AP_MONTHS[d.month - 1]} #{d.day}, #{d.year}"
    end

    def self.ap_date(input) = Object.new.extend(self).ap_date(input)

    # 4 -> "4th"
    def self.ordinal(n) = Object.new.extend(self).ordinal(n)

    def ordinal(n)
      n = n.to_i
      suffix = (11..13).cover?(n % 100) ? "th" : { 1 => "st", 2 => "nd", 3 => "rd" }.fetch(n % 10, "th")
      "#{n}#{suffix}"
    end
  end
end

Liquid::Template.register_filter(Yan::Filters)
