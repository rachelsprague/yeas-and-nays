# Loads the pipeline's JSON (data/out/) and generates a page per vote and per
# member. All counts and definitions come from the pipeline; this file only
# joins and arranges them for display.
#
#   site.data["meta"]      data/out/meta.json
#   site.data["votes"]     data/out/votes.json, newest first, each with a url
#   site.data["members"]   data/out/members.json, sorted by name, each with a url
#   site.data["leads"]     the newest vote overall and per chamber, prepared for display
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

  # "2026-11-16T15:00:00" (Eastern) -> "Monday, Nov. 16, 2026, at 3 p.m. ET"
  def self.convene_label(iso)
    t = DateTime.strptime(iso, "%Y-%m-%dT%H:%M:%S")
    clock =
      if t.hour == 12 && t.minute.zero? then "noon"
      else
        hour = t.hour % 12
        hour = 12 if hour.zero?
        "#{hour}#{t.minute.zero? ? "" : format(":%02d", t.minute)} #{t.hour < 12 ? "a.m." : "p.m."}"
      end
    "#{Date::DAYNAMES[t.wday]}, #{Filters.ap_date(t)}, at #{clock} ET"
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

  # Official social media accounts, in one fixed order for every member.
  ACCOUNTS = [["x_url", "X"], ["facebook_url", "Facebook"], ["instagram_url", "Instagram"],
              ["youtube_url", "YouTube"], ["mastodon_url", "Mastodon"]].freeze

  def self.accounts(m)
    ACCOUNTS.filter_map { |key, label| m[key] && { "label" => label, "url" => m[key] } }
  end

  # The words this vote recorded for yes and no: Yea/Nay, Aye/No or Guilty/Not Guilty.
  def self.words(positions)
    seen = positions.values.uniq
    yes = (%w[Aye Guilty] & seen).first || "Yea"
    no = { "Aye" => "No", "Guilty" => "Not Guilty" }.fetch(yes, "Nay")
    { "yes" => yes, "no" => no }
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
      "by_party" => by_party, "against" => against, "summary" => doc["summary"]
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

      site.data["meta"] = meta
      site.data["members"] = members
      site.data["votes"] = votes
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
