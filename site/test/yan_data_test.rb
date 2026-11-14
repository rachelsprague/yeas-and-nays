# Tests for _plugins/yan_data.rb. Run with `make sitetest`.

require "minitest/autorun"
require "jekyll"
require "yaml"
require "json"
require "tmpdir"
require "fileutils"
require_relative "../_plugins/yan_data"

class ProcedureTest < Minitest::Test
  PROCEDURES = YAML.load_file(File.expand_path("../_data/procedures.yml", __dir__))

  def key(question, measure_title: nil, bill_type: nil)
    Yan.procedure({ "question" => question, "measure_title" => measure_title, "bill_type" => bill_type },
                  PROCEDURES)&.fetch("key")
  end

  def test_rule_needs_a_consideration_title
    assert_equal "rule", key("On Agreeing to the Resolution",
                             measure_title: "Providing for consideration of the bill (H.R. 1)")
    assert_equal "passage", key("On Agreeing to the Resolution", measure_title: "Expressing support for X")
  end

  def test_specific_patterns_win_over_general_ones
    assert_equal "concur_amendment", key("On Motion to Concur in the Senate Amendment with an Amendment")
    assert_equal "concur", key("On Motion to Concur in the Senate Amendment")
    assert_equal "suspend", key("On Motion to Suspend the Rules and Pass, as Amended")
    assert_equal "table", key("On Motion to Table the Motion to Reconsider")
    assert_equal "cloture", key("On the Cloture Motion")
  end

  def test_matching_ignores_case
    assert_equal "previous_question", key("ON ORDERING THE PREVIOUS QUESTION")
  end

  def test_quorum_calls
    assert_equal "quorum", key("Call of the House")
    assert_equal "quorum_states", key("Call by States")
  end

  def test_retaining_divisions
    assert_equal "retain_division", key("On Retaining Division A")
    assert_equal "retain_division", key("On Retaining Divisions B and C")
  end

  def test_unknown_question_has_no_definition
    assert_nil key("On Something New")
    assert_nil key(nil)
  end

  def test_measure_note_only_on_passage_votes
    passage = Yan.procedure({ "question" => "On Passage", "bill_type" => "hr" }, PROCEDURES)
    assert_match(/\ABills become law/, passage["measure_note"])

    suspend = Yan.procedure({ "question" => "On Motion to Suspend the Rules and Pass", "bill_type" => "hres" },
                            PROCEDURES)
    assert_match(/\ASimple resolutions/, suspend["measure_note"])

    assert_nil Yan.procedure({ "question" => "On Motion to Recommit", "bill_type" => "hr" },
                             PROCEDURES)["measure_note"]
    assert_nil Yan.procedure({ "question" => "On the Nomination", "bill_type" => nil }, PROCEDURES)["measure_note"]
  end

  def test_empty_procedures
    assert_nil Yan.procedure({ "question" => "On Passage" }, {})
  end
end

# Builds the site from a one-member, one-vote export whose member name holds
# double quotes, then checks every page escapes them (attributes included).
class EscapingTest < Minitest::Test
  SOURCE = File.expand_path("..", __dir__)

  MEMBER = {
    "bioguide_id" => "Z000001", "official_full_name" => 'Jane "JJ" Doe', "first_name" => "Jane",
    "last_name" => "Doe", "party" => "R", "caucus_party" => "R", "chamber" => "house", "state" => "AL",
    "district" => 4, "is_current" => true, "is_voting_member" => true
  }.freeze

  VOTE = {
    "vote_id" => "h119-1-0001", "congress" => 119, "chamber" => "house", "session" => 1, "roll_number" => 1,
    "vote_date" => "2025-01-03", "question" => "On Passage", "result" => "Passed", "bill_type" => "hr",
    "measure_title" => "A bill", "sponsor_bioguide_id" => "Z000001"
  }.freeze

  # Returns { "/path/index.html" => html } for every page built.
  def build
    Dir.mktmpdir do |tmp|
      data = File.join(tmp, "data")
      FileUtils.mkdir_p([File.join(data, "votes"), File.join(data, "members")])
      write = ->(path, obj) { File.write(File.join(data, path), JSON.generate(obj)) }
      write.call("meta.json", { "congress" => 119, "has_sponsored_bills" => true })
      write.call("members.json", { "members" => [MEMBER] })
      write.call("votes.json", { "votes" => [VOTE] })
      write.call("votes/#{VOTE["vote_id"]}.json", {
        "positions" => { "Z000001" => "Nay" }, "party_totals" => { "R" => { "no" => 1 } },
        # A caucus majority the member voted against, so the against-majority lists name them.
        "caucus_majority_position" => { "R" => "yes" },
        "against_party_majority" => [{ "bioguide_id" => "Z000001", "position" => "Nay" }], "summary" => nil
      })
      write.call("members/Z000001.json", { "sponsored" => [], "cosponsored" => [] })

      site = Jekyll::Site.new(Jekyll.configuration(
        "source" => SOURCE, "destination" => File.join(tmp, "_site"), "yan_data" => data,
        "plugins_dir" => File.join(tmp, "none"), # yan_data.rb is already loaded above
        "quiet" => true
      ))
      site.process
      Dir[File.join(tmp, "_site", "**", "*.html")].to_h { |f| [f.delete_prefix("#{tmp}/_site"), File.read(f)] }
    end
  end

  def test_member_name_quotes_are_escaped
    pages = build.select { |_, html| html.match?(/jj/i) }
    assert_includes pages.keys, "/members/Z000001/index.html"
    assert_includes pages.keys, "/members/index.html"
    assert_includes pages.keys, "/votes/119/house/1/1/index.html"
    assert_includes pages.keys, "/index.html"

    pages.each do |path, html|
      html.scan(/.?jj.?/i).each do |hit|
        assert_match(/\A;jj&\z/i, hit, "#{path}: member name quotes not escaped")
      end
    end
  end
end

class ScheduleTest < Minitest::Test
  def test_category_drops_the_house_lead_in
    assert_equal "Under suspension of the rules",
                 Yan.schedule_category("Items that may be considered under suspension of the rules")
    assert_equal "Pursuant to a rule", Yan.schedule_category("Items that may be considered pursuant to a rule")
    assert_nil Yan.schedule_category("Items that may be considered")
    assert_nil Yan.schedule_category(nil)
  end

  def test_convene_label
    assert_equal "Monday, Nov. 16, 2026, at 3 p.m. ET", Yan.convene_label("2026-11-16T15:00:00")
    assert_equal "Thursday, Nov. 12, 2026, at noon ET", Yan.convene_label("2026-11-12T12:00:00")
    assert_equal "Tuesday, Nov. 17, 2026, at 10:30 a.m. ET", Yan.convene_label("2026-11-17T10:30:00")
  end

  def item(chamber, id, week: nil, vote_id: nil)
    { "chamber" => chamber, "item_id" => id, "week_date" => week, "vote_id" => vote_id,
      "category" => "Items that may be considered under suspension of the rules" }
  end

  def test_coming_up_skips_voted_items_and_earlier_house_weeks
    votes = { "h1" => { "url" => "/votes/119/house/2/1/", "result_label" => "Passed" } }
    view = Yan.schedule_view({ "items" => [
      item("house", "a", week: "2026-11-09"),
      item("house", "b", week: "2026-11-16", vote_id: "h1"),
      item("house", "c", week: "2026-11-16"),
      item("senate", "d"),
      item("senate", "e", vote_id: "s9")
    ], "senate_next_convene_et" => "2026-11-16T15:00:00" }, votes)

    assert_equal ["c"], view["upcoming_house"].map { |i| i["item_id"] }
    assert_equal "2026-11-16", view["upcoming_week"]
    assert_equal ["d"], view["upcoming_senate"].map { |i| i["item_id"] }
    assert_equal ["2026-11-09", "2026-11-16"], view["house_weeks"].map { |w| w["week_date"] }
    voted = view["house_weeks"].last["groups"].first["items"].first
    assert_equal ["/votes/119/house/2/1/", "Passed"], [voted["vote_url"], voted["result_label"]]
    assert_equal "Monday, Nov. 16, 2026, at 3 p.m. ET", view["senate_next_convene"]
  end

  def test_senate_items_without_a_house_schedule
    view = Yan.schedule_view({ "items" => [item("senate", "d")] }, {})
    assert_equal [["d"], [], nil, []],
                 [view["upcoming_senate"].map { |i| i["item_id"] }, view["upcoming_house"], view["upcoming_week"],
                  view["house_weeks"]]
  end

  def test_empty_schedule
    view = Yan.schedule_view({ "items" => [] }, {})
    assert_equal [[], [], nil, nil], view.values_at("upcoming_house", "upcoming_senate", "upcoming_week",
                                                   "senate_next_convene")
  end
end

class ScheduleCalendarTest < Minitest::Test
  FRIDAY = Date.new(2026, 11, 13)

  def vote(id, date, chamber, roll)
    { "vote_id" => id, "vote_date" => date, "chamber" => chamber, "roll_number" => roll,
      "url" => "/votes/#{id}/", "measure_label" => "H.R. #{roll}", "question" => "On Passage",
      "result_label" => "Passage: Passed" }
  end

  def item(chamber, id, week: nil, vote_id: nil)
    { "chamber" => chamber, "item_id" => id, "week_date" => week, "vote_id" => vote_id,
      "category" => "Items that may be considered under suspension of the rules" }
  end

  def calendar(items, votes, today = FRIDAY, convene = "2026-11-16T15:00:00")
    view = Yan.schedule_view({ "items" => items, "senate_next_convene_et" => convene }, {})
    Yan.schedule_calendar(view, votes, today, convene)
  end

  def week(cal, date) = cal["weeks"].find { |w| w["week_date"] == date }

  def test_weeks_run_from_two_back_through_the_latest_scheduled_week
    cal = calendar([item("house", "a", week: "2026-11-16")], [])
    assert_equal %w[2026-10-26 2026-11-02 2026-11-09 2026-11-16], cal["weeks"].map { |w| w["week_date"] }
    assert_equal ["Oct. 26", "Nov. 2", "This week", "Next week"], cal["weeks"].map { |w| w["tab"] }
    assert_equal "2026-11-09", cal["default_week"]
  end

  def test_roll_calls_go_on_their_day_in_roll_order
    cal = calendar([], [vote("h2", "2026-11-10", "house", 316), vote("h1", "2026-11-10", "house", 315),
                        vote("s1", "2026-11-12", "senate", 262), vote("old", "2026-09-01", "house", 1)])
    days = week(cal, "2026-11-09")["days"]
    assert_equal %w[Mon Tue Wed Thu Fri], days.map { |d| d["weekday"] }
    assert_equal ["H.R. 315", "H.R. 316"], days[1]["house"].map { |v| v["label"] }
    assert_equal ["/votes/s1/"], days[3]["senate"].map { |v| v["url"] }
    assert_equal 3, week(cal, "2026-11-09")["roll_calls"]
    assert_equal %w[past past past past today], days.map { |d| d["when"] }
  end

  def test_weekend_days_only_when_something_is_on_them
    cal = calendar([], [vote("s1", "2026-11-07", "senate", 250)], FRIDAY, "2026-11-15T13:00:00")
    assert_equal %w[Mon Tue Wed Thu Fri Sat], week(cal, "2026-11-02")["days"].map { |d| d["weekday"] }
    sunday = week(cal, "2026-11-09")["days"].last
    assert_equal ["Sun", "1 p.m. ET"], sunday.values_at("weekday", "convene")
  end

  def test_pending_items_sit_under_their_week
    cal = calendar([item("house", "a", week: "2026-11-09"), item("house", "b", week: "2026-11-09", vote_id: "h1"),
                    item("house", "c", week: "2026-11-16"), item("senate", "d")], [])
    assert_equal ["a"], week(cal, "2026-11-09")["house_pending"].flat_map { |g| g["items"].map { |i| i["item_id"] } }
    assert_equal ["c"], week(cal, "2026-11-16")["house_pending"].flat_map { |g| g["items"].map { |i| i["item_id"] } }
    # Pending cloture motions go in the week the Senate next convenes.
    assert_equal [[], ["d"]], [week(cal, "2026-11-09")["senate_pending"],
                               week(cal, "2026-11-16")["senate_pending"].map { |i| i["item_id"] }]
  end

  def test_past_weeks_list_nothing_pending
    cal = calendar([item("house", "a", week: "2026-11-02")], [], FRIDAY, nil)
    assert_equal [], week(cal, "2026-11-02")["house_pending"]
    saturday = calendar([item("house", "a", week: "2026-11-09")], [], Date.new(2026, 11, 14), nil)
    assert_equal [], week(saturday, "2026-11-09")["house_pending"]
    assert_equal ["d"], calendar([item("senate", "d")], [], FRIDAY, nil)["weeks"].last["senate_pending"].map { |i| i["item_id"] }
  end

  def test_a_convene_time_already_past_is_dropped
    cal = calendar([], [], FRIDAY, "2026-11-12T10:00:00")
    assert_equal "2026-11-09", cal["weeks"].last["week_date"]
    assert(cal["weeks"].flat_map { |w| w["days"] }.none? { |d| d["convene"] })
  end

  def test_weekend_opens_on_the_coming_week_when_it_has_something_listed
    saturday = Date.new(2026, 11, 14)
    assert_equal "2026-11-16", calendar([], [], saturday)["default_week"]
    assert_equal "2026-11-09", calendar([], [], saturday, nil)["default_week"]
    # A recess: the Senate next convenes weeks out, so open on this week.
    assert_equal "2026-11-09", calendar([], [], saturday, "2026-12-07T15:00:00")["default_week"]
  end

  def test_without_a_convene_time_cloture_motions_go_in_the_opening_week
    saturday = Date.new(2026, 11, 14)
    cal = calendar([item("house", "a", week: "2026-11-16"), item("senate", "d")], [], saturday, nil)
    assert_equal "2026-11-16", cal["default_week"]
    assert_equal ["d"], week(cal, "2026-11-16")["senate_pending"].map { |i| i["item_id"] }
  end

  def test_a_day_spanning_two_sessions_lists_the_earlier_session_first
    v1 = vote("a", "2027-01-03", "house", 700).merge("congress" => 119, "session" => 2)
    v2 = vote("b", "2027-01-03", "house", 1).merge("congress" => 119, "session" => 3)
    cal = calendar([], [v2, v1], Date.new(2027, 1, 4), nil)
    sunday = week(cal, "2026-12-28")["days"].last
    assert_equal ["/votes/a/", "/votes/b/"], sunday["house"].map { |v| v["url"] }
  end

  def test_a_house_week_without_a_date_is_skipped
    view = { "house_weeks" => [{ "week_date" => nil, "groups" => [] }], "upcoming_senate" => [] }
    cal = Yan.schedule_calendar(view, [], FRIDAY, nil)
    assert_equal "2026-11-09", cal["weeks"].last["week_date"]
  end
end
