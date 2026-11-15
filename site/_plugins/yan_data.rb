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

  # Legend mark for a position: Yea solid, Nay striped, Not voting open box.
  MARKS = { "yes" => "yea", "no" => "nay", "present" => "present", "not_voting" => "nv" }.freeze

  # The House records a bare "Passed", "Failed" or "Agreed to", which on its
  # own reads as the fate of the measure. Tie it to the question voted on:
  # "Motion to Refer: Passed". Senate results already name their subject
  # ("Motion to Proceed Agreed to", "Nomination Confirmed").
  BARE_RESULTS = ["Passed", "Failed", "Agreed to"].freeze

  def self.result_label(v)
    return v["result"] unless BARE_RESULTS.include?(v["result"])

    "#{v["question"].sub(/\AOn (the )?/, "")}: #{v["result"]}"
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
    { "key" => q["key"], "term" => q["term"], "definition" => q["definition"],
      "measure_note" => (%w[passage suspend].include?(q["key"]) && note) ? note["definition"] : nil }
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

  # The floor schedule for display. Each item links to its roll call once
  # there is one (else to Congress.gov, when it's a bill or resolution).
  # "Coming up" lists items without a roll call yet, and for the House only
  # the newest published week: by the time the next week's schedule is out,
  # the current week's floor business is mostly done.
  def self.schedule_view(schedule, votes_by_id)
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
    next_convene = schedule["senate_next_convene_et"]
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
  def self.schedule_calendar(view, votes, today, next_convene_iso)
    monday = ->(d) { d - ((d.wday - 1) % 7) }
    this_week = monday.call(today)
    convene = next_convene_iso && DateTime.strptime(next_convene_iso, "%Y-%m-%dT%H:%M:%S")
    # A failed fetch can leave a convene time that has already passed.
    convene = nil if convene && convene.to_date < today
    house_weeks = (view["house_weeks"] || []).select { |w| w["week_date"] }
    listed_weeks = [convene && monday.call(convene.to_date),
                    *house_weeks.map { |w| Date.parse(w["week_date"]) }].compact
    last_week = [this_week, *listed_weeks].max
    first_week = this_week - (7 * CALENDAR_WEEKS_BACK)
    span = (first_week.to_s..(last_week + 6).to_s)
    taken = votes.select { |v| span.cover?(v["vote_date"]) }
                 .sort_by { |v| [v["congress"], v["session"], v["roll_number"]] }
                 .group_by { |v| [v["vote_date"], v["chamber"]] }
    # On a weekend, open on the coming week if anything is listed for it.
    weekend = today.saturday? || today.sunday?
    default = weekend && listed_weeks.include?(this_week + 7) ? this_week + 7 : this_week
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

  def self.vote_url(v)
    "/votes/#{v["congress"]}/#{v["chamber"]}/#{v["session"]}/#{v["roll_number"]}/"
  end

  def self.member_url(id)
    "/members/#{id}/"
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
              ["youtube_url", "YouTube", "youtube"], ["mastodon_url", "Mastodon", "mastodon"]].freeze

  def self.accounts(m)
    ACCOUNTS.filter_map { |key, label, icon| m[key] && { "label" => label, "url" => m[key], "icon" => icon } }
  end

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

  # The By state map and table for one vote. "seats" is what the map draws
  # (site/assets/js/vote-map.js): for each House seat ("KY-4", "WY") or Senate
  # state ("KY"), its members' marks in last-name order and a hover title. DC
  # and the territories aren't on the map (their delegates can't vote on the
  # House floor) but are in the table; "unmapped" counts them, with members of
  # no known state, for a note.
  def self.state_map(chamber, positions, members_by_id, words)
    return nil if positions.empty?

    labels = { "yes" => words["yes"], "no" => words["no"], "present" => "Present", "not_voting" => "Not voting" }
    house = chamber == "house"
    counts = Hash.new { |h, k| h[k] = Hash.new(0) }
    seats = {}
    unmapped = 0
    positions.sort_by { |id, _| [members_by_id.dig(id, "last_name").to_s, id] }.each do |id, raw|
      m = members_by_id[id] || {}
      kind = position_kind(raw)
      counts[m["state"]][kind] += 1 if STATE_NAMES.key?(m["state"])
      # A member's record holds their latest seat: someone who has since moved
      # to the Senate has no district for a House vote, so they stay off the map.
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
      "procedures" => %w[passage suspend concur concur_amendment veto_override] },
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
  def self.vote_volume(votes)
    return nil if votes.empty?

    week_of = ->(v) { d = Date.parse(v["vote_date"]); d - ((d.wday + 6) % 7) }
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
          # A 1px surface gap above each segment; a single roll call stays visible.
          { "kind" => k["key"], "y" => (y + 1).round(1), "h" => [h - 1, 1].max.round(1) }
        end
        total = c.values.sum
        parts = VOTE_KINDS.filter_map { |k| "#{k["label"]} #{c[k["key"]]}" if c[k["key"]].positive? }
        { "start" => start.iso8601, "x" => i * VOLUME_SLOT, "total" => total, "segments" => segments,
          "counts" => VOTE_KINDS.to_h { |k| [k["key"], c.fetch(k["key"], 0)] },
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
  # carries policy_area.
  def self.policy_volume(votes)
    return nil unless votes.any? { |v| v.key?("policy_area") }

    counts = Hash.new { |h, k| h[k] = Hash.new(0) }
    votes.each { |v| counts[[policy_row(v), v["chamber"]]][vote_kind(v.dig("procedure", "key"))] += 1 }
    rows = counts.keys.map(&:first).uniq
    total = ->(row, chamber = nil) { counts.sum { |(r, c), k| r == row && (chamber.nil? || c == chamber) ? k.values.sum : 0 } }
    areas = (rows - NO_AREA).sort_by { |r| [-total.call(r), r] }
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

  # Everything the tally, by-party and against-majority blocks need for one vote.
  def self.vote_view(vote, doc, members_by_id)
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

    sponsor = (m = members_by_id[vote["sponsor_bioguide_id"]]) && {
      "name" => member_name(m), "url" => member_url(m["bioguide_id"]), "code" => "#{m["party"]}-#{seat(m)}"
    }

    {
      "vote" => vote, "words" => words, "sponsor" => sponsor, "tally" => tally, "has_other" => !other.empty?,
      "total" => total, "yes_pct" => pct.call(counts["yes"]), "no_pct" => pct.call(counts["no"]),
      "by_party" => by_party, "party_grid" => other.empty? ? party_grid(by_party, words) : [],
      "state_map" => other.empty? ? state_map(vote["chamber"], doc["positions"], members_by_id, words) : nil,
      "against" => against, "summary" => doc["summary"]
    }
  end

  class VotePage < Jekyll::PageWithoutAFile
    def initialize(site, view, rows)
      vote = view["vote"]
      super(site, site.source, vote["url"], "index.html")
      data.merge!(view)
      data["layout"] = "vote"
      data["title"] = "#{CHAMBER_NAMES[vote["chamber"]]} roll call #{vote["roll_number"]}, #{vote["vote_date"]}"
      data["nav"] = "votes"
      data["rows"] = rows
      data["states"] = rows.map { |r| r["state"] }.uniq.sort
      # Record order: Yea, Nay, Present, Not Voting (candidates first in a Speaker election).
      data["position_options"] = view["tally"].map { |t| t["label"] } & rows.map { |r| r["position"] }
    end
  end

  class MemberPage < Jekyll::PageWithoutAFile
    def initialize(site, member, recent, sponsored, cosponsored)
      super(site, site.source, member["url"], "index.html")
      data["sponsored"] = sponsored
      data["cosponsored"] = cosponsored
      data["layout"] = "member"
      data["title"] = member["name"]
      data["nav"] = "members"
      data["member"] = member
      data["recent"] = recent
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
        m["url"] = Yan.member_url(m["bioguide_id"])
        m["name"] = Yan.member_name(m)
        m["seat"] = Yan.seat(m)
        m["party_name"] = PARTY_NAMES[m["party"]]
        m["state_name"] = STATE_NAMES.fetch(m["state"], m["state"])
        m["initials"] = "#{m["first_name"].to_s[0]}#{m["last_name"].to_s[0]}"
        m["chamber_name"] = m["chamber"] == "senate" ? "U.S. Senate" : "U.S. House"
        m["where"] = Yan.where(m)
        m["accounts"] = Yan.accounts(m)
        m["website_label"] = Yan.website_label(m["website_url"])
      end
      members.sort_by! { |m| [m["last_name"].to_s, m["first_name"].to_s, m["bioguide_id"]] }
      by_id = members.to_h { |m| [m["bioguide_id"], m] }

      positions_by_member = Hash.new { |h, k| h[k] = [] }
      views = {}
      votes.each do |v|
        v["url"] = Yan.vote_url(v)
        v["chamber_name"] = CHAMBER_NAMES[v["chamber"]]
        v["result_label"] = Yan.result_label(v)
        v["procedure"] = Yan.procedure(v, site.data["procedures"] || {})
        doc = read.call("votes/#{v["vote_id"]}.json")
        view = Yan.vote_view(v, doc, by_id)
        # The By state map's shapes (scripts/build_vote_map.py); the table shows either way.
        # Members' districts are as of meta's Congress, so only its votes get a map.
        map_src = "/assets/maps/#{v["congress"].to_i}.json"
        if view["state_map"] && v["congress"].to_i == meta["congress"].to_i && File.exist?(File.join(site.source, map_src))
          view["state_map"]["src"] = map_src
        end
        views[v["vote_id"]] = view

        against_ids = doc["against_party_majority"].to_h { |a| [a["bioguide_id"], true] }
        rows = doc["positions"].map do |id, raw|
          m = by_id[id] || {}
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

      # Newest first already (votes.json order), so each member's list is too.
      members.each do |m|
        list = positions_by_member[m["bioguide_id"]]
        next if list.empty?

        recent = list.each_with_index.select { |p, i| i < RECENT_VOTES || p["against"] }.map do |p, i|
          p.merge("recent" => i < RECENT_VOTES)
        end
        bills = read_optional.call("members/#{m["bioguide_id"]}.json") || {}
        sponsored = bills.fetch("sponsored", [])
        # Nil until the member's cosponsored list is first fetched; the page leaves the section out.
        cosponsored = bills["cosponsored"]
        [*sponsored, *cosponsored].each do |b|
          vote = b["latest_vote_id"] && votes_by_id[b["latest_vote_id"]]
          b["vote_url"] = vote && vote["url"]
        end
        site.pages << MemberPage.new(site, m, recent, sponsored, cosponsored)
      end

      # Absent until the pipeline first ingests the floor schedules.
      schedule = read_optional.call("floor_schedule.json") || { "items" => [] }
      site.data["schedule"] = Yan.schedule_view(schedule, votes_by_id)
      # site.time is Eastern (timezone in _config.yml), the floor's own clock.
      site.data["schedule_calendar"] = Yan.schedule_calendar(site.data["schedule"], votes, site.time.to_date,
                                                             schedule["senate_next_convene_et"])

      site.data["meta"] = meta
      site.data["members"] = members
      map_file = File.join(site.source, "_maps", "#{meta["congress"]}.json")
      site.data["district_map"] = Yan.district_map(File.exist?(map_file) && JSON.parse(File.read(map_file)), members)
      site.data["votes"] = votes
      site.data["vote_volume"] = Yan.vote_volume(votes)
      site.data["policy_volume"] = Yan.policy_volume(votes)
      site.data["leads"] = {
        "all" => views[votes.first["vote_id"]],
        "house" => (v = votes.find { |x| x["chamber"] == "house" }) && views[v["vote_id"]],
        "senate" => (v = votes.find { |x| x["chamber"] == "senate" }) && views[v["vote_id"]]
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
