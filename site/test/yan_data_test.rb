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

  # Every question in the exported votes has a definition, so a new kind of
  # vote gets one in procedures.yml rather than showing none.
  def test_every_exported_question_has_a_definition
    votes = JSON.parse(File.read(File.expand_path("../../data/out/votes.json", __dir__)))["votes"]
    assert_empty votes.reject { |v| Yan.procedure(v, PROCEDURES) }.map { |v| v["question"] }.uniq
  end
end

# Builds the site from a small export written to a temp dir.
module SiteBuild
  SOURCE = File.expand_path("..", __dir__)

  # Returns { "/path/index.html" => html } for every page built from these
  # members and [vote, vote file] pairs.
  def build_site(members, votes, files: "*.html")
    Dir.mktmpdir do |tmp|
      data = File.join(tmp, "data")
      FileUtils.mkdir_p([File.join(data, "votes"), File.join(data, "members")])
      write = ->(path, obj) { File.write(File.join(data, path), JSON.generate(obj)) }
      write.call("meta.json", { "congress" => 119, "has_sponsored_bills" => true })
      write.call("members.json", { "members" => members })
      write.call("votes.json", { "votes" => votes.map(&:first) })
      votes.each { |v, doc| write.call("votes/#{v["vote_id"]}.json", doc) }
      members.each { |m| write.call("members/#{m["bioguide_id"]}.json", { "sponsored" => [], "cosponsored" => [] }) }

      site = Jekyll::Site.new(Jekyll.configuration(
        "source" => SOURCE, "destination" => File.join(tmp, "_site"), "yan_data" => data,
        "plugins_dir" => File.join(tmp, "none"), # yan_data.rb is already loaded above
        "quiet" => true
      ))
      site.process
      Dir[File.join(tmp, "_site", "**", files)].to_h { |f| [f.delete_prefix("#{tmp}/_site"), File.read(f)] }
    end
  end
end

# Builds the site from a one-member, one-vote export whose member name and
# measure title hold HTML's special characters (" < > & '), then checks every
# page escapes them (attributes included).
class EscapingTest < Minitest::Test
  include SiteBuild

  MEMBER = {
    "bioguide_id" => "Z000001", "official_full_name" => %q(Jane "JJ" <jj> O'Jay & Doe), "first_name" => "Jane",
    "last_name" => "Doe", "party" => "R", "caucus_party" => "R", "chamber" => "house", "state" => "AL",
    "district" => 4, "is_current" => true, "is_voting_member" => true,
    # Links holding the quoted name too, so the escaping check covers their attributes.
    "website_url" => 'https://example.house.gov/?n="jj"', "phone" => "202-225-0000", "phone_tel" => "+12022250000",
    "office" => "1 Example House Office Building", "x_url" => 'https://x.com/"jj"', "mastodon_url" => "https://example.social/@ex"
  }.freeze

  VOTE = {
    "vote_id" => "h119-1-0001", "congress" => 119, "chamber" => "house", "session" => 1, "roll_number" => 1,
    "vote_date" => "2025-01-03", "question" => "On Passage", "result" => "Passed", "bill_type" => "hr",
    "measure_title" => %q(A bill to name the "KK" <kk> O'Kay & Co Post Office), "sponsor_bioguide_id" => "Z000001",
    # Shows the summary section and its "Introduced by" sponsor line.
    "congress_gov_url" => "https://www.congress.gov/bill/119th-congress/house-bill/1"
  }.freeze

  DOC = {
    "positions" => { "Z000001" => "Nay" }, "party_totals" => { "R" => { "no" => 1 } },
    # A caucus majority the member voted against, so the against-majority lists name them.
    "caucus_majority_position" => { "R" => "yes" },
    "against_party_majority" => [{ "bioguide_id" => "Z000001", "position" => "Nay" }], "summary" => nil
  }.freeze

  def build(member = MEMBER)
    build_site([member], [[VOTE, DOC]])
  end

  def test_member_name_and_measure_title_are_escaped
    built = build
    vote_page = built["/votes/119/house/1/1/index.html"]
    assert_includes vote_page, "Introduced by"
    assert_includes vote_page, "&quot;KK&quot; &lt;kk&gt; O&#39;Kay &amp; Co"
    assert_includes built["/members/Z000001/index.html"], "&quot;JJ&quot; &lt;jj&gt; O&#39;Jay &amp; Doe"
    pages = built.select { |_, html| html.match?(/jj|kk/i) }
    assert_includes pages.keys, "/members/Z000001/index.html"
    assert_includes pages.keys, "/members/index.html"
    assert_includes pages.keys, "/votes/119/house/1/1/index.html"
    assert_includes pages.keys, "/index.html"
    assert_includes pages["/votes/119/house/1/1/index.html"], '<g class="dot nay" fill="url(#hatch-R)">'

    # The district map's card data is JSON in a script tag, where quotes are
    # JSON-escaped rather than HTML-escaped (and "</" can't appear).
    people = %r{<script type="application/json" data-people>(.*?)</script>}m
    find = pages.fetch("/find/index.html")
    assert_equal %q(Jane "JJ" <jj> O'Jay & Doe), JSON.parse(find[people, 1])["AL-4"]["rep"]["name"]
    pages["/find/index.html"] = find.sub(people, "")
    # Likewise the vote page's state map seats.
    seats = %r{<script type="application/json" data-seats>(.*?)</script>}m
    vote = pages.fetch("/votes/119/house/1/1/index.html")
    assert_includes JSON.parse(vote[seats, 1])["AL-4"]["title"], %q(Jane "JJ" <jj> O'Jay & Doe (R))
    pages["/votes/119/house/1/1/index.html"] = vote.sub(seats, "")

    pages.each do |path, html|
      # Escaped, "JJ" and <jj> both read ;jj& (from &quot;JJ&quot; and &lt;jj&gt;).
      html.scan(/.?(?:jj|kk).?/i).each do |hit|
        assert_match(/\A;(jj|kk)&\z/i, hit, "#{path}: quote or angle bracket not escaped")
      end
      ["O'Jay", "O'Kay", "& Doe", "& Co"].each do |raw|
        refute_includes html, raw, "#{path}: apostrophe or ampersand not escaped"
      end
    end
  end

  # The map's size, party codes and city label positions come from our own
  # build, but are escaped anyway; this feeds them HTML's special characters.
  def test_find_page_escapes_map_size_party_and_city_fields
    hostile = %q(1 "ZQ" <zq> O'Qx & Q)
    real = Yan.method(:district_map)
    Yan.define_singleton_method(:district_map) do |map, members|
      real.call(map, members).merge("width" => hostile, "height" => hostile).tap do |m|
        m["districts"].each { |d| d["rep_party"] = hostile }
        m["cities"].each { |c| c.merge!("tier" => hostile, "x" => hostile, "y" => hostile) }
      end
    end
    html = begin
      build.fetch("/find/index.html")
    ensure
      Yan.define_singleton_method(:district_map, real)
    end

    escaped = "1 &quot;ZQ&quot; &lt;zq&gt; O&#39;Qx &amp; Q"
    assert_includes html, %(<svg viewBox="0 0 #{escaped} #{escaped}")
    assert_includes html, "Jane &quot;JJ&quot; &lt;jj&gt; O&#39;Jay &amp; Doe (#{escaped})</title>"
    assert_includes html, %(<g class="city t#{escaped}" transform="translate(#{escaped} #{escaped})">)
    html.scan(/.?zq.?/i).each { |hit| assert_match(/\A;zq&\z/i, hit, "quote or angle bracket not escaped") }
    ["O'Qx", "& Q"].each { |raw| refute_includes html, raw, "apostrophe or ampersand not escaped" }
  end

  # The fixture's Congress (119) uses the real site/_maps/119.json.
  def test_find_page_draws_every_district_linked_to_its_member
    pages = build
    html = pages.fetch("/find/index.html")
    assert_equal 435, html.scan(" data-seat=").size
    assert_match(%r{<a href="/members/Z000001/" tabindex="-1" data-seat="AL-4"><path d="M[^"]+"/><title>Alabama, 4th District: Jane &quot;JJ&quot; &lt;jj&gt; O&#39;Jay &amp; Doe \(R\)</title></a>}, html)
    assert_includes html, '<a href="/members/?state=AL" tabindex="-1" data-seat="AL-1">'
    assert_includes html, "<title>Alabama, 1st District: vacant</title>"
    assert_match(%r{<g class="city t2" transform="translate\([\d.]+ [\d.]+\)"><circle/><text>Long Beach</text></g>}, html)
    # The members page reads ?state= into its State filter by the select's name.
    assert_includes pages.fetch("/members/index.html"), '<select id="m-state" class="field" name="state" data-filter="state">'
    assert_includes pages.fetch("/index.html"), '<a class="small" href="/find/">'
  end

  def test_member_page_lists_official_links
    html = build.fetch("/members/Z000001/index.html")
    assert_includes html, "Official links"
    assert_includes html, '<a class="link" href="tel:+12022250000">202-225-0000</a>'
    assert_includes html, "1 Example House Office Building"
    icons = html[%r{<ul class="account-icons">.*?</ul>}m]
    assert_equal 3, icons.scan(%r{<li><a href="[^"]*" title="[^"]*"><svg viewBox="0 0 24 24"[^>]*><(path|g) }).size
    assert_equal ['https://example.house.gov/?n=&quot;jj&quot;', "https://x.com/&quot;jj&quot;", "https://example.social/@ex"],
                 icons.scan(/<a href="([^"]*)"/).flatten
    assert_equal ["Website (example.house.gov/?n=&quot;jj&quot;)", "X", "Mastodon"],
                 icons.scan(%r{<span class="visually-hidden">([^<]*)</span>}).flatten
    refute_includes html, "Official accounts"
    refute_includes html, "Contact form"
  end

  def test_member_with_only_a_phone_has_no_icon_row
    links = %w[website_url office x_url mastodon_url]
    html = build(MEMBER.reject { |k, _| links.include?(k) }).fetch("/members/Z000001/index.html")
    assert_includes html, "Official links"
    refute_includes html, "account-icons"
  end

  def test_member_without_links_has_no_section_and_phone_without_tel_is_text
    links = %w[website_url phone phone_tel office x_url mastodon_url]
    html = build(MEMBER.reject { |k, _| links.include?(k) }).fetch("/members/Z000001/index.html")
    refute_includes html, "Official links"

    html = build(MEMBER.merge("phone" => "202-225-0000 ext. 5", "phone_tel" => nil)).fetch("/members/Z000001/index.html")
    assert_includes html, '<dd class="nums">202-225-0000 ext. 5</dd>'
    refute_includes html, "tel:"
  end
end

# The masthead, footer and analytics tag that every page shares.
class LayoutTest < Minitest::Test
  include SiteBuild

  def build
    build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])
  end

  # The main nav item each page marks as current (nil: none).
  CURRENT = {
    "/index.html" => "/votes/", "/votes/index.html" => "/votes/", "/votes/119/house/1/1/index.html" => "/votes/",
    "/members/index.html" => "/members/", "/members/Z000001/index.html" => "/members/", "/find/index.html" => "/members/",
    "/schedule/index.html" => "/schedule/", "/about/index.html" => "/about/", "/privacy/index.html" => nil,
    "/activity/index.html" => "/activity/"
  }.freeze

  def test_masthead_and_footer_link_to_the_schedule_and_activity_and_mark_the_current_page
    pages = build
    assert_empty CURRENT.keys - pages.keys
    pages.each do |path, html|
      nav = html[%r{<nav class="mainnav" aria-label="Main">(.*?)</nav>}m, 1]
      refute_nil nav, "#{path}: no main nav"
      assert_equal %w[/votes/ /members/ /schedule/ /activity/ /about/], nav.scan(/<a href="([^"]+)"/).flatten, path
      assert_equal [CURRENT[path]].compact, nav.scan(/<a href="([^"]+)" aria-current="page">/).flatten, path
      assert_includes html[%r{<footer.*</footer>}m].to_s, '<a href="/schedule/">Floor schedule</a>', path
      assert_includes html[%r{<footer.*</footer>}m].to_s, '<a href="/activity/">Floor activity</a>', path
    end
  end

  def test_umami_and_its_opt_out_only_in_a_production_build
    production = with_env("production") { build }
    development = with_env(nil) { build }
    [production, development].each { |pages| assert_includes pages.keys, "/index.html" }
    # The Privacy page names Umami in its text, so look for the tags themselves.
    tag = '<script defer src="https://cloud.umami.is/script.js"'
    opt_out = 'localStorage.setItem("umami.disabled", "1")'
    production.each do |path, html|
      assert_includes html, tag, path
      assert_includes html, opt_out, path
    end
    development.each do |path, html|
      refute_includes html, tag, path
      refute_includes html, opt_out, path
    end
  end

  def with_env(value)
    saved = ENV["JEKYLL_ENV"]
    ENV["JEKYLL_ENV"] = value
    yield
  ensure
    ENV["JEKYLL_ENV"] = saved
  end
end

class AccountsTest < Minitest::Test
  def test_accounts_in_fixed_order_skipping_missing
    m = { "mastodon_url" => "https://m.example/@a", "x_url" => "https://x.com/a", "facebook_url" => nil }
    assert_equal [{ "label" => "X", "url" => "https://x.com/a", "icon" => "x" },
                  { "label" => "Mastodon", "url" => "https://m.example/@a", "icon" => "mastodon" }],
                 Yan.accounts(m)
    assert_equal [], Yan.accounts({})
  end

  def test_every_account_and_the_website_has_an_icon
    include_html = File.read(File.join(__dir__, "..", "_includes", "account_icon.html"))
    (["website"] + Yan::ACCOUNTS.map(&:last)).each { |icon| assert_includes include_html, %(when "#{icon}") }
  end

  def test_website_label_strips_only_the_leading_scheme_and_www
    assert_equal "example.house.gov", Yan.website_label("https://www.example.house.gov/")
    assert_equal "example.gov/www.page", Yan.website_label("http://example.gov/www.page")
    assert_nil Yan.website_label(nil)
  end
end

class DistrictMapTest < Minitest::Test
  MAP = { "width" => 100, "height" => 60, "borders" => "M0 0l1 1",
          "districts" => [{ "state" => "WY", "district" => 0, "d" => "M1 1l1 0 0 1z" },
                          { "state" => "KY", "district" => 4, "d" => "M2 2l1 0 0 1z",
                            "places" => %w[Lexington Frankfort], "more_places" => 3 },
                          { "state" => "KY", "district" => 5, "d" => "M3 3l1 0 0 1z" }] }.freeze

  def member(id, chamber, state, district = nil, name: id, current: true)
    { "bioguide_id" => id, "name" => name, "url" => "/members/#{id}/", "party" => "R", "chamber" => chamber,
      "state" => state, "district" => district, "is_current" => current, "is_voting_member" => true }
  end

  def map(members = [])
    Yan.district_map(MAP, members)
  end

  def test_each_district_gets_its_current_representative_and_state_senators
    members = [member("H1", "house", "KY", 4), member("H0", "house", "KY", 4, current: false),
               member("S1", "senate", "KY"), member("S2", "senate", "KY"), member("W1", "house", "WY", 0)]
    m = map(members)
    assert_equal %w[WY KY-4 KY-5], m["districts"].map { |d| d["seat"] }
    ky4 = m["districts"][1]
    assert_equal ["Kentucky, 4th District", "H1", "/members/H1/"], ky4.values_at("where", "rep_name", "url")
    people = JSON.parse(m["people_json"])
    assert_equal({ "name" => "H1", "id" => "H1", "party" => "R" }, people["KY-4"]["rep"])
    assert_equal %w[S1 S2], people["KY-4"]["senators"].map { |s| s["name"] }
    assert_equal ["Wyoming, At Large", "W1"], [people["WY"]["where"], people["WY"]["rep"]["name"]]
    assert_equal [%w[Lexington Frankfort], 3], people["KY-4"].values_at("places", "more_places")
    assert_equal [[], 0], people["WY"].values_at("places", "more_places")
  end

  def test_a_vacant_seat_links_to_the_state_list
    ky5 = map["districts"][2]
    assert_nil ky5["rep_name"]
    assert_equal "/members/?state=KY", ky5["url"]
    assert_nil JSON.parse(map["people_json"])["KY-5"]["rep"]
  end

  def test_names_cannot_close_the_script_tag
    json = map([member("H1", "house", "KY", 4, name: "</script><b>")])["people_json"]
    refute_includes json, "<"
    assert_equal "</script><b>", JSON.parse(json)["KY-4"]["rep"]["name"]
  end

  def test_no_map_for_the_congress
    assert_nil Yan.district_map(nil, [])
  end

  # Every current representative in the exported data has a seat on the map
  # for the exported Congress, so district numbering matches after a switchover.
  def test_every_current_representative_is_on_the_current_map
    out = File.expand_path("../../data/out", __dir__)
    congress = JSON.parse(File.read(File.join(out, "meta.json")))["congress"]
    doc = JSON.parse(File.read(File.expand_path("../_maps/#{congress}.json", __dir__)))
    seats = doc["districts"].map { |d| [d["state"], d["district"]] }
    reps = JSON.parse(File.read(File.join(out, "members.json")))["members"]
               .select { |m| m["is_current"] && m["is_voting_member"] && m["chamber"] == "house" }
    assert_empty reps.map { |m| [m["state"], m["district"].to_i] } - seats
  end

  # Both committed maps: the 50 states' 435 seats, numbered as the member data numbers them.
  def test_committed_maps_have_every_seat
    %w[119 120].each do |congress|
      doc = JSON.parse(File.read(File.expand_path("../_maps/#{congress}.json", __dir__)))
      seats = doc["districts"].map { |d| [d["state"], d["district"]] }
      assert_equal 435, seats.uniq.size, congress
      assert_equal 50, seats.map(&:first).uniq.size, congress
      assert(seats.select { |_, n| n.zero? }.all? { |s, _| %w[AK DE ND SD VT WY].include?(s) }, congress)
      assert(doc["districts"].all? { |d| d["d"].start_with?("M") }, congress)
    end
  end

  # The vote pages' maps (scripts/build_vote_map.py) cover the same seats, keyed
  # by the seat codes Yan.state_map uses, and every state.
  def test_committed_vote_maps_match_the_district_maps
    %w[119 120].each do |congress|
      src = JSON.parse(File.read(File.expand_path("../_maps/#{congress}.json", __dir__)))
      doc = JSON.parse(File.read(File.expand_path("../assets/maps/#{congress}.json", __dir__)))
      seats = src["districts"].map { |d| Yan.seat("chamber" => "house", "state" => d["state"], "district" => d["district"]) }
      assert_equal seats.sort, doc["districts"].keys.sort, congress
      assert_equal (Yan::STATE_NAMES.keys - Yan::TERRITORIES).sort, doc["states"].keys.sort, congress
      assert([*doc["districts"].values, *doc["states"].values].all? { |d| d.start_with?("M") }, congress)
    end
  end
end

class PartyGridTest < Minitest::Test
  WORDS = { "yes" => "Yea", "no" => "Nay" }.freeze

  def party(p, yes: 0, no: 0, present: 0, not_voting: 0)
    { "party" => p, "name" => Yan::PARTY_NAMES[p], "yes" => yes, "no" => no, "present" => present,
      "not_voting" => not_voting, "other" => 0 }
  end

  def test_positions_fill_rows_in_order_yea_nay_present_not_voting
    g = Yan.party_grid([party("R", yes: 24, no: 2, not_voting: 1)], WORDS).first
    assert_equal [["yea", "Yea", 24], ["nay", "Nay", 2], ["nv", "Not Voting", 1]],
                 g["runs"].map { |r| r.values_at("mark", "label", "count") }
    nay = g["runs"][1]["cells"]
    assert_equal({ "x" => 24 * 12, "y" => 0 }, nay[0]) # last square of the first row
    assert_equal({ "x" => 0, "y" => 12 }, nay[1])       # wraps to the second row
    assert_equal [25 * 12 - 2, 2 * 12 - 2], g.values_at("width", "height")
  end

  def test_a_short_block_is_only_as_wide_as_its_squares
    g = Yan.party_grid([party("I", yes: 2)], WORDS).first
    assert_equal [22, 10], g.values_at("width", "height")
  end

  def test_parties_with_no_members_recorded_are_left_out
    assert_equal ["D"], Yan.party_grid([party("D", no: 1), party("I")], WORDS).map { |g| g["party"] }
  end

  def test_no_grid_for_a_vote_by_candidate
    doc = { "positions" => { "A000001" => "Jeffries", "B000001" => "Johnson" },
            "party_totals" => { "D" => { "other" => 1 }, "R" => { "other" => 1 } },
            "against_party_majority" => [], "caucus_majority_position" => {}, "summary" => nil }
    assert_equal [], Yan.vote_view({}, doc, {})["party_grid"]
  end
end

class StateMapTest < Minitest::Test
  WORDS = { "yes" => "Aye", "no" => "No" }.freeze
  MEMBERS = {
    "A1" => { "official_full_name" => "Ann Able", "last_name" => "Able", "party" => "D", "chamber" => "house", "state" => "CA", "district" => 12 },
    "A2" => { "official_full_name" => "Bo Bell", "last_name" => "Bell", "party" => "R", "chamber" => "house", "state" => "WY", "district" => 0 },
    "A3" => { "official_full_name" => "Cy <Cole>", "last_name" => "Cole", "party" => "R", "chamber" => "house", "state" => "CA", "district" => 3 },
    "B1" => { "official_full_name" => "Di Dee", "last_name" => "Dee", "party" => "D", "chamber" => "house", "state" => "PR", "district" => 0 },
    "S1" => { "official_full_name" => "Ed Zee", "last_name" => "Zee", "party" => "R", "chamber" => "senate", "state" => "KY" },
    "S2" => { "official_full_name" => "Flo Ash", "last_name" => "Ash", "party" => "D", "chamber" => "senate", "state" => "KY" }
  }.freeze

  def seats(map)
    JSON.parse(map["seats_json"])
  end

  def test_house_seats_by_district_with_names_in_the_title
    map = Yan.state_map("house", { "A1" => "Aye", "A2" => "Not Voting", "A3" => "No" }, MEMBERS, WORDS)
    assert_equal({ "marks" => ["yea"], "title" => "California, 12th District: Ann Able (D), Aye" }, seats(map)["CA-12"])
    assert_equal({ "marks" => ["nv"], "title" => "Wyoming, At Large: Bo Bell (R), Not voting" }, seats(map)["WY"])
    assert_equal "house", map["chamber"]
  end

  # S1's record is a senator's (their latest seat), so it has no district for a House vote.
  def test_a_member_now_in_the_senate_stays_off_a_house_map_but_in_the_table
    map = Yan.state_map("house", { "A1" => "Aye", "S1" => "No" }, MEMBERS, WORDS)
    assert_equal ["CA-12"], seats(map).keys
    assert_equal 1, map["unmapped"]
    assert_equal ["California", "Kentucky"], map["table"].map { |r| r["name"] }
  end

  def test_senate_seats_by_state_in_last_name_order
    map = Yan.state_map("senate", { "S1" => "Guilty", "S2" => "Present" }, MEMBERS, { "yes" => "Guilty", "no" => "Not Guilty" })
    assert_equal({ "marks" => %w[present yea], "title" => "Kentucky: Flo Ash (D), Present; Ed Zee (R), Guilty" },
                 seats(map)["KY"])
    assert_equal [{ "name" => "Kentucky", "yes" => 1, "no" => 0, "present" => 1, "not_voting" => 0 }], map["table"]
  end

  def test_territories_and_unknown_states_are_off_the_map_but_territories_are_in_the_table
    map = Yan.state_map("house", { "A1" => "Aye", "B1" => "Aye", "Z9" => "No" }, MEMBERS, WORDS)
    assert_equal ["CA-12"], seats(map).keys
    assert_equal 2, map["unmapped"]
    assert_equal ["California", "Puerto Rico"], map["table"].map { |r| r["name"] }
  end

  def test_names_cannot_close_the_script_tag
    map = Yan.state_map("house", { "A3" => "No" }, MEMBERS, WORDS)
    refute_includes map["seats_json"], "<"
    assert_equal "California, 3rd District: Cy <Cole> (R), No", seats(map)["CA-3"]["title"]
  end

  def test_no_map_without_positions_or_for_a_vote_by_candidate
    assert_nil Yan.state_map("house", {}, MEMBERS, WORDS)
    doc = { "positions" => { "A1" => "Jeffries" }, "party_totals" => { "D" => { "other" => 1 } },
            "against_party_majority" => [], "caucus_majority_position" => {}, "summary" => nil }
    assert_nil Yan.vote_view({ "chamber" => "house" }, doc, MEMBERS)["state_map"]
  end
end

# Builds vote pages: one with every position, one Speaker election.
class VotePageTest < Minitest::Test
  include SiteBuild

  def member(id, state, district)
    { "bioguide_id" => id, "official_full_name" => "Member #{id}", "first_name" => "Member", "last_name" => id,
      "party" => "R", "caucus_party" => "R", "chamber" => "house", "state" => state, "district" => district,
      "is_current" => true, "is_voting_member" => true }
  end

  def vote(roll, question)
    { "vote_id" => "h119-1-000#{roll}", "congress" => 119, "chamber" => "house", "session" => 1,
      "roll_number" => roll, "vote_date" => "2025-01-03", "question" => question, "result" => "Passed" }
  end

  def doc(positions, totals)
    { "positions" => positions, "party_totals" => { "R" => totals }, "caucus_majority_position" => {},
      "against_party_majority" => [], "summary" => nil }
  end

  def pages
    @pages ||= build_site(
      [member("A000001", "AL", 1), member("A000002", "AL", 2), member("A000003", "AL", 3), member("A000004", "AL", 4), member("A000005", "ZZ", 1)],
      [[vote(1, "On Passage"), doc({ "A000001" => "Yea", "A000002" => "Present", "A000003" => "Not Voting",
                                     "A000004" => "Nay", "A000005" => "Yea" },
                                   { "yes" => 2, "no" => 1, "present" => 1, "not_voting" => 1 })],
       [vote(2, "Election of the Speaker"), doc({ "A000001" => "Johnson", "A000002" => "Johnson", "A000003" => "Not Voting" },
                                                { "other" => 2, "not_voting" => 1 })]]
    )
  end

  def test_every_position_is_on_the_party_grid_and_the_state_map
    html = pages.fetch("/votes/119/house/1/1/index.html")
    %w[yea present nv].each { |mark| assert_equal 1, html.scan(%(<g class="dot #{mark}")).size, mark }
    assert_includes html, '<g class="dot nay" fill="url(#hatch-R)">'
    assert_includes html, 'data-vmap data-src="/assets/maps/119.json" data-chamber="house"'
    seats = JSON.parse(html[%r{<script type="application/json" data-seats>(.*?)</script>}m, 1])
    assert_equal({ "AL-1" => ["yea"], "AL-2" => ["present"], "AL-3" => ["nv"], "AL-4" => ["nay"] },
                 seats.transform_values { |s| s["marks"] })
    assert_includes html, %(<th scope="row">Alabama</th><td class="r">1</td><td class="r">1</td><td class="r">1</td><td class="r">1</td>)
    # A000005's state code isn't on the map.
    assert_includes html, "Not on the map: 1 member with no seat drawn on it"
  end

  # The built site's meta is the 119th Congress. A 120th vote has shapes but its
  # members' districts aren't known; a 99th vote has no shapes at all.
  def test_map_only_for_votes_in_the_member_datas_congress_with_shapes
    built = build_site([member("A000001", "AL", 1)],
                       [99, 120].map { |c| [vote(1, "On Passage").merge("congress" => c), doc({ "A000001" => "Yea" }, { "yes" => 1 })] })
    %w[99 120].each do |c|
      html = built.fetch("/votes/#{c}/house/1/1/index.html")
      assert_includes html, "By state", c
      refute_includes html, "data-vmap", c
    end
  end

  def test_no_grids_for_a_speaker_election
    html = pages.fetch("/votes/119/house/1/2/index.html")
    refute_includes html, "grid-chart"
    refute_includes html, "By state"
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

class VoteVolumeTest < Minitest::Test
  include SiteBuild

  def vote(chamber, date, key)
    { "chamber" => chamber, "vote_date" => date, "procedure" => key && { "key" => key } }
  end

  def test_kinds_group_procedure_keys_and_default_to_procedural
    assert_equal "passage", Yan.vote_kind("suspend")
    assert_equal "passage", Yan.vote_kind("veto_override")
    assert_equal "amendment", Yan.vote_kind("amendment")
    assert_equal "nomination", Yan.vote_kind("nomination")
    assert_equal "procedural", Yan.vote_kind("cloture")
    assert_equal "procedural", Yan.vote_kind("rule")
    assert_equal "procedural", Yan.vote_kind(nil) # a question with no definition
  end

  def test_every_grouped_key_is_in_procedures_yml
    keys = ProcedureTest::PROCEDURES["questions"].map { |q| q["key"] }
    assert_empty Yan::VOTE_KINDS.flat_map { |k| k["procedures"] } - keys
  end

  def test_weeks_run_monday_to_sunday_and_empty_weeks_are_kept
    vol = Yan.vote_volume([
      vote("senate", "2026-11-09", "cloture"),    # Monday
      vote("senate", "2026-11-15", "nomination"), # Sunday: same week
      vote("house", "2026-10-28", "passage")      # two weeks earlier
    ])
    assert_equal "2026-10-26", vol["first_week"]
    assert_equal "2026-11-09", vol["last_week"]
    house, senate = vol["chambers"]
    assert_equal %w[2026-10-26 2026-11-02 2026-11-09], senate["weeks"].map { |w| w["start"] }
    assert_equal [0, 0, 2], senate["weeks"].map { |w| w["total"] }
    assert_equal [1, 0, 0], house["weeks"].map { |w| w["total"] }
    assert_equal "Week of Nov. 2, 2026: no roll calls", senate["weeks"][1]["summary"]
    assert_equal "Week of Nov. 9, 2026: 2 roll calls · Nominations 1 · Procedural and other 1",
                 senate["weeks"][2]["summary"]
  end

  def test_segments_stack_from_the_bottom_in_kind_order_on_a_shared_scale
    votes = Array.new(3) { vote("house", "2026-11-10", "passage") } +
            Array.new(2) { vote("house", "2026-11-10", "recommit") } +
            Array.new(4) { vote("senate", "2026-11-10", "nomination") }
    vol = Yan.vote_volume(votes)
    assert_equal 5, vol["y_ticks"].last["value"] # busiest week 5, ticks of 5
    house = vol["chambers"].first["weeks"].first["segments"]
    # 40 units a vote; each segment gives up 1 unit to the gap above it.
    assert_equal [{ "kind" => "passage", "y" => 81.0, "h" => 119.0 },
                  { "kind" => "procedural", "y" => 1.0, "h" => 79.0 }], house
    assert_equal({ "passage" => 0, "amendment" => 0, "nomination" => 4, "procedural" => 0 },
                 vol["chambers"].last["totals"])
  end

  def test_a_chamber_with_no_votes_is_left_out_and_no_votes_means_no_chart
    assert_equal ["senate"], Yan.vote_volume([vote("senate", "2026-11-10", "cloture")])["chambers"].map { |c| c["chamber"] }
    assert_nil Yan.vote_volume([])
  end

  def test_month_ticks_label_january_with_its_year_and_july
    vol = Yan.vote_volume([vote("house", "2025-06-02", "passage"), vote("house", "2026-01-06", "passage")])
    assert_equal ["July", "Jan. 2026"], vol["x_ticks"].map { |t| t["label"] }.compact
    assert_equal 7, vol["x_ticks"].size # July through January
  end

  def test_activity_page_draws_a_column_per_week_with_a_table
    html = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])["/activity/index.html"]
    assert_equal 1, html.scan('<g class="wk"').size
    assert_includes html, "Show the House table by week"
    # The top gridline sits inside the chart, not 1px above it where it would be clipped.
    assert_includes html, '<rect class="grid" x="0" y="0"'
    # No policy_area in this export yet, so no policy area section.
    refute_includes html, "By policy area"
  end
end

class PolicyVolumeTest < Minitest::Test
  include SiteBuild

  def vote(chamber, area, key = "passage", bill_type: "hr", measure: nil)
    { "chamber" => chamber, "vote_date" => "2026-11-10", "bill_type" => bill_type, "measure_number" => measure,
      "policy_area" => area, "procedure" => { "key" => key } }
  end

  def test_rows_for_votes_with_no_area
    assert_equal "Health", Yan.policy_row(vote("house", "Health"))
    assert_equal "Not yet assigned", Yan.policy_row(vote("house", nil))
    assert_equal "Not yet assigned", Yan.policy_row(vote("house", ""))
    # Cloture on a nomination counts with nominations, not under "No bill recorded".
    assert_equal "Nominations", Yan.policy_row(vote("senate", nil, "cloture", bill_type: nil, measure: "PN1181-7"))
    assert_equal "No bill recorded", Yan.policy_row(vote("senate", nil, "waive", bill_type: nil))
    assert_equal "No bill recorded", Yan.policy_row(vote("house", nil, "adjourn", bill_type: nil, measure: "ADJOURN"))
  end

  def test_no_section_until_the_export_carries_policy_area
    assert_nil Yan.policy_volume([{ "chamber" => "house", "vote_date" => "2026-11-10", "bill_type" => "hr" }])
  end

  def test_no_section_when_no_vote_has_an_area_to_draw
    assert_nil Yan.policy_volume([vote("senate", nil, "nomination", bill_type: nil, measure: "PN5"), vote("house", nil)])
  end

  def test_areas_by_total_on_a_shared_scale_with_unassigned_rows_counted_not_drawn
    votes = Array.new(2) { vote("house", "Taxation") } + [vote("senate", "Taxation", "cloture")] +
            Array.new(4) { vote("house", "Health", "amendment") } + [vote("senate", "Armed Forces", "rule")] +
            Array.new(9) { vote("senate", nil, "nomination", bill_type: nil, measure: "PN5") } +
            [vote("house", nil)]
    pv = Yan.policy_volume(votes)
    house, senate = pv["chambers"]
    # Health 4 and Taxation 3 (both chambers), then Armed Forces 1; ties would go by name.
    assert_equal ["Health", "Taxation", "Armed Forces"], house["rows"].map { |r| r["area"] }
    assert_equal 3, pv["area_count"]
    # The largest drawn bar is House Health (4); the 9 nominations don't set the scale.
    assert_equal [100.0, 50.0, 0.0], house["rows"].map { |r| r["pct"] }
    assert_equal [0.0, 25.0, 25.0], senate["rows"].map { |r| r["pct"] }
    assert_equal [{ "kind" => "procedural", "pct" => 100.0 }], senate["rows"][1]["segments"]
    assert_equal "Taxation, Senate: 1 roll call · Procedural and other 1", senate["rows"][1]["summary"]
    assert_equal "Armed Forces, House: no roll calls", house["rows"][2]["summary"]
    assert_equal [{ "area" => "Nominations", "counts" => "Senate 9" }, { "area" => "Not yet assigned", "counts" => "House 1" }],
                 pv["other"]
    assert_equal ["Health", "Taxation", "Armed Forces", "Nominations", "Not yet assigned"], pv["table"].map { |t| t["area"] }
    assert_equal({ "area" => "Taxation", "house" => 2, "senate" => 1, "total" => 3 }, pv["table"][1])
    # The legend has only kinds drawn on some area's bar: nominations have no area.
    assert_equal %w[passage amendment procedural], pv["kinds"].map { |k| k["key"] }
  end

  def test_activity_page_bars_match_the_area_table_with_zero_for_a_chamber_with_none
    areas = { "house" => %w[Health Health Health Taxation Taxation], "senate" => %w[Taxation Taxation Energy] }
    votes = areas.flat_map do |chamber, list|
      list.each_with_index.map do |area, i|
        [EscapingTest::VOTE.merge("vote_id" => "#{chamber[0]}119-1-#{i + 1}", "chamber" => chamber, "roll_number" => i + 1,
                                  "policy_area" => area), EscapingTest::DOC]
      end
    end
    html = build_site([EscapingTest::MEMBER], votes)["/activity/index.html"]
    section = html[html.index("By policy area")..]
    bars = section.scan(/data-chamber="(\w+)" data-area="([^"]*)"[^>]*data-total="(\d+)"/)
    rows = section.scan(%r{<tr><th scope="row">([^<]*)</th><td class="r">(\d+)</td><td class="r">(\d+)</td><td class="r">(\d+)</td></tr>})
    # Taxation 4, Health 3, Energy 1: each area's House and Senate bars carry the counts in its table row, in the same order.
    assert_equal [["Taxation", "2", "2", "4"], ["Health", "3", "0", "3"], ["Energy", "0", "1", "1"]], rows
    assert_equal rows.flat_map { |a, h, s, _| [["house", a, h], ["senate", a, s]] }, bars
  end

  def test_activity_page_escapes_area_names
    v = EscapingTest::VOTE.merge("policy_area" => %q(Arts & "Culture" <x>))
    html = build_site([EscapingTest::MEMBER], [[v, EscapingTest::DOC]])["/activity/index.html"]
    assert_includes html, "By policy area"
    assert_includes html, "Arts &amp; &quot;Culture&quot; &lt;x&gt;"
    refute_includes html, "<x>"
  end
end

class ActivityListTest < Minitest::Test
  include SiteBuild

  def test_kind_counts_in_kind_order_skipping_none
    assert_equal "passage:4,procedural:5", Yan.kind_counts(Hash.new(0).merge("procedural" => 5, "passage" => 4))
    assert_equal "", Yan.kind_counts(Hash.new(0))
  end

  def test_each_vote_carries_its_filters_and_display_text
    v = { "url" => "/votes/119/senate/2/262/", "chamber" => "senate", "vote_date" => "2026-11-15", "roll_number" => 262,
          "question" => "On the Cloture Motion PN1181-7", "measure_label" => "PN1181-7", "bill_type" => nil,
          "measure_number" => "PN1181-7", "vote_title" => "Anna St. John, to be Judge", "result_label" => "Cloture Motion Agreed to",
          "policy_area" => nil, "procedure" => { "key" => "cloture" } }
    assert_equal [{ "u" => "/votes/119/senate/2/262/", "c" => "senate", "w" => "2026-11-09", "a" => "Nominations",
                    "k" => "procedural", "d" => "Nov. 15, 2026", "r" => 262, "q" => "On the Cloture Motion PN1181-7",
                    "t" => "Anna St. John, to be Judge", "s" => "Cloture Motion Agreed to" }], Yan.activity_votes([v])
    # The measure is added to the question when the question doesn't name it; no area before the export has one.
    h = v.merge("question" => "On Passage", "measure_label" => "H.R. 1", "bill_type" => "hr", "measure_title" => "A bill")
    h.delete("policy_area")
    row = Yan.activity_votes([h]).first
    assert_equal ["On Passage · H.R. 1", "A bill", nil], row.values_at("q", "t", "a")
    # No title (a Speaker election, or a blank one): the question is the title, shown once.
    s = v.merge("question" => "Election of the Speaker", "measure_label" => nil, "measure_number" => nil, "vote_title" => " ")
    assert_equal [nil, "Election of the Speaker"], Yan.activity_votes([s]).first.values_at("q", "t")
  end

  def test_rollcalls_json_is_built_without_running_liquid_in_titles
    v = EscapingTest::VOTE.merge("measure_title" => "A bill {{ site.title }} {% raw %} <b>")
    pages = build_site([EscapingTest::MEMBER], [[v, EscapingTest::DOC]], files: "*.{html,json}")
    rows = JSON.parse(pages.fetch("/activity/rollcalls.json"))["votes"]
    assert_equal ["A bill {{ site.title }} {% raw %} <b>"], rows.map { |r| r["t"] }
    html = pages["/activity/index.html"]
    assert_includes html, 'data-week="2024-12-30"'
    assert_includes html, 'data-kinds="passage:1"'
  end
end
