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

  # The question reads only "On Agreeing to the Resolution", so the title tells
  # an expulsion apart; a motion to table one is still a motion to table.
  def test_expulsion_needs_an_expulsion_title
    assert_equal "expel", key("On Agreeing to the Resolution",
                              measure_title: "Providing for the expulsion of Representative X from the House")
    assert_equal "expel", key("On the Resolution", measure_title: "Expelling Senator X")
    assert_equal "table", key("On Motion to Table", measure_title: "Expelling Representative X")
    more = Yan.procedure({ "question" => "On Agreeing to the Resolution", "measure_title" => "Expelling X" },
                         PROCEDURES)["more"]
    assert_equal({ "url" => "/how/expulsion/", "label" => "How expulsion works" }, more)
    assert_nil Yan.procedure({ "question" => "On Passage" }, PROCEDURES)["more"]
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

  # Keys are the dictionary page's anchors, so each is unique across all
  # three lists, and none is an id the page already uses; each has a term and
  # a definition, so no entry renders empty.
  def test_every_entry_has_a_unique_key
    entries = %w[questions measures terms].flat_map { |list| PROCEDURES[list] }
    assert_empty entries.reject { |e| e["term"].to_s.strip != "" && e["definition"].to_s.strip != "" }
    keys = entries.map { |e| e["key"] }
    assert_empty keys.select { |k| k.nil? || k !~ /\A[a-z][a-z_]*\z/ }
    assert_equal keys.uniq, keys
    refute_includes keys, "main"
    refute_includes keys, "terms"
  end

  def test_dictionary_sorts_every_entry_and_resolves_see_also
    entries = Yan.dictionary(PROCEDURES)
    assert_equal %w[questions measures terms].sum { |list| PROCEDURES[list].size }, entries.size
    terms = entries.map { |e| e["term"] }
    assert_equal terms.sort_by(&:downcase), terms
    filibuster = entries.find { |e| e["key"] == "filibuster" }
    assert_equal [{ "key" => "cloture", "term" => "Cloture (Senate)" }], filibuster["see"]
    assert_equal({ "url" => "/how/expulsion/", "label" => "How expulsion works" },
                 entries.find { |e| e["key"] == "expel" }["more"])
    assert_equal [], entries.find { |e| e["key"] == "bill" }["see"]
  end

  def test_dictionary_stops_on_an_unknown_see_also_key
    procedures = { "terms" => [{ "key" => "a", "term" => "A", "definition" => "x", "see" => ["nope"] }] }
    assert_raises(KeyError) { Yan.dictionary(procedures) }
  end
end

# build_site's extra pages, added once the source is read.
Jekyll::Hooks.register :site, :post_read do |site|
  site.config.fetch("test_pages", []).each do |dir, name|
    site.pages << Jekyll::PageWithoutAFile.new(site, site.source, dir, name).tap { |p| p.content = "<p>Test page</p>" }
  end
end

# Builds the site from a small export written to a temp dir.
module SiteBuild
  SOURCE = File.expand_path("..", __dir__)

  # A page without its footer, which links every "How it works" page.
  def without_footer(html)
    html.sub(%r{<footer.*</footer>}m, "")
  end

  # Returns { "/path/index.html" => html } for every page built from these
  # members and [vote, vote file] pairs, plus a floor schedule export, a build
  # time (Eastern) and members' bill files ({ bioguide_id => file }) when given.
  # `pages` adds pages the source doesn't have, as [[dir, name]] pairs; `cards`
  # is the link card folder, relative to the source (none by default).
  def build_site(members, votes, files: "*.html", schedule: nil, time: nil, member_files: {}, pages: [], cards: nil)
    Dir.mktmpdir do |tmp|
      data = File.join(tmp, "data")
      FileUtils.mkdir_p([File.join(data, "votes"), File.join(data, "members")])
      write = ->(path, obj) { File.write(File.join(data, path), JSON.generate(obj)) }
      write.call("meta.json", { "congress" => 119, "has_sponsored_bills" => true })
      members = members.map { |m| { "last_congress" => 119 }.merge(m) }
      write.call("members.json", { "members" => members })
      write.call("votes.json", { "votes" => votes.map(&:first) })
      votes.each { |v, doc| write.call("votes/#{v["vote_id"]}.json", doc) }
      members.each do |m|
        file = member_files.fetch(m["bioguide_id"], { "sponsored" => [], "cosponsored" => [] })
        # Bills given as a plain list are the 119th's; the export groups them by Congress.
        file = file.to_h { |k, v| [k, v.is_a?(Array) && !v.first&.key?("bills") ? [{ "congress" => 119, "bills" => v }] : v] }
        write.call("members/#{m["bioguide_id"]}.json", file)
      end
      write.call("floor_schedule.json", schedule) if schedule

      config = {
        "source" => SOURCE, "destination" => File.join(tmp, "_site"), "yan_data" => data,
        "plugins_dir" => File.join(tmp, "none"), # yan_data.rb is already loaded above
        "quiet" => true
      }
      config["time"] = time if time
      # Never the real assets/cards/, which `yan cards` fills with cards for real vote IDs.
      config["yan_cards"] = cards || "assets/no-cards"
      config["test_pages"] = pages
      site = Jekyll::Site.new(Jekyll.configuration(config))
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
    "congress_gov_url" => "https://www.congress.gov/bill/119th-congress/house-bill/1",
    # Puts the title and the member's name in the home page's closest and
    # against-majority modules too.
    "yea_count" => 0, "nay_count" => 1, "yeas_needed" => 1, "required_share" => "1/2",
    "bot_posts" => true, "against_party_majority_count" => 1
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
    assert_includes pages["/index.html"], 'id="close-h"'
    assert_includes pages["/index.html"], 'id="against-h"'
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

  # The sponsor's party and seat are as of introduction, not the member's latest.
  def test_sponsor_code_is_as_of_introduction
    senator = MEMBER.merge("party" => "I", "chamber" => "senate", "district" => nil)
    code = lambda do |vote|
      build_site([senator], [[VOTE.merge(vote), DOC]])["/votes/119/house/1/1/index.html"][/Introduced by.*?<\/a> \(([^)]*)\)/, 1]
    end
    assert_equal "R-AL-4", code.call("sponsor_party" => "R", "sponsor_chamber" => "house",
                                     "sponsor_state" => "AL", "sponsor_district" => 4)
    # Data exported before those columns: the member's latest.
    assert_equal "I-AL", code.call({})
  end

  # The rest of the feed's text: a candidate's name as a position (tallies,
  # filters, rows), amendment, tie-breaker and source fields, and a second
  # member whose state, party and initials hold the special characters.
  def test_positions_vote_fields_and_member_codes_are_escaped
    other = MEMBER.merge("bioguide_id" => "Z000002", "official_full_name" => %q(Will "WQ" <wq> O'Wee & Two),
                         "first_name" => "&", "last_name" => "<Two", "state" => %q("WQ" <wq>),
                         "party" => %q("WQ" <wq>), "website_url" => nil, "x_url" => nil)
    candidate = %q("VQ" <vq> O'Vee & Co)
    speaker = VOTE.merge("vote_id" => "h119-1-0002", "roll_number" => 2, "question" => "Election of the Speaker",
                         "result" => "Doe (AL)", "measure_title" => nil, "bill_type" => nil, "congress_gov_url" => nil,
                         "sponsor_bioguide_id" => nil, "yeas_needed" => nil, "bot_posts" => false)
    speaker_doc = DOC.merge("positions" => { "Z000001" => candidate, "Z000002" => candidate },
                            "party_totals" => { "R" => { "other" => 1 } }, "against_party_majority" => [])
    amendment = VOTE.merge("vote_id" => "h119-1-0003", "roll_number" => 3, "question" => "On Agreeing to the Amendment",
                           "amendment_number" => %q("VQ" <vq> 1), "amendment_purpose" => "To add a section.",
                           "tie_breaker_by" => %q("VQ" <vq> O'Vee & VP), "tie_breaker_vote" => %q("VQ" <vq> Yea),
                           "source_url" => %q(https://clerk.house.gov/?q="vq"<vq>&x='vq'),
                           "congress_gov_url" => %q(https://www.congress.gov/?q="vq"<vq>&x='vq'))
    amendment_doc = DOC.merge("positions" => { "Z000001" => "Nay", "Z000002" => "Yea" })
    built = build_site([MEMBER, other], [[VOTE, DOC], [speaker, speaker_doc], [amendment, amendment_doc]])

    speaker_page = built.fetch("/votes/119/house/1/2/index.html")
    escaped = "&quot;VQ&quot; &lt;vq&gt; O&#39;Vee &amp; Co"
    assert_includes speaker_page, %(<option>#{escaped}</option>)
    assert_includes speaker_page, %(data-position="#{escaped}")
    amendment_page = built.fetch("/votes/119/house/1/3/index.html")
    assert_includes amendment_page, "Amendment &quot;VQ&quot; &lt;vq&gt; 1:"
    assert_includes amendment_page, %(href="https://clerk.house.gov/?q=&quot;vq&quot;&lt;vq&gt;&amp;x=&#39;vq&#39;")
    assert_includes amendment_page, %(href="https://www.congress.gov/text?q=&quot;vq&quot;&lt;vq&gt;&amp;x=&#39;vq&#39;")
    assert_includes amendment_page, %(data-party="&quot;WQ&quot; &lt;wq&gt;" data-state="&quot;WQ&quot; &lt;wq&gt;")
    assert_includes built.fetch("/members/Z000002/index.html"), %(<span class="initials" aria-hidden="true" data-pagefind-ignore>&amp;&lt;</span>)
    assert_includes built.fetch("/members/index.html"), %(<option value="&quot;WQ&quot; &lt;wq&gt;">)

    # Map and card data are JSON in script tags (checked above); drop them.
    scripts = %r{<script type="application/json" data-(?:people|seats)>.*?</script>}m
    pages = built.transform_values { |html| html.gsub(scripts, "") }.select { |_, html| html.match?(/vq|wq/i) }
    assert_includes pages.keys, "/votes/119/house/1/2/index.html"
    assert_includes pages.keys, "/members/Z000002/index.html"
    pages.each do |path, html|
      html.scan(/.?(?:vq|wq).?/i).each do |hit|
        assert_match(/\A;(vq|wq)&\z/i, hit, "#{path}: quote or angle bracket not escaped")
      end
      ["O'Vee", "O'Wee", "& Co", "& VP", "& Two", "='vq'"].each do |raw|
        refute_includes html, raw, "#{path}: apostrophe or ampersand not escaped"
      end
    end
  end

  # The pipeline sanitizes CRS summaries, but in a job that runs third-party
  # code; the site build re-checks them and escapes the version label.
  def test_summary_keeps_only_bare_allowed_tags_and_escapes_the_version
    hostile = { "version" => %q(Introduced "<vv>"), "version_date" => "2025-01-03",
                "html" => %q(<p>Keeps <strong>bold</strong> &amp; lists</p><ul><li>one</li></ul>) +
                          %q(<script>alert(1)</script><p onclick="x">a</p><img src=x onerror=y><a href="/">b</a>) }
    built = build_site([MEMBER], [[VOTE, DOC.merge("summary" => hostile)]])
    page = built["/votes/119/house/1/1/index.html"]
    assert_equal "<p>Keeps <strong>bold</strong> &amp; lists</p><ul><li>one</li></ul>" \
                 "&lt;script&gt;alert(1)&lt;/script&gt;&lt;p onclick=\"x\"&gt;a&lt;/p&gt;" \
                 "&lt;img src=x onerror=y&gt;&lt;a href=\"/\"&gt;b&lt;/a&gt;",
                 page[%r{<div class="crs-text">(.*?)</div>}m, 1]
    assert_includes page, "Version: Introduced &quot;&lt;vv&gt;&quot;,"
  end

  # A summary with no usable text reads as none, without the CRS credit line.
  # Each entity and character gets its own summary, so one the check misses
  # fails here instead of hiding behind another that it matches.
  def test_a_summary_without_text_reads_as_no_summary
    base = { "version" => "Introduced", "version_date" => "2025-01-03" }
    entities = %w[&nbsp; &NBSP; &ensp; &EMSP; &thinsp; &zwnj; &ZWJ; &shy; &lrm; &RLM;
                  &#9; &#10; &#13; &#32; &#160; &#173; &#8194; &#08195; &#8201; &#8203; &#8204; &#08205;
                  &#8206; &#08207; &#8232; &#8233; &#8288; &#65279;
                  &#x9; &#x0a; &#xD; &#x20; &#xA0; &#xAD; &#x2002; &#X2003; &#x2009; &#x200B; &#x0200b; &#x200c;
                  &#X200D; &#x200E; &#x200f; &#x2028; &#X02029; &#x2060; &#xFEFF; &#x0feff;]
    characters = [0xAD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0x2060, 0xFEFF]
                 .map { |c| c.chr(Encoding::UTF_8) }
    blanks = ["", " <p> </p><br>\n", "<p>\0</p>"] + (entities + characters).map { |e| "<p>#{e}</p>" }
    summaries = [base.merge("html" => 1), "<p>a</p>"] + blanks.map { |html| base.merge("html" => html) }
    votes = summaries.each_with_index.map do |summary, i|
      [VOTE.merge("vote_id" => format("h119-1-%04d", i + 1), "roll_number" => i + 1), DOC.merge("summary" => summary)]
    end
    built = build_site([MEMBER], votes)
    (1..summaries.size).each do |roll|
      page = built.fetch("/votes/119/house/1/#{roll}/index.html")
      assert_includes page, "No Congressional Research Service summary of", roll
      refute_includes page, "By the Congressional Research Service", roll
    end
  end

  # A missing or unreadable version date is left out of the credit line.
  def test_a_summary_without_a_valid_version_date_still_builds
    votes = [nil, "Jan. 3", 20_250_103].each_with_index.map do |date, i|
      summary = { "version" => "Introduced", "version_date" => date, "html" => "<p>a</p>" }
      [VOTE.merge("vote_id" => "h119-1-000#{i + 1}", "roll_number" => i + 1), DOC.merge("summary" => summary)]
    end
    built = build_site([MEMBER], votes)
    (1..3).each do |roll|
      assert_includes built.fetch("/votes/119/house/1/#{roll}/index.html"), "Version: Introduced.", roll
    end
  end

  # Other text, even an entity, is a summary; a missing or blank version label
  # is left out of the credit line, keeping the date when there is one.
  def test_a_summary_without_a_version_label
    summaries = [{ "html" => "<p>&nbsp;&#8203;&shy;a&ensp;&#xFEFF;&lrm;\u200B</p>" }, { "html" => "<p>&amp;</p>", "version" => " ", "version_date" => "2025-01-03" },
                 { "html" => "<p>a</p>", "version" => 1, "version_date" => "Jan. 3" },
                 { "html" => "<p>a</p>", "version" => " \t" }]
    votes = summaries.each_with_index.map do |summary, i|
      [VOTE.merge("vote_id" => "h119-1-000#{i + 1}", "roll_number" => i + 1), DOC.merge("summary" => summary)]
    end
    built = build_site([MEMBER], votes)
    pages = (1..4).map { |roll| built.fetch("/votes/119/house/1/#{roll}/index.html") }
    pages.each { |page| refute_includes page, "Version:" }
    assert_includes pages[0], "Library of Congress, as published.<"
    assert_includes pages[1], "as published. Version dated Jan. 3, 2025."
    assert_includes pages[2], "Library of Congress, as published.<"
    assert_includes pages[3], "Library of Congress, as published.<"
  end

  def test_summary_tags_match_the_pipeline_allowlist
    py = File.read(File.expand_path("../../src/yan/export/summary_html.py", __dir__))
    assert_equal py[/^ALLOWED = \{(.*)\}$/, 1].scan(/"(\w+)"/).flatten.sort, Yan::SUMMARY_TAGS.sort
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

# A member's sponsored list is null until first fetched (no section; a fetch
# can fail), then [] (an empty section) or the bills introduced in their last Congress.
class MemberSponsoredTest < Minitest::Test
  include SiteBuild

  # The member page's sponsored section, or nil when there is none.
  def section(sponsored)
    files = { "Z000001" => { "sponsored" => sponsored, "cosponsored" => [] } }
    @page = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]], member_files: files)
            .fetch("/members/Z000001/index.html")
    @page[%r{<section aria-labelledby="bills-h".*?</section>}m]
  end

  def test_no_section_until_the_list_is_fetched
    assert_nil section(nil)
    assert_includes @page, '<section aria-labelledby="cosponsored-h"'
  end

  def test_an_empty_list_says_none
    s = section([])
    assert_includes s, "0 in the 119th Congress"
    assert_includes s, "No bills or resolutions introduced in the 119th Congress."
  end
end

# A member's cosponsored list is null until first fetched (no section), then
# [] (an empty section) or the bills cosponsored in their last Congress.
class MemberCosponsoredTest < Minitest::Test
  include SiteBuild

  BILL = {
    "measure_label" => "S. 7", "title" => "A bill to rename a post office", "introduced_date" => "2025-02-01",
    "congress_gov_url" => "https://www.congress.gov/bill/119th-congress/senate-bill/7",
    "latest_action_date" => "2025-03-04", "latest_action_text" => "Read twice and referred to committee.",
    "latest_vote_id" => "h119-1-0001"
  }.freeze

  # The member page's cosponsored section, or nil when there is none.
  def section(cosponsored)
    files = { "Z000001" => { "sponsored" => [], "cosponsored" => cosponsored } }
    @page = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]], member_files: files)
            .fetch("/members/Z000001/index.html")
    @page[%r{<section aria-labelledby="cosponsored-h".*?</section>}m]
  end

  # The bill titles in a section, in order.
  def titles(html)
    html.scan(%r{<a class="t headline-link"[^>]*>([^<]*)</a>}).flatten
  end

  def test_no_section_until_the_list_is_fetched
    assert_nil section(nil)
    # The page itself rendered, with the sections around the missing one.
    assert_includes @page, '<section aria-labelledby="bills-h"'
    assert_includes @page, '<section aria-labelledby="recent-h"'
  end

  def test_an_empty_list_says_none
    s = section([])
    assert_includes s, "Bills cosponsored"
    assert_includes s, "0 in the 119th Congress"
    assert_includes s, "No bills or resolutions cosponsored in the 119th Congress."
  end

  def test_bills_are_listed_with_their_latest_action_and_vote
    s = section([BILL])
    assert_includes s, "1 in the 119th Congress"
    assert_includes s, "S. 7 · Introduced Feb. 1, 2025"
    assert_includes s, %(<a class="t headline-link" href="#{BILL["congress_gov_url"]}">A bill to rename a post office</a>)
    assert_includes s, "Latest action, March 4, 2025: Read twice and referred to committee."
    assert_includes s, 'href="/votes/119/house/1/1/">Recorded vote →</a>'
    refute_includes s, "No bills or resolutions cosponsored"
    refute_includes s, "Show all"
  end

  # The first five show; the rest go under "Show all".
  def test_more_than_five_bills_fold_the_rest_under_show_all
    bills = (1..6).map { |n| BILL.merge("measure_label" => "S. #{n}", "title" => "Bill #{n}") }
    s = section(bills)
    assert_includes s, "6 in the 119th Congress"
    parts = s.split("<summary")
    assert_equal 2, parts.size
    shown, folded = parts
    assert_equal (1..5).map { |n| "Bill #{n}" }, titles(shown)
    assert_includes folded, "Show all 6</summary>"
    assert_equal ["Bill 6"], titles(folded)
  end

  def test_exactly_five_bills_all_show_with_no_show_all
    s = section((1..5).map { |n| BILL.merge("measure_label" => "S. #{n}", "title" => "Bill #{n}") })
    assert_includes s, "5 in the 119th Congress"
    assert_equal (1..5).map { |n| "Bill #{n}" }, titles(s)
    refute_includes s, "<summary"
    refute_includes s, "Show all"
  end

  def test_a_bill_with_no_dates_action_or_vote_shows_only_its_label_and_title
    bare = BILL.merge("introduced_date" => nil, "latest_action_date" => nil, "latest_action_text" => nil,
                      "latest_vote_id" => nil)
    s = section([bare])
    assert_includes s, %(<span class="kicker muted nums">S. 7</span>)
    assert_equal ["A bill to rename a post office"], titles(s)
    refute_includes s, "Introduced"
    refute_includes s, "Latest action"
    refute_includes s, "Recorded vote"
  end

  def test_titles_and_labels_are_escaped
    s = section([BILL.merge("measure_label" => "S. <7>", "title" => %q(A "bill" <b>to</b> & 'rename'))])
    assert_includes s, "S. &lt;7&gt;"
    assert_equal ["A &quot;bill&quot; &lt;b&gt;to&lt;/b&gt; &amp; &#39;rename&#39;"], titles(s)
    refute_includes s, "<b>to</b>"
  end
end

# Member bill lists come one group per fetched Congress; a page shows the
# member's last Congress.
class CongressBillsTest < Minitest::Test
  LISTS = [{ "congress" => 120, "bills" => [{ "bill_id" => "120-hr-2" }] },
           { "congress" => 119, "bills" => [{ "bill_id" => "119-hr-1" }] }].freeze

  def test_picks_the_congress_group
    assert_equal [{ "bill_id" => "119-hr-1" }], Yan.congress_bills(LISTS, 119)
    assert_equal [{ "bill_id" => "120-hr-2" }], Yan.congress_bills(LISTS, 120)
  end

  def test_a_congress_not_fetched_or_no_lists_is_nil
    assert_nil Yan.congress_bills(LISTS, 118)
    assert_nil Yan.congress_bills(nil, 119)
  end

  # Exported before lists were grouped: one Congress's bills as a plain list.
  def test_an_ungrouped_list_is_returned_as_is
    assert_equal [{ "bill_id" => "119-hr-1" }], Yan.congress_bills([{ "bill_id" => "119-hr-1" }], 119)
    assert_equal [], Yan.congress_bills([], 119)
  end

  def test_earlier_groups_are_every_other_congress_newest_first
    lists = [LISTS[1], { "congress" => 118, "bills" => [] }, LISTS[0]]
    assert_equal [119, 118], Yan.earlier_congress_bills(lists, 120).map { |g| g["congress"] }
    assert_equal [120, 118], Yan.earlier_congress_bills(lists, 119).map { |g| g["congress"] }
    assert_equal [], Yan.earlier_congress_bills(nil, 120)
    assert_equal [], Yan.earlier_congress_bills([{ "bill_id" => "119-hr-1" }], 120)
  end
end

# A member page across Congresses: stats, term line and bill lists name the
# member's last Congress (not the site's), with earlier Congresses below.
class MemberCongressesTest < Minitest::Test
  include SiteBuild

  STATS_119 = { "roll_calls" => 685, "votes_cast" => 665, "missed_votes" => 20, "missed_votes_pct" => 2.9,
                "party_majority_votes" => 662, "with_party_majority_pct" => 98.0 }.freeze
  CONGRESS_119 = STATS_119.merge("congress" => 119, "served_from" => "2025-01-03", "served_to" => "2027-01-03").freeze
  BILL = MemberCosponsoredTest::BILL

  def page(member, files = { "sponsored" => [], "cosponsored" => [] })
    @site = build_site([EscapingTest::MEMBER.merge(member)], [[EscapingTest::VOTE, EscapingTest::DOC]],
                       member_files: { "Z000001" => files })
    @site.fetch("/members/Z000001/index.html")
  end

  def section(html, id)
    html[%r{<section aria-labelledby="#{id}".*?</section>}m]
  end

  # A returning member from Jan. 3 until their chamber's first 120th roll call.
  def test_a_last_congress_with_no_roll_calls_yet_shows_earlier_congresses
    html = page("last_congress" => 120, "served_from" => "2027-01-03", "served_to" => "2029-01-03",
                "congresses" => [{ "congress" => 120, "served_from" => "2027-01-03", "roll_calls" => nil },
                                 CONGRESS_119])
    s = section(html, "stats-h")
    assert_includes s, ">120th Congress</h2>"
    assert_includes s, "No roll calls yet in the 120th Congress."
    refute_includes s, '<div class="tiles'
    assert_includes s, "<th scope=\"row\">119th</th><td class=\"r\" style=\"white-space: nowrap\">665 of 685</td><td class=\"r\">2.9%</td><td class=\"r\">98.0%</td>"
    assert_includes html, "In office in the 120th Congress since Jan. 3, 2027"
    refute_includes html, "this Congress"
  end

  # A returning member on a 120th roll call before congress-legislators lists their new term.
  def test_a_last_congress_with_roll_calls_but_no_term_dates
    html = page(STATS_119.merge("last_congress" => 120, "served_in_congress" => false,
                                "served_from" => nil, "served_to" => nil,
                                "congresses" => [STATS_119.merge("congress" => 120), CONGRESS_119]))
    s = section(html, "stats-h")
    assert_includes s, ">120th Congress</h2>"
    assert_includes s, '<div class="tiles'
    assert_includes s, "<th scope=\"row\">119th</th>"
    refute_includes s, "<th scope=\"row\">120th</th>"
    refute_includes html, "In office in the"
    refute_includes html, "Former member"
  end

  def test_a_member_with_one_congress_has_tiles_and_no_table
    s = section(page(STATS_119.merge("congresses" => [CONGRESS_119])), "stats-h")
    assert_includes s, ">119th Congress</h2>"
    assert_includes s, '<div class="tiles'
    refute_includes s, "Earlier Congresses"
  end

  def test_a_former_member_reads_as_former_with_their_last_congress
    html = page(STATS_119.merge("is_current" => false, "served_from" => "2025-01-03", "served_to" => "2025-05-21",
                                "congresses" => [CONGRESS_119]))
    assert_includes html, "Former member · Served in the 119th Congress Jan. 3, 2025–May 21, 2025"
    assert_includes section(html, "stats-h"), ">119th Congress</h2>"
    refute_includes html, "In office"
  end

  # The 120th's lists aren't fetched yet; the 119th's go in collapsed sections.
  def test_last_congress_120_with_only_a_119th_list
    files = { "sponsored" => [{ "congress" => 119, "bills" => [BILL] }],
              "cosponsored" => [{ "congress" => 119, "bills" => [] }] }
    html = page(STATS_119.merge("last_congress" => 120, "congresses" => [CONGRESS_119]), files)
    s = section(html, "bills-h")
    assert_includes s, %(<summary class="small nums">119th Congress (1)</summary>)
    assert_includes s, ">A bill to rename a post office</a>"
    assert_includes s, 'href="/votes/119/house/1/1/">Recorded vote →</a>'
    refute_includes s, "in the 120th Congress"
    c = section(html, "cosponsored-h")
    assert_includes c, "119th Congress (0)</summary>"
    assert_includes c, "No bills or resolutions cosponsored in the 119th Congress."
    refute_includes html, "this Congress"
  end

  def test_earlier_lists_follow_the_last_congress_list
    files = { "sponsored" => [{ "congress" => 120, "bills" => [BILL.merge("title" => "New bill")] },
                              { "congress" => 119, "bills" => [BILL] }],
              "cosponsored" => [] }
    s = section(page({ "last_congress" => 120 }, files), "bills-h")
    assert_includes s, "1 in the 120th Congress"
    assert_operator s.index("New bill"), :<, s.index("119th Congress (1)")
  end

  # Exports from before per-Congress stats: no last_congress or congresses.
  def test_an_older_export_reads_as_meta_congress
    s = section(page(STATS_119.merge("last_congress" => nil)), "stats-h")
    assert_includes s, ">119th Congress</h2>"
    refute_includes s, "Earlier Congresses"
  end

  def test_directory_lists_former_members_hidden_until_chosen
    former = EscapingTest::MEMBER.merge("bioguide_id" => "F000001", "official_full_name" => "Fay Former",
                                        "is_current" => false, "served_to" => "2025-05-21")
    delegate = former.merge("bioguide_id" => "D000001", "official_full_name" => "Dee Delegate", "state" => "GU",
                            "is_voting_member" => false)
    positions = { "Z000001" => "Nay", "F000001" => "Yea", "D000001" => "Yea" }
    vote = [EscapingTest::VOTE, EscapingTest::DOC.merge("positions" => positions)]
    html = build_site([EscapingTest::MEMBER, former, delegate], [vote]).fetch("/members/index.html")
    refute_includes html, "Dee Delegate"
    rows = html.scan(%r{<li data-row data-status="(\w+)".*?</li>}m).flatten
    assert_equal %w[current former], rows
    assert_match %r{<li data-row data-status="former"[^>]* hidden>.*?Fay Former.*?Served until May 21, 2025}m, html
    assert_includes html, %(<option value="current" selected>Current members</option><option value="former">Former members</option>)
    assert_includes html, 'data-count-of="status"'
  end
end

# Links from the data reach a page only as http(s) web addresses.
class WebUrlTest < Minitest::Test
  include SiteBuild

  def test_only_http_and_https_pass
    %w[https://www.house.gov/ http://example.senate.gov HTTPS://X.COM/a].each { |u| assert_equal u, Yan.web_url(u) }
    ["javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)", "data:text/html,x", "//example.com/",
     "/members/", "www.house.gov", "https:example.com", "", nil, 7].each { |u| assert_nil Yan.web_url(u), u.inspect }
  end

  def test_text_url_ends_the_path_ahead_of_a_query_or_fragment
    base = "https://www.congress.gov/bill/119th-congress/house-bill/1"
    assert_equal "#{base}/text", Yan.text_url(base)
    assert_equal "#{base}/text", Yan.text_url("#{base}/")
    assert_equal "#{base}/text?s=1&r=2", Yan.text_url("#{base}?s=1&r=2")
    assert_equal "#{base}/text#top", Yan.text_url("#{base}/#top")
    assert_equal "#{base}/text?a=b/c#d?e", Yan.text_url("#{base}?a=b/c#d?e")
    assert_nil Yan.text_url(nil)
  end

  # Every link field holds a script URL; none reaches a page, and the page
  # leaves out each link it dropped (an http:// one stays).
  def test_other_schemes_are_dropped_from_every_page
    bad = "javascript:alert(1)"
    member = EscapingTest::MEMBER.merge("website_url" => bad, "contact_form_url" => "JavaScript:alert(1)",
                                        "x_url" => " javascript:alert(1)", "facebook_url" => "data:text/html,alert(1)",
                                        "mastodon_url" => "http://example.social/@ex")
    vote = EscapingTest::VOTE.merge("congress_gov_url" => bad, "source_url" => bad)
    bill = MemberCosponsoredTest::BILL.merge("congress_gov_url" => bad)
    item = { "chamber" => "house", "item_id" => "a", "week_date" => "2026-11-09", "question" => nil,
             "category" => "Items that may be considered under suspension of the rules", "measure_number" => "H.R. 1",
             "bill_type" => "hr", "measure_label" => "H.R. 1", "title" => "Linked Act", "amends" => nil,
             "congress_gov_url" => bad, "vote_id" => nil }
    built = build_site([member], [[vote, EscapingTest::DOC]], time: "2026-11-13 12:00:00 -0500",
                       member_files: { "Z000001" => { "sponsored" => [bill], "cosponsored" => [bill] } },
                       schedule: { "items" => [item] })

    built.each { |path, html| refute_match(/alert|data:text/, html, path) }
    member_page = built.fetch("/members/Z000001/index.html")
    assert_includes member_page, '<a href="http://example.social/@ex"'
    refute_includes member_page, "Website ("
    refute_includes member_page, "Contact form"
    refute_includes member_page, 'title="X"'
    # Each bill's title as text, in both lists, with no link to the page itself.
    assert_equal 2, member_page.scan('<span class="t">A bill to rename a post office</span>').size
    refute_includes member_page, 'href=""'
    vote_page = built.fetch("/votes/119/house/1/1/index.html")
    # The bill's summary section stays, without its Congress.gov link.
    assert_includes vote_page, "No Congressional Research Service summary of"
    refute_includes vote_page, "Full text on Congress.gov"
    refute_includes vote_page, "Official sources"
    refute_includes vote_page, 'href=""'
    assert_includes built.fetch("/schedule/index.html"), "Linked Act"
  end
end

# A vote's page path takes only integer fields and a known chamber.
class VoteUrlTest < Minitest::Test
  VOTE = { "vote_id" => "h119-1-0001", "congress" => 119, "chamber" => "house", "session" => 1, "roll_number" => 1 }.freeze

  def test_a_vote_url_from_its_fields
    assert_equal "/votes/119/house/1/1/", Yan.vote_url(VOTE)
    assert_equal "/votes/119/senate/2/334/", Yan.vote_url(VOTE.merge("chamber" => "senate", "session" => 2, "roll_number" => 334))
  end

  # The bot's vote_page_url is checked against the same cases (tests/test_bot.py),
  # so its posts link the paths this builds.
  def test_the_paths_the_bot_links
    cases = JSON.parse(File.read(File.expand_path("../../tests/fixtures/vote_urls.json", __dir__)))
    refute_empty cases
    cases.each { |c| assert_equal c["path"], Yan.vote_url(c["vote"]) }
  end

  def test_other_values_stop_the_build
    [["roll_number", "1/../../x"], ["roll_number", "1"], ["roll_number", 0], ["roll_number", nil],
     ["session", 1.5], ["congress", -119], ["chamber", "joint"], ["chamber", nil]].each do |field, value|
      error = assert_raises(ArgumentError, "#{field}: #{value.inspect}") { Yan.vote_url(VOTE.merge(field => value)) }
      assert_includes error.message, '"h119-1-0001"'
    end
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

  # A new "How it works" page has to be added to the footer's list.
  def test_footer_links_every_how_it_works_page_and_its_links_resolve
    pages = build
    footer = pages.fetch("/index.html")[%r{<footer.*</footer>}m]
    links = footer.scan(/href="(\/[^"]*)"/).flatten
    how = pages.keys.grep(%r{\A/how/}).map { |path| path.delete_suffix("index.html") }
    refute_empty how
    assert_equal how.sort, links.grep(%r{\A/how/}).sort
    links.each do |link|
      path, id = link.split("#")
      html = pages["#{path}index.html"]
      refute_nil html, link
      assert_includes html, %(id="#{id}"), link if id
    end
    assert_equal footer.scan(/aria-labelledby="([^"]+)"/), footer.scan(/ id="([^"]+)"/)
  end

  # Site search (Pagefind) indexes each page's content under a "Show" label,
  # leaves out the home and search pages, and skips the lists that would match
  # every query. Every page but /search/ and the 404 page (which have their
  # own) has the masthead search box.
  def test_search_index_labels_pages_and_skips_long_lists
    pages = build
    body = ->(path) { pages.fetch(path)[%r{<div data-pagefind-body[^>]*>(.*)</div>\s*<footer}m, 1] }
    {
      "/votes/119/house/1/1/index.html" => "Votes", "/members/Z000001/index.html" => "Members",
      "/how/bills/index.html" => "How it works", "/about/index.html" => "About this site",
      "/votes/index.html" => "Other pages"
    }.each { |path, label| assert_includes body.(path).to_s, %(data-pagefind-filter="Show:#{label}"), path }
    %w[/index.html /search/index.html /404.html].each { |path| refute_includes pages.fetch(path), "data-pagefind-body", path }

    vote = body.("/votes/119/house/1/1/index.html")
    assert_includes vote, %(aria-labelledby="roll-h" data-filter-scope data-pagefind-ignore>)
    # Tally and By party stay out of the index; the heading beside them is indexed.
    assert_includes vote, %(<section class="tally" aria-labelledby="tally-h" data-pagefind-ignore>)
    assert_includes vote, %(<section class="tally by-party" aria-labelledby="party-h" data-pagefind-ignore>)
    assert_includes vote, %(<div class="vote-top">\n    <section class="vote-head">)
    # The result title, escaped once (the measure title holds " < > ' &).
    assert_includes vote, 'data-title="On Passage: A bill to name the &quot;KK&quot; &lt;kk&gt; O&#39;Kay &amp; Co Post Office (House, Jan. 3, 2025)"'
    assert_includes body.("/members/Z000001/index.html"), %(aria-labelledby="recent-h" style="display: flex; flex-direction: column; gap: 12px" data-filter-scope data-pagefind-ignore>)

    pages.each do |path, html|
      has_box = html.include?(%(<form class="sitesearch" action="/search/" method="get" role="search">\n      <label for="site-q"))
      assert_equal !%w[/search/index.html /404.html].include?(path), has_box, path
    end
  end

  # Link cards: every page has Open Graph tags and the brand card image; a
  # vote page's card leads with its official title (escaped once) and its
  # description gives the chamber, roll call, date, result and tally.
  def test_link_card_tags
    pages = build
    meta = ->(html, prop) { html[/<meta (?:property|name)="#{Regexp.escape(prop)}" content="([^"]*)">/, 1] }
    pages.each do |path, html|
      next unless html.include?("<head>")

      assert_equal "https://yeasandnaysdata.com/assets/brand/social/og-card-1200x630.png", meta.(html, "og:image"), path
      assert_equal "summary_large_image", meta.(html, "twitter:card"), path
      refute_nil meta.(html, "og:title"), path
      assert_equal meta.(html, "description"), meta.(html, "og:description"), path
    end
    assert File.exist?(File.join(SOURCE, "assets/brand/social/og-card-1200x630.png"))

    vote = pages.fetch("/votes/119/house/1/1/index.html")
    assert_equal "A bill to name the &quot;KK&quot; &lt;kk&gt; O&#39;Kay &amp; Co Post Office", meta.(vote, "og:title")
    assert_equal "House roll call 1, Jan. 3, 2025. Passage: Passed, 0 Yea · 1 Nay.", meta.(vote, "og:description")
    assert_equal "https://yeasandnaysdata.com/votes/119/house/1/1/", meta.(vote, "og:url")
    assert_equal "About &amp; methodology", meta.(pages.fetch("/about/index.html"), "og:title")
    assert_equal "Every recorded vote in the U.S. House and Senate, from the official record.",
                 meta.(pages.fetch("/index.html"), "og:description")
  end

  # With no measure title the card falls back as the heading does: the
  # Senate's vote title, then the question.
  def test_link_card_title_falls_back_like_the_heading
    base = EscapingTest::VOTE.merge("measure_title" => nil, "bill_type" => nil, "congress_gov_url" => nil)
    votes = [base.merge("vote_title" => "A joint resolution providing for a vote"),
             base.merge("vote_id" => "h119-1-0002", "roll_number" => 2, "vote_title" => "")]
    pages = build_site([EscapingTest::MEMBER], votes.map { |v| [v, EscapingTest::DOC] })
    og = ->(roll) { pages.fetch("/votes/119/house/1/#{roll}/index.html")[/<meta property="og:title" content="([^"]*)">/, 1] }
    assert_equal "A joint resolution providing for a vote", og.(1)
    assert_equal "On Passage", og.(2)
  end

  # A blank or whitespace-only title falls through to the next one, in the
  # heading, vote lists, the link card and the search title alike; a question that is the
  # title but for whitespace is named once in the search title, not "Q: Q".
  def test_whitespace_titles_fall_back_and_the_question_is_not_repeated
    base = EscapingTest::VOTE.merge("measure_title" => nil, "bill_type" => nil, "congress_gov_url" => nil)
    votes = [base.merge("measure_title" => "  ", "vote_title" => " A joint resolution providing for a vote\n"),
             base.merge("vote_id" => "h119-1-0002", "roll_number" => 2, "measure_title" => " ", "vote_title" => "\t",
                        "question" => "On Passage ")]
    pages = build_site([EscapingTest::MEMBER], votes.map { |v| [v, EscapingTest::DOC] })
    page = ->(roll) { pages.fetch("/votes/119/house/1/#{roll}/index.html") }
    h1 = ->(roll) { page.(roll)[%r{<h1 class="vote-h">(.*?)</h1>}m, 1] }
    og = ->(roll) { page.(roll)[/<meta property="og:title" content="([^"]*)">/, 1] }
    search = ->(roll) { page.(roll)[/data-title="([^"]*)"/, 1] }

    assert_equal "A joint resolution providing for a vote", h1.(1)
    assert_equal "A joint resolution providing for a vote", og.(1)
    assert_equal "On Passage: A joint resolution providing for a vote (House, Jan. 3, 2025)", search.(1)
    assert_equal "On Passage", h1.(2)
    assert_equal "On Passage", og.(2)
    assert_equal "On Passage (House, Jan. 3, 2025)", search.(2)
    list = pages.fetch("/votes/index.html")
    assert_includes list, %(<span class="t">A joint resolution providing for a vote</span>)
    assert_includes list, %(<span class="t">On Passage</span>)
  end

  # The search page keeps its fallback text until Pagefind's UI is built, so
  # a missing index or a failed constructor never leaves the area blank.
  def test_search_fallback_is_removed_only_after_the_ui_is_built
    html = build.fetch("/search/index.html")
    assert_match(%r{<div id="search" class="sitesearch-results">\s*<p class="soft" data-search-fallback>.*?<a class="link" href="/votes/">}m, html)
    built = html.index("new PagefindUI(")
    removed = html.index(%(document.querySelector("[data-search-fallback]").remove()))
    assert built && removed && built < removed, "fallback removed before new PagefindUI"
    assert_operator html.index(%(if (typeof PagefindUI === "undefined") return;)), :<, built
  end

  # A vote with a card from `yan cards` points og:image at it, with the title
  # and description as alt text; a vote without one keeps the brand card.
  def test_link_card_image_per_vote
    other = EscapingTest::VOTE.merge("vote_id" => "h119-1-0002", "roll_number" => 2)
    Dir.mktmpdir("cards", File.join(SOURCE, "assets")) do |dir|
      File.write(File.join(dir, "h119-1-0001.png"), "png")
      cards = "assets/#{File.basename(dir)}"
      pages = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC], [other, EscapingTest::DOC]],
                         cards: cards)
      meta = ->(roll, prop) { pages.fetch("/votes/119/house/1/#{roll}/index.html")[/<meta property="#{prop}" content="([^"]*)">/, 1] }
      assert_equal "https://yeasandnaysdata.com/#{cards}/h119-1-0001.png", meta.(1, "og:image")
      assert_equal "A bill to name the &quot;KK&quot; &lt;kk&gt; O&#39;Kay &amp; Co Post Office: " \
                   "House roll call 1, Jan. 3, 2025. Passage: Passed, 0 Yea · 1 Nay.", meta.(1, "og:image:alt")
      assert_equal "https://yeasandnaysdata.com/assets/brand/social/og-card-1200x630.png", meta.(2, "og:image")
      assert_equal "Yeas &amp; Nays: Recorded votes from the House and Senate.", meta.(2, "og:image:alt")
    end
  end

  # Present and Not Voting are left out of a vote's description when zero;
  # a Speaker election lists its candidates; a Vice President's tie-break is
  # named as in bot posts.
  def test_vote_description_tally
    view = ->(vote, tally) { { "vote" => EscapingTest::VOTE.merge(vote), "tally" => tally } }
    yn = [{ "label" => "Yea", "count" => 211, "mark" => "yea" }, { "label" => "Nay", "count" => 204, "mark" => "nay" },
          { "label" => "Present", "count" => 0, "mark" => "present" }, { "label" => "Not Voting", "count" => 18, "mark" => "nv" }]
    assert_equal "Senate roll call 257, Nov. 9, 2026. Nomination Confirmed, 211 Yea · 204 Nay · 18 Not Voting.",
                 Yan.vote_description(view.({ "chamber" => "senate", "roll_number" => 257, "vote_date" => "2026-11-09",
                                              "result_label" => "Nomination Confirmed" }, yn))
    # The vote's own words; Aye and No show even at zero, Present when nonzero.
    aye_no = [{ "label" => "Aye", "count" => 400, "mark" => "yea" }, { "label" => "No", "count" => 0, "mark" => "nay" },
              { "label" => "Present", "count" => 1, "mark" => "present" }, { "label" => "Not Voting", "count" => 0, "mark" => "nv" }]
    assert_equal "House roll call 1, Jan. 3, 2025. Passage: Passed, 400 Aye · 0 No · 1 Present.",
                 Yan.vote_description(view.({ "result_label" => "Passage: Passed" }, aye_no))
    speaker = [{ "label" => "Johnson", "count" => 216 }, { "label" => "Jeffries", "count" => 215 },
               { "label" => "Present", "count" => 0, "mark" => "present" }, { "label" => "Not Voting", "count" => 1, "mark" => "nv" }]
    assert_equal "House roll call 2, Jan. 3, 2025. Most votes: Mike Johnson (R-LA-4), 216 Johnson · 215 Jeffries · 1 Not Voting.",
                 Yan.vote_description(view.({ "roll_number" => 2, "result_label" => "Most votes: Mike Johnson (R-LA-4)" }, speaker))
    tie = [{ "label" => "Yea", "count" => 50, "mark" => "yea" }, { "label" => "Nay", "count" => 50, "mark" => "nay" }]
    assert_equal "Senate roll call 372, July 1, 2025. Bill Passed, 50 Yea · 50 Nay · Vice President voted Yea to break the tie.",
                 Yan.vote_description(view.({ "chamber" => "senate", "roll_number" => 372, "vote_date" => "2025-07-01",
                                              "result_label" => "Bill Passed", "tie_breaker_by" => "Vice President of the United States",
                                              "tie_breaker_vote" => "Yea" }, tie))
    # Both fields or no tie-break, as on the vote page.
    assert_equal "House roll call 1, Jan. 3, 2025. Bill Passed, 50 Yea · 50 Nay.",
                 Yan.vote_description(view.({ "result_label" => "Bill Passed", "tie_breaker_by" => "Vice President of the United States",
                                              "tie_breaker_vote" => nil }, tie))
  end

  # GitHub Pages serves /404.html for a missing address at any depth, so its
  # links and assets are root-relative. It's kept out of search engines and
  # the search index, and offers a search box and the main sections.
  def test_404_page
    pages = build
    html = pages.fetch("/404.html")
    assert_includes html, "<title>Page not found · Yeas & Nays</title>"
    assert_includes html, '<meta name="robots" content="noindex">'
    pages.each { |path, page| assert_equal path == "/404.html", page.include?('name="robots"'), path }
    refute_includes html, "data-pagefind-body"
    assert_match(%r{<form class="sitesearch inpage" action="/search/" method="get" role="search">.*?name="q"}m, html)
    hrefs = html.scan(/(?:href|src|srcset|action)="([^"]*)"/).flatten
    assert_empty hrefs.reject { |u| u.start_with?("/", "#", "https://") }
    %w[/ /votes/ /members/ /find/ /how/bills/ /how/expulsion/ /about/].each do |url|
      assert_includes hrefs, url
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
      assert_match(/#{Regexp.escape(tag)}[^>]* data-exclude-search="true"/, html, path)
      assert_includes html, opt_out, path
    end
    development.each do |path, html|
      refute_includes html, tag, path
      refute_includes html, opt_out, path
    end
  end

  # The sitemap lists every built HTML page but the 404 page by its full URL,
  # an index.html by its directory, and nothing else (no data files);
  # robots.txt points to it.
  def test_sitemap_lists_every_page_and_robots_points_to_it
    files = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]], files: "*.{html,xml,txt,json}",
                       pages: [["", "extra.html"], ["how", "notes.html"]])
    sitemap = files.fetch("/sitemap.xml")
    assert sitemap.start_with?('<?xml version="1.0" encoding="UTF-8"?>'), "XML declaration must come first"
    locs = sitemap.scan(%r{<loc>([^<]*)</loc>}).flatten
    pages = (files.keys.grep(/\.html\z/) - ["/404.html"]).map { |p| "https://yeasandnaysdata.com#{p.delete_suffix("index.html")}" }
    assert_includes files.keys, "/404.html"
    assert_equal locs.uniq, locs
    assert_equal pages.sort, locs.sort
    assert_includes locs, "https://yeasandnaysdata.com/votes/119/house/1/1/"
    assert_includes locs, "https://yeasandnaysdata.com/extra.html"
    assert_includes locs, "https://yeasandnaysdata.com/how/notes.html"
    assert_includes files.keys, "/activity/rollcalls.json"
    assert_equal "User-agent: *\nAllow: /\n\nSitemap: https://yeasandnaysdata.com/sitemap.xml\n", files.fetch("/robots.txt")
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
    m = { "bluesky_url" => "https://bsky.app/profile/a.example", "mastodon_url" => "https://m.example/@a", "x_url" => "https://x.com/a", "facebook_url" => nil }
    assert_equal [{ "label" => "X", "url" => "https://x.com/a", "icon" => "x" },
                  { "label" => "Mastodon", "url" => "https://m.example/@a", "icon" => "mastodon" },
                  { "label" => "Bluesky", "url" => "https://bsky.app/profile/a.example", "icon" => "bluesky" }],
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
    assert_equal({ "marks" => ["nv"], "title" => "Wyoming, At Large: Bo Bell (R), Not Voting" }, seats(map)["WY"])
    assert_equal "house", map["chamber"]
  end

  # S1's record is a senator's (their latest seat); the vote file gives the House seat held then.
  def test_a_member_now_in_the_senate_is_mapped_by_the_seat_held_then
    doc = { "members_as_of_vote" => { "S1" => { "chamber" => "house", "state" => "KY", "district" => 4, "party" => "D", "caucus_party" => "D" } } }
    map = Yan.state_map("house", { "A1" => "Aye", "S1" => "No" }, Yan.members_as_of(doc, MEMBERS), WORDS)
    assert_equal "Kentucky, 4th District: Ed Zee (D), No", seats(map)["KY-4"]["title"]
    assert_equal 0, map["unmapped"]
    assert_equal "senate", MEMBERS["S1"]["chamber"]
  end

  def test_a_senator_with_no_house_seat_on_record_stays_off_a_house_map_but_in_the_table
    map = Yan.state_map("house", { "A1" => "Aye", "S1" => "No" }, Yan.members_as_of({}, MEMBERS), WORDS)
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

class ResultLabelTest < Minitest::Test
  JOHNSON = { "bioguide_id" => "J000299", "official_full_name" => "Mike Johnson", "party" => "R",
              "chamber" => "house", "state" => "LA", "district" => 4 }.freeze

  def speaker(id)
    { "question" => "Election of the Speaker", "result" => "Johnson (LA)", "result_bioguide_id" => id }
  end

  def test_a_speaker_election_names_the_member_with_the_most_votes
    assert_equal "Most votes: Mike Johnson (R-LA-4)", Yan.result_label(speaker("J000299"), { "J000299" => JOHNSON })
  end

  # No match in dbt, or a member missing from members.json: the Clerk's text.
  def test_an_unmatched_speaker_result_stays_as_recorded
    assert_equal "Johnson (LA)", Yan.result_label(speaker(nil), { "J000299" => JOHNSON })
    assert_equal "Johnson (LA)", Yan.result_label(speaker("J000299"))
  end

  def test_a_bare_house_result_is_tied_to_its_question
    assert_equal "Motion to Refer: Passed", Yan.result_label({ "question" => "On Motion to Refer", "result" => "Passed" })
    assert_equal "Nomination Confirmed", Yan.result_label({ "question" => "On the Nomination", "result" => "Nomination Confirmed" })
  end

  def test_an_at_large_or_senate_seat_is_the_state_alone
    wy = JOHNSON.merge("bioguide_id" => "W000001", "official_full_name" => "Wy Member", "state" => "WY", "district" => 0)
    ky = JOHNSON.merge("bioguide_id" => "K000001", "official_full_name" => "Ky Member", "chamber" => "senate", "state" => "KY",
                       "district" => nil)
    assert_equal "Most votes: Wy Member (R-WY)", Yan.result_label(speaker("W000001"), { "W000001" => wy })
    assert_equal "Most votes: Ky Member (R-KY)", Yan.result_label(speaker("K000001"), { "K000001" => ky })
  end

  # Senate results already name their subject, so they read as recorded.
  def test_a_senate_result_stays_as_recorded
    v = { "chamber" => "senate", "question" => "On the Cloture Motion", "result" => "Cloture Motion Agreed to" }
    assert_equal "Cloture Motion Agreed to", Yan.result_label(v, { "J000299" => JOHNSON })
  end
end

# The site build's re-check of CRS summary HTML (the build test above covers
# hostile tags and attributes end to end).
class SummaryHtmlTest < Minitest::Test
  def test_balanced_allowed_tags_pass_unchanged
    html = "<p>One <em>two</em><br>three</p><ol><li><b>a</b><sub>2</sub></li></ol>"
    assert_equal html, Yan.summary_html(html)
  end

  def test_tags_left_open_are_closed_at_the_end
    assert_equal "<ul><li>one</li></ul>", Yan.summary_html("<ul><li>one")
    assert_equal "<p>a <strong>b</strong></p>", Yan.summary_html("<p>a <strong>b")
  end

  def test_a_closing_tag_closes_the_tags_opened_inside_it
    assert_equal "<ul><li><em>one</em></li></ul><p>x</p>", Yan.summary_html("<ul><li><em>one</ul><p>x</p>")
  end

  def test_a_closing_tag_with_nothing_to_close_is_escaped
    assert_equal "a&lt;/p&gt;<ul>b</ul>&lt;/ul&gt;&lt;/br&gt;", Yan.summary_html("a</p><ul>b</ul></ul></br>")
  end

  # The pipeline writes tags in lower case, with nothing inside the brackets.
  def test_uppercase_or_spaced_tags_are_escaped
    assert_equal "&lt;P&gt;a&lt;/P&gt;", Yan.summary_html("<P>a</P>")
    assert_equal "&lt;p\n&gt;a&lt;/p &gt;", Yan.summary_html("<p\n>a</p >")
    assert_equal "&lt;\np&gt;", Yan.summary_html("<\np>")
  end

  def test_no_text_unless_a_string
    [nil, 1, ["<p>a</p>"], { "html" => "<p>a</p>" }].each { |html| assert_nil Yan.summary_html(html), html.inspect }
  end

  def test_no_text_unless_valid_utf8
    assert_nil Yan.summary_html("<p>a\xFF</p>")
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
       [vote(2, "Election of the Speaker").merge("result" => "Johnson", "result_bioguide_id" => "A000001"),
        doc({ "A000001" => "Johnson", "A000002" => "Johnson", "A000003" => "Not Voting" },
                                                { "other" => 2, "not_voting" => 1 })]]
    )
  end

  def test_every_position_is_on_the_party_grid_and_the_state_map
    html = pages.fetch("/votes/119/house/1/1/index.html")
    %w[yea present nv].each { |mark| assert_equal 1, html.scan(%(<g class="dot #{mark}")).size, mark }
    assert_includes html, '<g class="dot nay" fill="url(#hatch-R)">'
    assert_includes html, 'data-vmap data-src="/assets/maps/119.json" data-chamber="house"'
    assert_includes html, '<h2 id="state-h" class="section-h sm">By district</h2>'
    seats = JSON.parse(html[%r{<script type="application/json" data-seats>(.*?)</script>}m, 1])
    assert_equal({ "AL-1" => ["yea"], "AL-2" => ["present"], "AL-3" => ["nv"], "AL-4" => ["nay"] },
                 seats.transform_values { |s| s["marks"] })
    assert_includes html, %(<th scope="row">Alabama</th><td class="r">1</td><td class="r">1</td><td class="r">1</td><td class="r">1</td>)
    # A000005's state code isn't on the map.
    assert_includes html, "Not on the map: 1 member with no seat drawn on it, such as a delegate from the District of Columbia " \
                          "or a territory. See the table by state."
  end

  # A member who has since changed party, caucus and district shows as they
  # were, on the vote page and the member page.
  def test_a_vote_shows_members_party_and_seat_as_of_the_vote
    now = member("A000001", "AL", 7).merge("party" => "I", "caucus_party" => "D")
    then_seat = { "chamber" => "house", "state" => "AL", "district" => 1, "party" => "R", "caucus_party" => "R" }
    d = doc({ "A000001" => "Nay" }, { "no" => 1 }).merge(
      "members_as_of_vote" => { "A000001" => then_seat }, "caucus_majority_position" => { "R" => "yes", "D" => "no" },
      "against_party_majority" => [{ "bioguide_id" => "A000001", "position" => "Nay" }]
    )
    built = build_site([now], [[vote(1, "On Passage"), d]])
    html = built.fetch("/votes/119/house/1/1/index.html")
    assert_includes html, "R-AL-1"
    refute_includes html, "AL-7"
    seats = JSON.parse(html[%r{<script type="application/json" data-seats>(.*?)</script>}m, 1])
    assert_equal({ "AL-1" => "Alabama, 1st District: Member A000001 (R), Nay" }, seats.transform_values { |s| s["title"] })
    assert_includes html, "R majority voted Yea"
    assert_includes built.fetch("/members/A000001/index.html"), "R majority voted Yea"
  end

  def test_a_speaker_election_names_the_top_candidate_by_party_and_seat_as_of_the_vote
    now = member("A000001", "AL", 7).merge("party" => "I", "caucus_party" => "D")
    then_seat = { "chamber" => "house", "state" => "AL", "district" => 1, "party" => "R", "caucus_party" => "R" }
    v = vote(1, "Election of the Speaker").merge("result" => "Alpha", "result_bioguide_id" => "A000001")
    d = doc({ "A000001" => "Alpha" }, { "other" => 1 }).merge("members_as_of_vote" => { "A000001" => then_seat })
    html = build_site([now], [[v, d]]).fetch("/votes/119/house/1/1/index.html")
    assert_includes html, "Most votes: Member A000001 (R-AL-1)"
    refute_includes html, "AL-7"
  end

  # Another Congress's vote gets that Congress's map only when its file gives seats as of the vote.
  def test_another_congress_gets_its_own_map_with_seats_as_of_the_vote
    other = vote(1, "On Passage").merge("vote_id" => "h120-1-0001", "congress" => 120)
    d = doc({ "A000001" => "Yea" }, { "yes" => 1 })
    page = ->(doc) { build_site([member("A000001", "AL", 1)], [[other, doc]]).fetch("/votes/120/house/1/1/index.html") }
    assert_includes page.call(d.merge("members_as_of_vote" => {})), 'data-src="/assets/maps/120.json"'
    refute_includes page.call(d), "data-vmap"
  end

  # A vote with no measure or vote title (a Speaker election) has the question
  # as its search result title once, not "question: question".
  def test_a_speaker_election_search_title_names_the_question_once
    assert_includes pages.fetch("/votes/119/house/1/2/index.html"),
                    'data-title="Election of the Speaker (House, Jan. 3, 2025)"'
  end

  # A definition with an explainer page links it from the vote page and About;
  # one without links only How votes work.
  def test_an_expulsion_vote_links_the_explainer
    expel = vote(1, "On Agreeing to the Resolution").merge("measure_title" => "Expelling Member A000001")
    built = build_site([member("A000001", "AL", 1)],
                       [[expel, doc({ "A000001" => "Yea" }, { "yes" => 1 })],
                        [vote(2, "On Passage"), doc({ "A000001" => "Yea" }, { "yes" => 1 })]])
    link = '<a class="link small" href="/how/expulsion/" data-pagefind-ignore>How expulsion works</a>'
    assert_includes built.fetch("/votes/119/house/1/1/index.html"), link
    refute_includes without_footer(built.fetch("/votes/119/house/1/2/index.html")), "/how/expulsion/"
    assert_includes built.fetch("/about/index.html"), '<a href="/how/expulsion/">How expulsion works</a>.'
    assert_includes built.fetch("/how/expulsion/index.html"), "<h1 class=\"vote-h\">How expulsion works</h1>"
  end

  # A vote on a measure links How a bill becomes law; a vote with no measure doesn't.
  def test_a_vote_on_a_measure_links_how_a_bill_becomes_law
    built = build_site([member("A000001", "AL", 1)],
                       [[vote(1, "On Passage").merge("bill_type" => "hr"), doc({ "A000001" => "Yea" }, { "yes" => 1 })],
                        [vote(2, "On Passage"), doc({ "A000001" => "Yea" }, { "yes" => 1 })]])
    link = '<a class="link small" href="/how/bills/" data-pagefind-ignore>How a bill becomes law</a>'
    assert_includes built.fetch("/votes/119/house/1/1/index.html"), link
    refute_includes without_footer(built.fetch("/votes/119/house/1/2/index.html")), "/how/bills/"
    assert_includes without_footer(built.fetch("/about/index.html")), '<a href="/how/bills/">How a bill becomes law</a>'
    assert_includes built.fetch("/how/bills/index.html"), "<h1 class=\"vote-h\">How a bill becomes law</h1>"
  end

  # A vote page links its kind of vote's dictionary entry, which the
  # dictionary page has as an anchor, alongside every other entry; About and
  # the 404 page link the dictionary.
  def test_a_vote_links_its_dictionary_entry
    built = build_site([member("A000001", "AL", 1)],
                       [[vote(1, "On Motion to Table"), doc({ "A000001" => "Yea" }, { "yes" => 1 })]])
    assert_includes built.fetch("/votes/119/house/1/1/index.html"),
                    '<a class="link small" href="/how/dictionary/#table" data-pagefind-ignore>Motion to table in the dictionary</a>'
    page = built.fetch("/how/dictionary/index.html")
    ids = page.scan(/<dt id="([^"]*)">/).flatten
    assert_equal Yan.dictionary(ProcedureTest::PROCEDURES).map { |e| e["key"] }, ids
    assert_includes page, '<dt id="filibuster">Filibuster (Senate)</dt>'
    assert_includes page, 'See also: <a href="#cloture">Cloture (Senate)</a>.</dd>'
    assert_includes page, '<a href="/how/expulsion/">How expulsion works</a>.'
    page[%r{<dl>.*</dl>}m].scan(/href="#([^"]*)"/).flatten.each { |id| assert_includes ids, id }
    assert_includes built.fetch("/about/index.html"), '<a href="/how/dictionary/">dictionary of floor terms</a>'
    assert_includes without_footer(built.fetch("/404.html")), 'href="/how/dictionary/"'
  end

  def path_doc
    doc({ "A000001" => "Yea" }, { "yes" => 1 }).merge("path" => { "track" => "law", "steps" => [
      { "key" => "introduced", "label" => "Introduced", "status" => "done", "date" => "2025-01-03",
        "anchor" => "introduced", "current" => false },
      { "key" => "passed_house", "label" => "Passed House", "status" => "done", "date" => "2025-02-01",
        "anchor" => "first-chamber", "current" => true },
      { "key" => "differences", "label" => "Differences resolved", "status" => "skipped", "date" => nil,
        "anchor" => "differences", "current" => false },
      { "key" => "became_law", "label" => "Became law", "status" => "upcoming", "date" => nil,
        "anchor" => "president", "current" => false },
    ] })
  end

  # The path lists each step with its date or status, marks the step this vote was
  # taken at, and links each step to its part of How a bill becomes law.
  def test_a_vote_on_a_measure_shows_its_path
    v = vote(1, "On Passage").merge("bill_type" => "hr", "measure_number" => "H R 1", "measure_label" => "H.R. 1")
    built = build_site([member("A000001", "AL", 1)],
                       [[v, path_doc], [vote(2, "On Passage"), doc({ "A000001" => "Yea" }, { "yes" => 1 })]])
    html = built.fetch("/votes/119/house/1/1/index.html")
    assert_includes html, '<h2 id="path-h" class="section-h sm">Path of H.R. 1</h2>'
    assert_includes html, '<li class="step done current" aria-current="step">'
    assert_match %r{<span class="kicker">This vote was taken here</span>\s+<a class="link" href="/how/bills/#first-chamber">Passed House</a>}, html
    assert_includes html, "Feb. 1, 2025"
    assert_includes html, "Not needed"
    assert_includes html, '<span class="visually-hidden">Not reached</span>'
    refute_includes built.fetch("/votes/119/house/1/2/index.html"), 'id="path-h"'
  end

  def test_the_path_view_keeps_only_known_statuses_anchors_and_dates
    path = { "steps" => [
      { "label" => "A", "status" => "done", "date" => "2025-13-99x", "anchor" => "elsewhere", "current" => "yes" },
      { "label" => "B", "status" => "unknown" },
      { "label" => 5, "status" => "done" },
    ] }
    assert_equal [{ "label" => "A", "status" => "done", "current" => false, "date" => nil, "anchor" => nil }],
                 Yan.bill_path_view(path)
    assert_nil Yan.bill_path_view({ "steps" => [{ "label" => "B", "status" => "unknown" }] })
    assert_nil Yan.bill_path_view(nil)
    assert_nil Yan.bill_path_view({ "steps" => [] })
  end

  # Every senator has a state, so on a Senate vote only one with no state on
  # record is off the map, and the table by state can't list them either.
  def test_a_senate_vote_names_senators_with_no_state_on_record
    senator = ->(id, state) { member(id, state, nil).merge("chamber" => "senate") }
    senate_vote = ->(roll) { vote(roll, "On Passage").merge("vote_id" => "s119-1-000#{roll}", "chamber" => "senate") }
    built = build_site([senator["S000001", "AL"], senator["S000002", "ZZ"], senator["S000003", "ZZ"]],
                       [[senate_vote[1], doc({ "S000001" => "Yea", "S000002" => "Nay" }, { "yes" => 1, "no" => 1 })],
                        [senate_vote[2], doc({ "S000001" => "Yea", "S000002" => "Nay", "S000003" => "Nay" },
                                             { "yes" => 1, "no" => 2 })]])
    one = built.fetch("/votes/119/senate/1/1/index.html")
    assert_includes one, 'data-chamber="senate"'
    assert_includes one, '<h2 id="state-h" class="section-h sm">By state</h2>'
    assert_includes one, "Not on the map: 1 senator with no state on record. District and state lines"
    refute_includes one, "such as a delegate"
    assert_includes built.fetch("/votes/119/senate/1/2/index.html"), "Not on the map: 2 senators with no state on record."
  end

  # The built site's meta is the 119th Congress. A 120th vote has shapes but its
  # members' districts aren't known; a 99th vote has no shapes at all.
  def test_map_only_for_votes_in_the_member_datas_congress_with_shapes
    built = build_site([member("A000001", "AL", 1)],
                       [99, 120].map { |c| [vote(1, "On Passage").merge("congress" => c), doc({ "A000001" => "Yea" }, { "yes" => 1 })] })
    %w[99 120].each do |c|
      html = built.fetch("/votes/#{c}/house/1/1/index.html")
      # With no map to draw districts, the House heading names the table.
      assert_includes html, '<h2 id="state-h" class="section-h sm">By state</h2>', c
      refute_includes html, "data-vmap", c
    end
  end

  # The House's records don't give the share, so for both chambers it comes from required_share.
  def test_the_tally_note_gives_the_yeas_needed_and_the_share
    built = build_site([member("A000001", "AL", 1)],
                       [[vote(1, "On Motion to Suspend the Rules and Pass").merge("required_share" => "2/3", "yeas_needed" => 1,
                                                                             "yea_count" => 1, "nay_count" => 0),
                         doc({ "A000001" => "Yea" }, { "yes" => 1 })],
                        [vote(2, "On Passage").merge("required_share" => "3/5"), doc({ "A000001" => "Yea" }, { "yes" => 1 })],
                        [vote(3, "On Passage"), doc({ "A000001" => "Yea" }, { "yes" => 1 })]])
    assert_includes built.fetch("/votes/119/house/1/1/index.html"), "1 members recorded. 1 needed to carry, two-thirds of those voting."
    assert_includes built.fetch("/votes/119/house/1/2/index.html"), "1 members recorded. Needed to carry: three-fifths of senators."
    three = built.fetch("/votes/119/house/1/3/index.html")
    assert_includes three, "1 members recorded."
    refute_includes three, "needed"
  end

  def test_no_grids_for_a_speaker_election
    html = pages.fetch("/votes/119/house/1/2/index.html")
    refute_includes html, "grid-chart"
    refute_includes html, "By state"
    assert_includes html, '<span class="kicker result">Most votes: Member A000001 (R-AL-1)</span>'
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
    ], "senate_next_convene_et" => "2026-11-16T15:00:00" }, votes, Date.new(2026, 11, 13))

    assert_equal ["c"], view["upcoming_house"].map { |i| i["item_id"] }
    assert_equal "2026-11-16", view["upcoming_week"]
    assert_equal ["d"], view["upcoming_senate"].map { |i| i["item_id"] }
    assert_equal ["2026-11-09", "2026-11-16"], view["house_weeks"].map { |w| w["week_date"] }
    voted = view["house_weeks"].last["groups"].first["items"].first
    assert_equal ["/votes/119/house/2/1/", "Passed"], [voted["vote_url"], voted["result_label"]]
    assert_equal "Monday, Nov. 16, 2026, at 3 p.m. ET", view["senate_next_convene"]
  end

  def test_senate_items_without_a_house_schedule
    view = Yan.schedule_view({ "items" => [item("senate", "d")] }, {}, Date.new(2026, 11, 13))
    assert_equal [["d"], [], nil, []],
                 [view["upcoming_senate"].map { |i| i["item_id"] }, view["upcoming_house"], view["upcoming_week"],
                  view["house_weeks"]]
  end

  def test_empty_schedule
    view = Yan.schedule_view({ "items" => [] }, {}, Date.new(2026, 11, 13))
    assert_equal [[], [], nil, nil], view.values_at("upcoming_house", "upcoming_senate", "upcoming_week",
                                                   "senate_next_convene")
  end

  def test_a_convene_time_already_past_is_left_out_of_the_text
    schedule = { "items" => [], "senate_next_convene_et" => "2026-11-16T15:00:00" }
    assert_equal "Monday, Nov. 16, 2026, at 3 p.m. ET",
                 Yan.schedule_view(schedule, {}, Time.new(2026, 11, 16, 14, 59))["senate_next_convene"]
    assert_nil Yan.schedule_view(schedule, {}, Time.new(2026, 11, 16, 15, 1))["senate_next_convene"]
  end
end

# One House item in a floor schedule export.
module HouseItem
  def house(id, label, title, bill_type: nil, url: nil, vote_id: nil)
    { "chamber" => "house", "item_id" => id, "week_date" => "2026-11-09",
      "category" => "Items that may be considered under suspension of the rules", "question" => nil,
      "measure_number" => label, "bill_type" => bill_type, "measure_label" => label, "title" => title,
      "amends" => nil, "congress_gov_url" => url, "vote_id" => vote_id }
  end
end

# Builds /schedule/ on Friday, Nov. 13, 2026, from a small floor schedule export.
class SchedulePageTest < Minitest::Test
  include SiteBuild
  include HouseItem

  MEMBER = {
    "bioguide_id" => "Z000001", "official_full_name" => "Jane Doe", "first_name" => "Jane", "last_name" => "Doe",
    "party" => "R", "caucus_party" => "R", "chamber" => "house", "state" => "AL", "district" => 4,
    "is_current" => true, "is_voting_member" => true
  }.freeze

  VOTE = {
    "vote_id" => "h119-2-0316", "congress" => 119, "chamber" => "house", "session" => 2, "roll_number" => 316,
    "vote_date" => "2026-11-10", "question" => "On Passage", "result" => "Passed", "bill_type" => "hr",
    "bill_number" => "5549", "measure_number" => "H R 5549", "measure_title" => "Voted Act"
  }.freeze

  DOC = { "positions" => { "Z000001" => "Yea" }, "party_totals" => { "R" => { "yes" => 1 } },
          "caucus_majority_position" => {}, "against_party_majority" => [], "summary" => nil }.freeze

  def senate(id, label, title, amends: nil)
    { "chamber" => "senate", "item_id" => id, "filed_date" => "2026-11-12", "question" => "On the Cloture Motion",
      "measure_number" => nil, "bill_type" => nil, "measure_label" => label, "title" => title,
      "amends" => amends, "congress_gov_url" => nil, "vote_id" => nil }
  end

  def page
    @page ||= build_site([MEMBER], [[VOTE, DOC]], files: "schedule/index.html", time: "2026-11-13 12:00:00 -0500",
                         schedule: { "items" => [
                           house("a", "H.R. 3978", "Linked Act", bill_type: "hr",
                                 url: "https://www.congress.gov/bill/119th-congress/house-bill/3978"),
                           house("b", "H.R. 5549", "Voted Act", bill_type: "hr", vote_id: "h119-2-0316"),
                           house("c", "H. Res. ___", "Unnumbered resolution"),
                           house("f", nil, "House item with no label"),
                           senate("d", "PN1272-3", "A nomination"),
                           senate("e", "Amendment to H.R. 2347", "An amendment", amends: "H.R. 2347"),
                           senate("g", nil, "Senate item with no label")
                         ], "senate_next_convene_et" => "2026-11-16T15:00:00" })["/schedule/index.html"]
  end

  def week(date) = page[/<section class="cal-week" data-row data-week="#{date}".*?<\/section>/m]

  def test_the_convene_time_shows_until_it_has_passed
    assert_includes page, "The Senate is scheduled to convene Monday, Nov. 16, 2026, at 3 p.m. ET."
    assert_includes week("2026-11-16"), "3 p.m. ET"
    after = build_site([MEMBER], [[VOTE, DOC]], files: "schedule/index.html", time: "2026-11-16 15:30:00 -0500",
                       schedule: { "items" => [], "senate_next_convene_et" => "2026-11-16T15:00:00" })
    refute_includes after["/schedule/index.html"], "scheduled to convene"
    refute_includes after["/schedule/index.html"], "3 p.m. ET"
  end

  def test_house_items_are_pending_in_their_week_and_the_voted_one_is_on_its_day
    this_week = week("2026-11-09")
    pending = this_week[/House: on this week.*/m]
    assert_includes pending, %(href="https://www.congress.gov/bill/119th-congress/house-bill/3978")
    assert_includes pending, "Items that may be considered under suspension of the rules"
    refute_includes pending, "Voted Act"
    # The roll call is in Tuesday's cell, the day it was taken.
    tuesday = this_week[/<span class="kicker soft">Tue<\/span>.*?<span class="kicker soft">Wed<\/span>/m]
    assert_includes tuesday, %(<a class="headline-link" href="/votes/119/house/2/316/">)
  end

  def test_house_items_decided_without_a_roll_call_show_the_clerks_wording
    items = [house("a", "H.R. 1", "Pending Act"),
             house("b", "H.R. 2", "Decided Act").merge(
               "decided_date" => "2026-11-10", "decided_question" => "On motion to suspend the rules & pass the bill",
               "decided_outcome" => "Agreed to by voice vote"
             )]
    html = build_site([MEMBER], [[VOTE, DOC]], files: "schedule/index.html", time: "2026-11-13 12:00:00 -0500",
                      schedule: { "items" => items })["/schedule/index.html"]
    pending, decided = html.split("decided without a roll call</h4>", 2)
    assert_includes pending, "no decision recorded yet</h4>"
    refute_includes pending, "Decided Act"
    assert_includes li(decided, "Decided Act"),
                    "On motion to suspend the rules &amp; pass the bill: Agreed to by voice vote, Nov. 10, 2026"
  end

  # The home page passes each item's place to start rows past its third
  # hidden; this page doesn't, so every item shows.
  def test_no_item_starts_hidden
    assert_operator page.scan('<li class="vote-item"').size, :>, 3
    refute_match(/<li class="vote-item"[^>]* hidden>/, page)
  end

  def test_an_item_with_no_bill_type_or_link_is_unlinked
    item = li(week("2026-11-09"), "Unnumbered resolution")
    assert_includes item, %(<div class="unlinked">)
    assert_includes item, "H. Res. ___"
    refute_includes item, "<a "
  end

  def li(html, title) = html[/<li class="vote-item"[^>]*>(?:(?!<\/li>).)*#{Regexp.escape(title)}.*?<\/li>/m]

  def test_an_item_with_no_label_shows_no_empty_kicker_or_separator
    house = li(week("2026-11-09"), "House item with no label")
    refute_includes house, "kicker"
    senate = li(week("2026-11-16"), "Senate item with no label")
    assert_includes senate, %(<span class="small soft">On the Cloture Motion</span>)
  end

  def test_cloture_motions_sit_in_the_week_the_senate_next_convenes
    refute_includes week("2026-11-09"), "Senate: cloture motions filed"
    next_week = week("2026-11-16")
    assert_includes next_week, "Cloture filed Nov. 12, 2026"
    assert_includes next_week, "On the Cloture Motion · PN1272-3"
    assert_includes next_week, "On the Cloture Motion · Amendment to H.R. 2347"
    assert_includes page, "The Senate is scheduled to convene Monday, Nov. 16, 2026, at 3 p.m. ET."
  end

  def test_the_senate_note_gives_cloture_timing_from_procedures_yml
    cloture = ProcedureTest::PROCEDURES["questions"].find { |q| q["key"] == "cloture" }
    refute_empty cloture["timing"].to_s
    assert_includes page, "#{cloture["definition"]} #{cloture["timing"]} Source:"
  end

  # The footer's "Watch live" link lands on this section.
  def test_the_live_section_links_each_chambers_official_feeds
    live = page[%r{<section id="live".*?</section>}m]
    %w[https://www.senate.gov/floor/ https://www.senate.gov/legislative/floor_activity_pail.htm
       https://www.youtube.com/USHouseClerk/live https://live.house.gov/
       https://clerk.house.gov/FloorSummary].each do |url|
      assert_includes live, %(href="#{url}"), url
    end
    assert_includes page, '<a href="/schedule/#live">Watch live</a>'
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

  def calendar(items, votes, now = FRIDAY, convene = "2026-11-16T15:00:00")
    view = Yan.schedule_view({ "items" => items, "senate_next_convene_et" => convene }, {}, now)
    Yan.schedule_calendar(view, votes, now, convene)
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

  def test_house_items_decided_without_a_roll_call_are_listed_apart
    decided = { "decided_date" => "2026-11-10", "decided_question" => "On passage",
                "decided_outcome" => "Passed by voice vote" }
    items = [item("house", "a", week: "2026-11-09"), item("house", "b", week: "2026-11-09").merge(decided)]
    this_week = week(calendar(items, []), "2026-11-09")
    assert_equal ["a"], this_week["house_pending"].flat_map { |g| g["items"].map { |i| i["item_id"] } }
    assert_equal [["b", "On passage: Passed by voice vote, Nov. 10, 2026"]],
                 this_week["house_decided"].map { |i| i.values_at("item_id", "decided_label") }
    assert_equal ["a"], Yan.schedule_view({ "items" => items }, {}, FRIDAY)["upcoming_house"].map { |i| i["item_id"] }
    # Like pending items, they drop off once the week's Friday has passed.
    assert_equal [], week(calendar(items, [], Date.new(2026, 11, 14), nil), "2026-11-09")["house_decided"]
  end

  def test_a_pro_forma_senate_session_is_labeled
    schedule = { "items" => [], "senate_next_convene_et" => "2026-11-16T15:00:00",
                 "floor_status" => { "senate" => { "next_convene_pro_forma" => true } } }
    view = Yan.schedule_view(schedule, {}, FRIDAY)
    assert_equal "Monday, Nov. 16, 2026, at 3 p.m. ET (pro forma session)", view["senate_next_convene"]
    cal = Yan.schedule_calendar(view, [], FRIDAY, "2026-11-16T15:00:00")
    assert_equal ["3 p.m. ET (pro forma session)"], cal["weeks"].flat_map { |w| w["days"] }.filter_map { |d| d["convene"] }
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

  def test_a_convene_time_earlier_today_is_dropped_once_passed
    convenes = ->(cal) { cal["weeks"].flat_map { |w| w["days"] }.filter_map { |d| d["convene"] } }
    assert_equal ["3 p.m. ET"], convenes.call(calendar([], [], Time.new(2026, 11, 16, 14, 59), "2026-11-16T15:00:00"))
    assert_equal [], convenes.call(calendar([], [], Time.new(2026, 11, 16, 15, 1), "2026-11-16T15:00:00"))
  end

  def test_an_empty_schedule_still_lists_this_week_and_the_two_before
    cal = calendar([], [], FRIDAY, nil)
    assert_equal %w[2026-10-26 2026-11-02 2026-11-09], cal["weeks"].map { |w| w["week_date"] }
    assert_equal "2026-11-09", cal["default_week"]
    assert(cal["weeks"].all? { |w| w["house_pending"].empty? && w["senate_pending"].empty? && w["roll_calls"].zero? })
  end

  def test_weekend_opens_on_the_coming_week_when_it_has_something_listed
    saturday = Date.new(2026, 11, 14)
    assert_equal "2026-11-16", calendar([], [], saturday)["default_week"]
    assert_equal "2026-11-09", calendar([], [], saturday, nil)["default_week"]
    # A recess: the Senate next convenes weeks out, so open on this week.
    assert_equal "2026-11-09", calendar([], [], saturday, "2026-12-07T15:00:00")["default_week"]
  end

  def test_a_weekend_senate_session_keeps_the_page_on_this_week
    sunday = Date.new(2026, 11, 15)
    cal = calendar([item("house", "a", week: "2026-11-16"), item("senate", "d")], [], sunday, "2026-11-15T13:00:00")
    assert_equal "2026-11-09", cal["default_week"]
    this_week = week(cal, "2026-11-09")
    assert_equal ["Sun", "1 p.m. ET"], this_week["days"].last.values_at("weekday", "convene")
    assert_equal ["d"], this_week["senate_pending"].map { |i| i["item_id"] }
    assert_equal ["a"], week(cal, "2026-11-16")["house_pending"].flat_map { |g| g["items"].map { |i| i["item_id"] } }
    # Once that session has convened, open on next week with the motions.
    later = calendar([item("house", "a", week: "2026-11-16"), item("senate", "d")], [],
                     Time.new(2026, 11, 15, 13, 30), "2026-11-15T13:00:00")
    assert_equal "2026-11-16", later["default_week"]
    assert_equal ["d"], week(later, "2026-11-16")["senate_pending"].map { |i| i["item_id"] }
    assert_nil week(later, "2026-11-09")["days"].last["convene"]
  end

  def test_without_a_convene_time_cloture_motions_go_in_the_opening_week
    saturday = Date.new(2026, 11, 14)
    cal = calendar([item("house", "a", week: "2026-11-16"), item("senate", "d")], [], saturday, nil)
    assert_equal "2026-11-16", cal["default_week"]
    assert_equal ["d"], week(cal, "2026-11-16")["senate_pending"].map { |i| i["item_id"] }
  end

  def test_a_day_spanning_two_sessions_lists_the_earlier_session_first
    v1 = vote("a", "2027-01-03", "house", 700).merge("congress" => 119, "session" => 2)
    v2 = vote("b", "2027-01-03", "house", 1).merge("congress" => 120, "session" => 1)
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
    assert_equal "passage", Yan.vote_kind("expel")
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

  def test_a_small_segment_stays_above_the_baseline_and_inside_the_chart
    votes = [vote("house", "2026-11-10", "passage")] + Array.new(399) { vote("house", "2026-11-10", "recommit") }
    segments = Yan.vote_volume(votes)["chambers"].first["weeks"].first["segments"]
    assert_equal({ "kind" => "passage", "y" => 199.0, "h" => 1 }, segments.first) # half a unit tall by its count
    segments.each { |s| assert_operator s["y"] + s["h"], :<=, Yan::VOLUME_HEIGHT }
    # Last in a stack that reaches the top: the 1-unit minimum stops at the chart's edge.
    votes = Array.new(399) { vote("house", "2026-11-10", "passage") } + [vote("house", "2026-11-10", "recommit")]
    assert_equal 0, Yan.vote_volume(votes)["chambers"].first["weeks"].first["segments"].last["y"]
  end

  def test_tick_steps_grow_with_the_busiest_week
    { 20 => [0, 5, 10, 15, 20], 21 => [0, 10, 20, 30], 50 => [0, 10, 20, 30, 40, 50], 51 => [0, 20, 40, 60] }.each do |n, ticks|
      vol = Yan.vote_volume(Array.new(n) { vote("house", "2026-11-10", "passage") })
      assert_equal ticks, vol["y_ticks"].map { |t| t["value"] }
      # Evenly spaced, from the baseline up to the top edge.
      assert_equal ticks.map { |t| (Yan::VOLUME_HEIGHT * (1 - t.to_f / ticks.last)).round(1) }, vol["y_ticks"].map { |t| t["y"] }
    end
  end

  def test_the_week_of_dec_29_holds_the_january_tick
    vol = Yan.vote_volume([vote("house", "2025-12-29", "passage"), vote("house", "2026-01-06", "passage")])
    assert_equal [{ "pct" => 0.0, "label" => "Jan. 2026" }], vol["x_ticks"]
  end

  def test_activity_page_with_one_chamber_has_one_chart_and_no_shared_scale_note
    html = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])["/activity/index.html"]
    assert_equal 1, html.scan('<figure class="vol"').size
    refute_includes html, "Both charts use the same scale"
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
    areas = { "house" => [*%w[Health Health Health Taxation Taxation], nil], "senate" => %w[Taxation Taxation Energy] }
    fields = areas.flat_map { |chamber, list| list.map { |area| { "chamber" => chamber, "policy_area" => area } } } +
             # A Senate nomination and a Senate vote that records no bill.
             [{ "chamber" => "senate", "bill_type" => nil, "measure_number" => "PN5" }, { "chamber" => "senate", "bill_type" => nil }]
    votes = fields.each_with_index.map do |f, i|
      [EscapingTest::VOTE.merge("vote_id" => "#{f["chamber"][0]}119-1-#{i + 1}", "roll_number" => i + 1).merge(f), EscapingTest::DOC]
    end
    pages = build_site([EscapingTest::MEMBER], votes, files: "*.{html,json}")
    html = pages["/activity/index.html"]
    # Each bar's count is the number of rows activity.js lists for it.
    listed = JSON.parse(pages.fetch("/activity/rollcalls.json"))["votes"]
    weeks = html.scan(/data-chamber="(\w+)" data-week="([^"]*)"[^>]*data-total="(\d+)"/)
    assert_equal %w[house senate], weeks.map(&:first).uniq
    weeks.each { |c, w, n| assert_equal n.to_i, listed.count { |v| v["c"] == c && v["w"] == w }, [c, w] }
    section = html[/<section class="section" aria-labelledby="area-h">.*?<\/section>/m]
    bars = section.scan(/data-chamber="(\w+)" data-area="([^"]*)"[^>]*data-total="(\d+)"/)
    bars.each { |c, a, n| assert_equal n.to_i, listed.count { |v| v["c"] == c && v["a"] == a }, [c, a] }
    rows = section.scan(%r{<tr><th scope="row">([^<]*)</th><td class="r">(\d+)</td><td class="r">(\d+)</td><td class="r">(\d+)</td></tr>})
    # Taxation 4, Health 3, Energy 1: each area's House and Senate bars carry the counts in its table row, in the same order.
    # The votes with no area get table rows last but no bars, and are counted under the chart instead.
    assert_equal [["Taxation", "2", "2", "4"], ["Health", "3", "0", "3"], ["Energy", "0", "1", "1"],
                  ["Nominations", "0", "1", "1"], ["No bill recorded", "0", "1", "1"], ["Not yet assigned", "1", "0", "1"]], rows
    assert_equal rows[0, 3].flat_map { |a, h, s, _| [["house", a, h], ["senate", a, s]] }, bars
    assert_includes section.gsub(/\s+/, " "), "Not drawn above, as no policy area is recorded for them: " \
                                                "Nominations (Senate 1); No bill recorded (Senate 1); Not yet assigned (House 1)."
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

# The home page's modules: closest votes, votes with members against their
# party's majority, this week's roll calls and the top policy areas.
class LiveFloorTest < Minitest::Test
  include SiteBuild

  def status(convened: nil, next_at: nil, pro_forma: nil)
    { "convened_at" => convened, "next_convene_at" => next_at, "next_convene_pro_forma" => pro_forma }
  end

  def test_a_line_per_chamber_from_its_convening_or_its_next
    lines = Yan.live_floor("senate" => status(next_at: "2026-11-16T15:00:00-05:00", pro_forma: false),
                           "house" => status(convened: "2026-11-17T12:00:04-05:00"))
    assert_equal %w[senate house], lines.map { |l| l["chamber"] }
    assert_equal ["Scheduled to convene at 3 p.m. ET", "Convened at noon ET"], lines.map { |l| l["label"] }
    assert_equal [false, true], lines.map { |l| l["in_session"] }
    assert_equal ["2026-11-16T15:00:00-05:00", "2026-11-17T12:00:04-05:00"], lines.map { |l| l["from"] }
    assert_equal ["https://www.senate.gov/floor/", "https://www.youtube.com/USHouseClerk/live"], lines.map { |l| l["watch_url"] }
  end

  # Summer time: the label stays in Eastern wall-clock time.
  def test_the_label_reads_in_eastern_time
    lines = Yan.live_floor("senate" => status(next_at: "2026-07-02T10:30:00-04:00"))
    assert_equal ["Scheduled to convene at 10:30 a.m. ET"], lines.map { |l| l["label"] }
  end

  def test_no_line_for_a_pro_forma_session_no_time_or_no_status
    assert_equal [], Yan.live_floor("senate" => status(next_at: "2026-11-17T10:00:00-05:00", pro_forma: true),
                                    "house" => status)
    assert_equal [], Yan.live_floor(nil)
    assert_equal [], Yan.live_floor("house" => status(convened: "not a time"))
  end

  # The convening wins: a pro forma next session doesn't hide a chamber in session.
  def test_a_convening_shows_even_with_a_pro_forma_next_session
    lines = Yan.live_floor("senate" => status(convened: "2026-11-17T10:00:00-05:00",
                                              next_at: "2026-11-20T11:00:00-05:00", pro_forma: true))
    assert_equal ["Convened at 10 a.m. ET"], lines.map { |l| l["label"] }
    assert_equal [true], lines.map { |l| l["in_session"] }
    assert_equal ["2026-11-17T10:00:00-05:00"], lines.map { |l| l["from"] }
  end

  def build(floor_status)
    schedule = { "items" => [], "floor_status" => floor_status }
    build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]], files: "index.html",
               schedule: schedule).fetch("/index.html")
  end

  # Lines start without .is-live: live-floor.js shows them from their time.
  def test_the_home_page_band_has_a_tab_filtered_line_per_chamber
    html = build("senate" => status(next_at: "2026-11-16T15:00:00-05:00", pro_forma: false),
                 "house" => status(convened: "2026-11-17T12:00:04-05:00"))
    band = html[%r{<section class="live-band".*?</section>}m]
    assert_includes band, '<p class="live-line small" data-row data-chamber="senate" data-live-from="2026-11-16T15:00:00-05:00">'
    assert_includes band, '<p class="live-line small" data-row data-chamber="house" data-live-from="2026-11-17T12:00:04-05:00">'
    assert_includes band, "Scheduled to convene at 3 p.m. ET"
    senate, house = band.split('data-chamber="house"')
    assert_includes senate, '<span class="live-flag kicker"><span class="live-dot" aria-hidden="true"></span>Scheduled session</span>'
    refute_includes senate, "In session"
    assert_includes house, '<span class="live-flag kicker"><span class="live-dot pulse" aria-hidden="true"></span>In session</span>'
    refute_includes house, "Scheduled session"
    assert_includes band, '<a class="link" href="https://clerk.house.gov/FloorSummary">Floor summary</a>'
    refute_includes band, "is-live"
    assert_includes html, '<script src="/assets/js/live-floor.js" defer></script>'
  end

  # A House line from a scheduled time only reads "Scheduled session", like the Senate's.
  def test_a_house_line_from_a_scheduled_time_reads_scheduled_session
    html = build("house" => status(next_at: "2026-11-18T10:00:00-05:00", pro_forma: false))
    band = html[%r{<section class="live-band".*?</section>}m]
    assert_includes band, 'data-chamber="house" data-live-from="2026-11-18T10:00:00-05:00"'
    assert_includes band, "Scheduled to convene at 10 a.m. ET"
    assert_includes band, '<span class="live-flag kicker"><span class="live-dot" aria-hidden="true"></span>Scheduled session</span>'
    refute_includes band, "In session"
    refute_includes band, 'data-chamber="senate"'
  end

  def test_no_band_or_script_without_a_line
    html = build("senate" => status, "house" => status)
    refute_includes html, "live-band"
    refute_includes html, "live-floor.js"
  end
end

class HomeModulesTest < Minitest::Test
  include SiteBuild
  include HouseItem

  def vote(id, chamber, date, yea, nay, needed, share: "1/2", posts: true, against: 0)
    { "vote_id" => id, "chamber" => chamber, "vote_date" => date, "yea_count" => yea, "nay_count" => nay,
      "yeas_needed" => needed, "required_share" => share, "bot_posts" => posts,
      "against_party_majority_count" => against }
  end

  def test_closest_votes_sort_by_how_far_the_yeas_fell_from_the_yeas_needed
    rows = Yan.closest_votes([
      vote("h3", "house", "2026-11-12", 215, 209, 213),               # 2 over
      vote("s2", "senate", "2026-11-12", 58, 40, 60, share: "3/5"),   # 2 short
      vote("h2", "house", "2026-11-11", 300, 140, 294, share: "2/3"), # 6 over
      vote("h1", "house", "2026-11-10", 211, 210, 211),               # exactly enough
      vote("s1", "senate", "2026-10-13", 50, 49, 50),                 # outside the 30 days
      vote("q1", "house", "2026-11-12", 0, 0, nil)                    # a quorum call
    ], { "h1" => { "words" => { "yes" => "Aye", "no" => "No" } } }, 2)
    assert_equal "2026-10-14", rows["since"]
    assert_equal "2026-11-12", rows["through"]
    assert_equal "Oct. 14 through Nov. 12, 2026", rows["range"]
    # Two per chamber, nearest first; ties go to the newest.
    assert_equal %w[h1 h3 s2], rows["rows"].map { |r| r["vote"]["vote_id"] }
    # Each vote's own words; Yea and Nay when its page has none.
    assert_equal %w[Aye Yea], rows["rows"].first(2).map { |r| r["words"]["yes"] }
    s2 = rows["rows"].last
    assert_equal "three-fifths of senators", s2["share"]
    assert_equal 59.2, s2["yea_pct"]
    assert_equal 61.2, s2["tick_pct"]
    refute s2.key?("gap")
  end

  def test_a_tie_the_vice_president_broke_sorts_first_and_the_range_keeps_both_years
    rows = Yan.closest_votes([
      vote("s2", "senate", "2026-01-05", 60, 39, 50),
      vote("s1", "senate", "2026-01-02", 50, 50, 51).merge("tie_breaker_by" => "Vice President"),
      vote("s0", "senate", "2025-12-10", 52, 47, 50)
    ])
    assert_equal %w[s1 s0 s2], rows["rows"].map { |r| r["vote"]["vote_id"] }
    assert_equal "Dec. 7, 2025 through Jan. 5, 2026", rows["range"]
  end

  def test_tick_stays_on_the_bar_when_more_yeas_are_needed_than_were_cast
    row = Yan.closest_votes([vote("s1", "senate", "2026-11-12", 40, 10, 60, share: "3/5")])["rows"].first
    assert_equal 100, row["tick_pct"]
  end

  def test_against_lists_posted_votes_with_names_up_to_five
    views = { "h2" => { "against" => [{ "name" => "A" }] }, "h1" => { "against" => Array.new(6) { { "name" => "B" } } } }
    rows = Yan.against_votes([
      vote("h3", "house", "2026-11-12", 1, 0, 1, posts: false, against: 4), # a rule: not posted
      vote("h2", "house", "2026-11-11", 1, 0, 1, against: 1),
      vote("h1", "house", "2026-11-10", 1, 0, 1, against: 6),
      vote("h0", "house", "2026-11-09", 1, 0, 1, against: 0)
    ], views)
    assert_equal %w[h2 h1], rows.map { |r| r["vote"]["vote_id"] }
    assert_equal [{ "name" => "A" }], rows[0]["names"]
    assert_empty rows[1]["names"]
    assert_equal 6, rows[1]["count"]
  end

  def test_modules_are_nil_until_the_export_carries_their_fields
    old = { "vote_id" => "h1", "chamber" => "house", "vote_date" => "2026-11-12" }
    assert_nil Yan.closest_votes([old])
    assert_nil Yan.against_votes([old], {})
    assert_nil Yan.home_week(nil)
    assert_nil Yan.home_week({ "chambers" => [], "last_week" => "2026-11-09" })
    assert_nil Yan.home_areas(nil)
  end

  def test_week_shows_the_newest_week_and_bars_on_one_scale
    dates = { "house" => %w[2026-11-10 2026-11-11], "senate" => %w[2026-11-12 2026-10-27 2026-10-28 2026-10-29] }
    vol = Yan.vote_volume(dates.flat_map { |c, ds| ds.map { |d| { "chamber" => c, "vote_date" => d } } })
    week = Yan.home_week(vol, 2)
    assert_equal "2026-11-09", week["start"]
    assert_equal "2026-11-02", week["first"]
    house, senate = week["chambers"]
    assert_equal [2, 1], [house["total"], senate["total"]]
    assert_equal [0.0, 100.0], house["bars"].map { |b| b["pct"] }
    assert_equal [0.0, 50.0], senate["bars"].map { |b| b["pct"] }
    assert_equal "Senate roll calls per week, week of Nov. 2, 2026 to week of Nov. 9, 2026: 0, 1", senate["label"]
  end

  def test_home_page_renders_the_closest_votes_lines_and_hides_rows_past_the_limit
    member = EscapingTest::MEMBER.merge("official_full_name" => "Jane Doe")
    doc = { "positions" => { "Z000001" => "Aye" }, "party_totals" => { "R" => { "yes" => 1 } },
            "caucus_majority_position" => { "R" => "yes" }, "against_party_majority" => [], "summary" => nil }
    base = { "congress" => 119, "session" => 2, "question" => "On Passage", "result" => "Passed",
             "measure_title" => "A bill", "bot_posts" => false, "against_party_majority_count" => 0 }
    votes = (1..4).map do |roll|
      v = vote("h119-2-#{format("%04d", roll)}", "house", "2026-11-1#{roll}", 1, roll - 1, 1)
      [base.merge(v).merge("roll_number" => roll), doc]
    end
    tie = vote("s119-2-0001", "senate", "2026-11-10", 50, 50, 51)
          .merge(base).merge("roll_number" => 1, "tie_breaker_by" => "Vice President of the United States")
    html = build_site([member], votes + [[tie, doc]]).fetch("/index.html")
    closest = html[%r{<section aria-labelledby="close-h".*?</section>}m]
    assert_includes closest, "Roll calls from Oct. 16 through Nov. 14, 2026"
    assert_includes closest, "1 Aye, 0 No · 1 needed, a majority of those voting"
    assert_includes closest, "50 Aye, 50 No · Tie broken by the Vice President of the United States"
    refute_includes closest, "51 needed"
    # No tick on a tie-break: the needed count leaves out the tie-breaking vote.
    assert_equal 3, closest.scan('class="tick"').size
    # Three per chamber, three shown before the tabs run: the fourth row starts hidden.
    assert_equal 4, closest.scan('<li class="close-item"').size
    assert_equal 1, closest.scan(/<li class="close-item"[^>]* hidden>/).size
  end

  # A chamber tab hides a module with no rows for that chamber, so each module
  # lists the chambers it has rows for; without JS, Coming up shows three per
  # chamber, as the tabs do.
  def test_modules_list_their_chambers_and_coming_up_starts_rows_past_three_hidden
    member = EscapingTest::MEMBER.merge("official_full_name" => "Jane Doe")
    doc = { "positions" => { "Z000001" => "Nay" }, "party_totals" => { "R" => { "no" => 1 } },
            "caucus_majority_position" => { "R" => "yes" },
            "against_party_majority" => [{ "bioguide_id" => "Z000001", "position" => "Nay" }], "summary" => nil }
    v = vote("h119-2-0001", "house", "2026-11-12", 0, 1, 1, against: 1)
        .merge("congress" => 119, "session" => 2, "roll_number" => 1, "question" => "On Passage", "result" => "Failed")
    # A Senate vote with no member against their party: in Closest votes only.
    s = vote("s119-2-0001", "senate", "2026-11-11", 50, 49, 50)
        .merge("congress" => 119, "session" => 2, "roll_number" => 1, "question" => "On Passage", "result" => "Passed")
    senate = (1..4).map do |i|
      { "chamber" => "senate", "item_id" => "s#{i}", "filed_date" => "2026-11-12", "question" => "On the Cloture Motion",
        "measure_label" => "PN#{i}", "title" => "Nomination #{i}", "vote_id" => nil }
    end
    house_item = house("h1", "H.R. 1", "A House bill")
    built = ->(items) do
      build_site([member], [[v, doc], [s, doc.merge("against_party_majority" => [])]], time: "2026-11-13 12:00:00 -0500",
                 schedule: { "items" => items, "senate_next_convene_et" => "2026-11-16T15:00:00" }).fetch("/index.html")
    end
    chambers = ->(page, id) { page[/<section aria-labelledby="#{id}" data-row data-chamber="([^"]*)">/, 1] }
    html = built.call(senate + [house_item])
    # The tabs split the value on spaces: exactly one between chambers.
    assert_equal "senate house", chambers.call(html, "soon-h")
    assert_equal "senate", chambers.call(built.call(senate), "soon-h")
    assert_equal "house", chambers.call(built.call([house_item]), "soon-h")
    assert_equal %w[house senate], chambers.call(html, "close-h").split(" ").sort
    assert_equal "house", chambers.call(html, "against-h")
    soon = html[%r{<section aria-labelledby="soon-h".*?</section>}m]
    assert_equal 5, soon.scan('<li class="vote-item"').size
    assert_equal ["Nomination 4"], soon.scan(%r{<li class="vote-item"[^>]* hidden>.*?<span class="t">(.*?)</span>}m).flatten
    # The lead takes two-thirds only beside the week's column.
    assert_includes html, '<div class="front has-side">'
    assert_includes html, '<aside class="side"'
  end

  # A build with votes always has a week, so the plugin's is replaced with none.
  def test_lead_has_no_side_column_without_a_week
    real = Yan.method(:home_week)
    Yan.define_singleton_method(:home_week) { |*| nil }
    html = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]]).fetch("/index.html")
    assert_includes html, '<div class="front">'
    assert_includes html, '<article class="lead">'
    refute_includes html, "has-side"
    refute_includes html, '<aside class="side"'
  ensure
    Yan.define_singleton_method(:home_week, real)
  end

  # The member's seat code comes from member data: escaped in the
  # against-majority list.
  def test_against_names_escape_the_seat_code
    member = EscapingTest::MEMBER.merge("official_full_name" => "Jane Doe", "state" => %q("<x>&'))
    html = build_site([member], [[EscapingTest::VOTE, EscapingTest::DOC]]).fetch("/index.html")
    against = html[%r{<section aria-labelledby="against-h".*?</section>}m]
    assert_includes against, "(R-&quot;&lt;x&gt;&amp;&#39;-4)"
    refute_includes against, "<x>"
  end

  def test_areas_take_the_top_areas_and_leave_out_rows_with_no_area
    pv = { "area_count" => 2, "table" => [
      { "area" => "Energy", "total" => 4 }, { "area" => "Taxation", "total" => 1 },
      { "area" => "Nominations", "total" => 9 }
    ] }
    assert_equal [["Energy", 100.0], ["Taxation", 25.0]], Yan.home_areas(pv, 6).map { |r| [r["area"], r["pct"]] }
  end
end

# House ads (the maker's other projects) go on explainer pages only, never on
# vote, member, bill or other data pages; /about has a credit card instead.
class HouseAdTest < Minitest::Test
  include SiteBuild

  EXPLAINERS = ["/how/bills/index.html", "/how/dictionary/index.html", "/how/expulsion/index.html",
                "/how/house-and-senate/index.html", "/how/missed-votes/index.html",
                "/how/opening-prayers/index.html", "/how/voting/index.html"].freeze

  def pages
    @@pages ||= build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])
  end

  def links(html)
    html.scan(/<a [^>]*>/)
  end

  def test_explainer_pages_end_main_with_one_slot_of_both_units_the_first_shown
    EXPLAINERS.each do |path|
      html = pages.fetch(path)
      assert_equal 1, html.scan('<aside class="house-ad-slot"').size, path
      assert_includes html, '<link rel="stylesheet" href="/assets/css/house-ads.css">', path
      slot = html[%r{<aside class="house-ad-slot".*?</aside>}m]
      assert html.index(slot) < html.index("</main>"), "#{path}: the slot sits inside <main>"
      assert_match(%r{</aside>\s*</main>}, html, "#{path}: the slot ends <main>")
      assert_includes slot, "data-pagefind-ignore"
      assert_includes slot, "From the maker of Yeas &amp; Nays"
      assert_equal ['<div data-house-ad="keepscore">', '<div data-house-ad="hiringradar" hidden>'],
                   slot.scan(/<div data-house-ad="[^"]*"[^>]*>/)
      assert_includes slot, "Math.random()"
      refute_includes slot, "<script src", "no third-party or external script"
      slot.scan(/<img [^>]*>/).each { |img| assert_includes img, 'loading="lazy"', img }
    end
  end

  def test_each_unit_is_one_tracked_link
    slot = pages.fetch("/how/bills/index.html")[%r{<aside class="house-ad-slot".*?</aside>}m]
    units = slot.split(/<div data-house-ad=/).drop(1)
    assert_equal 2, units.size
    { "keepscore" => "https://keepscorebaseball.com/scorebooks?", "hiringradar" => "https://hiringradarjobs.com/?" }
      .zip(units).each do |(unit, href), html|
        a = links(html)
        assert_equal 1, a.size, unit
        assert_includes a.first, %(href="#{href}utm_source=yeasandnays&amp;utm_medium=house-ad&amp;utm_content=how-bills")
        assert_includes a.first, 'data-umami-event="house-ad-click"'
        assert_includes a.first, %(data-umami-event-unit="#{unit}")
        assert_includes a.first, 'target="_blank" rel="noopener"'
        assert_match(/aria-label="[^"]+"/, a.first)
      end
  end

  def test_no_other_page_has_a_house_ad
    assert_includes pages.keys, "/votes/119/house/1/1/index.html"
    assert pages.keys.any? { |p| p.start_with?("/members/") && p != "/members/index.html" }, "a member page"
    (pages.keys - EXPLAINERS).each do |path|
      refute_includes pages[path], "house-ad-slot", path
      refute_includes pages[path], "house-ads.css", path
    end
  end

  # Only the default layout includes the slot, and only explainer pages opt in.
  def test_only_explainer_sources_opt_in
    sources = Dir[File.join(SOURCE, "{_layouts,_includes,**}", "*.html")].reject { |f| f.match?(%r{/(_site|vendor|node_modules)/}) }
    including = sources.select { |f| File.read(f).include?("house-ad.html") }.map { |f| f.delete_prefix(SOURCE) }
    assert_equal ["/_layouts/default.html"], including.uniq
    opted_in = sources.select { |f| File.read(f) =~ /\A---\n(?:.*\n)*?house_ad: true\n/ }.map { |f| f.delete_prefix(SOURCE) }
    assert_equal EXPLAINERS.sort, opted_in.uniq.sort
  end

  def test_about_has_three_credit_rows_and_no_rotating_ad
    about = pages.fetch("/about/index.html")
    refute_includes about, "house-ad-slot"
    refute_includes about, "data-house-ad"
    card = about[%r{<div class="credit">.*?</ul>\s*</div>}m]
    rows = links(card)
    assert_equal 3, rows.size
    %w[rachelsprague.com keepscorebaseball.com hiringradarjobs.com].zip(rows).each do |host, a|
      assert_includes a, %(href="https://#{host}/?utm_source=yeasandnays&amp;utm_medium=house-ad&amp;utm_content=about")
      assert_includes a, 'data-umami-event="house-ad-click"'
    end
    assert_equal ["rachelsprague.com", "KeepScore", "HiringRadar"], card.scan(%r{<span class="credit-name">([^<]*)</span>}).flatten
  end
end

class MemberChartsTest < Minitest::Test
  include SiteBuild

  def bill(area, n = 1) = { "bill_id" => "119-hr-#{n}", "measure_label" => "H.R. #{n}", "title" => "Bill #{n}", "policy_area" => area }

  def test_areas_sort_most_first_with_unassigned_last
    bills = [bill("Health"), bill("Taxation"), bill(nil), bill("Health"), bill(""), bill("Agriculture and Food")]
    areas = Yan.member_areas(bills)
    assert_equal ["Health", "Agriculture and Food", "Taxation", "Not yet assigned"], areas["shown"].map { |a| a["area"] }
    assert_equal [2, 1, 1, 2], areas["shown"].map { |a| a["count"] }
    assert_equal [100.0, 50.0, 50.0, 100.0], areas["shown"].map { |a| a["pct"] }
    assert_empty areas["more"]
    # Each bill carries its row's filter value.
    assert_equal %w[health taxation not-yet-assigned health not-yet-assigned agriculture-and-food], bills.map { |b| b["area_slug"] }
    assert_nil Yan.member_areas([])
    assert_nil Yan.member_areas(nil)
  end

  def test_areas_fold_only_when_more_than_two_are_left
    ten = (1..10).map { |i| bill("Area #{format("%02d", i)}") }
    assert_equal [10, 0], Yan.member_areas(ten, 8).values_at("shown", "more").map(&:size)
    eleven = ten + [bill("Area 11")]
    assert_equal [8, 3], Yan.member_areas(eleven, 8).values_at("shown", "more").map(&:size)
  end

  def test_area_slug
    assert_equal "armed-forces-and-national-security", Yan.area_slug("Armed Forces and National Security")
    assert_equal "a-b-c", Yan.area_slug(%(A & "B" <c>))
  end

  def test_months_span_the_chamber_and_count_cast_and_missed
    votes = [
      { "chamber" => "house", "congress" => 119, "vote_date" => "2025-07-30" },
      { "chamber" => "house", "congress" => 119, "vote_date" => "2025-10-01" },
      { "chamber" => "senate", "congress" => 119, "vote_date" => "2025-09-02" }
    ]
    months = Yan.chamber_months(votes)
    assert_equal %w[2025-07 2025-08 2025-09 2025-10], months[["house", 119]]
    assert_equal %w[2025-09], months[["senate", 119]]

    list = [{ "vote" => votes[0], "position" => "Yea" }, { "vote" => votes[0], "position" => "Not Voting" },
            { "vote" => votes[0], "position" => "Present" }, { "vote" => votes[1], "position" => "Nay" }]
    mo = Yan.member_months(list, months[["house", 119]])
    assert_equal [[2, 1], [0, 0], [0, 0], [1, 0]], mo["months"].map { |r| [r["cast"], r["missed"]] }
    assert_equal [66.7, 33.3], mo["months"].first.values_at("cast_pct", "missed_pct")
    assert_equal ["July 2025", "Oct. 2025"], mo.values_at("first", "last")
    # The first month names its year; the rest show an initial.
    assert_equal [2025, nil, nil, nil], mo["months"].map { |r| r["year"] }
    assert_equal %w[J A S O], mo["months"].map { |r| r["initial"] }
    assert_nil Yan.member_months([], months[["house", 119]])
    assert_nil Yan.member_months(list, nil)
  end

  def test_months_cross_a_new_year_and_label_january
    votes = [{ "chamber" => "senate", "congress" => 119, "vote_date" => "2025-12-18" },
             { "chamber" => "senate", "congress" => 119, "vote_date" => "2026-02-02" }]
    months = Yan.chamber_months(votes)[["senate", 119]]
    assert_equal %w[2025-12 2026-01 2026-02], months
    mo = Yan.member_months(votes.map { |v| { "vote" => v, "position" => "Yea" } }, months)
    assert_equal [2025, 2026, nil], mo["months"].map { |r| r["year"] }
    assert_equal ["Dec. 2025", "Feb. 2026"], mo.values_at("first", "last")
  end

  def test_medians_count_only_members_with_roll_calls_in_that_congress
    members = [
      { "chamber" => "house", "last_congress" => 119, "roll_calls" => 10, "missed_votes_pct" => 1.0, "with_party_majority_pct" => 90.0 },
      { "chamber" => "house", "last_congress" => 119, "roll_calls" => 10, "missed_votes_pct" => 2.0, "with_party_majority_pct" => nil },
      { "chamber" => "house", "last_congress" => 119, "roll_calls" => 10, "missed_votes_pct" => 5.5, "with_party_majority_pct" => 95.0 },
      { "chamber" => "house", "last_congress" => 119, "roll_calls" => 0, "missed_votes_pct" => 0.0 },
      { "chamber" => "house", "last_congress" => 118, "roll_calls" => 10, "missed_votes_pct" => 50.0 }
    ]
    m = Yan.chamber_medians(members, 119)
    assert_equal({ "name" => "House", "members" => 3, "missed_votes_pct" => 2.0, "with_party_majority_pct" => 92.5 }, m["house"])
    assert_nil m["senate"]["missed_votes_pct"]
  end

  def test_medians_leave_out_members_under_a_tenth_of_the_chambers_most_roll_calls
    house = [[95, 1.0], [10, 3.0], [9, 80.0]].map do |n, pct|
      { "chamber" => "house", "last_congress" => 119, "roll_calls" => n, "missed_votes_pct" => pct, "with_party_majority_pct" => 100.0 - pct }
    end
    # The minimum is per chamber, and the most is from this Congress only.
    senate = [{ "chamber" => "senate", "last_congress" => 119, "roll_calls" => 1, "missed_votes_pct" => 4.0 },
              { "chamber" => "senate", "last_congress" => 118, "roll_calls" => 900, "missed_votes_pct" => 50.0 }]
    m = Yan.chamber_medians(house + senate, 119)
    assert_equal({ "name" => "House", "members" => 2, "missed_votes_pct" => 2.0, "with_party_majority_pct" => 98.0 }, m["house"])
    assert_equal 1, m["senate"]["members"]
    # Exactly a tenth counts.
    house.first["roll_calls"] = 100
    assert_equal 2, Yan.chamber_medians(house, 119)["house"]["members"]
  end

  # A returning member on 120th roll calls before congress-legislators lists their new term.
  def test_medians_count_a_member_with_roll_calls_but_no_term_dates
    members = [
      { "chamber" => "house", "last_congress" => 120, "served_in_congress" => true, "roll_calls" => 4, "missed_votes_pct" => 0.0 },
      { "chamber" => "house", "last_congress" => 120, "served_in_congress" => false, "served_from" => nil,
        "roll_calls" => 4, "missed_votes_pct" => 50.0 }
    ]
    m = Yan.chamber_medians(members, 120)
    assert_equal 2, m["house"]["members"]
    assert_equal 25.0, m["house"]["missed_votes_pct"]
  end

  def test_member_page_shows_medians_months_and_area_filters
    member = EscapingTest::MEMBER.merge("roll_calls" => 1, "votes_cast" => 1, "missed_votes" => 0, "missed_votes_pct" => 0.0,
                                        "party_majority_votes" => 1, "with_party_majority_pct" => 0.0)
    bills = [bill(%(Arts & "Culture" <x>), 1), bill(nil, 2)]
    html = build_site([member], [[EscapingTest::VOTE, EscapingTest::DOC]],
                      member_files: { "Z000001" => { "sponsored" => bills, "cosponsored" => [] } })
               .fetch("/members/Z000001/index.html")
    assert_includes html, %(<span class="med">House median: 0.0%</span>)
    assert_includes html, %(<span class="m-month" title="Jan. 2025: 1 cast, 0 missed">)
    # Plain text until filters.js makes it a button, so it's no dead control without JS.
    assert_includes html, %(<span class="m-area" data-button data-tab="area" data-value="arts-culture-x">)
    refute_includes html, %(<button type="button" data-tab="area" data-value="arts)
    assert_includes html, "<span>Arts &amp; &quot;Culture&quot; &lt;x&gt;</span>"
    assert_includes html, %(<li class="vrow" data-row data-area="arts-culture-x">)
    assert_includes html, %(<li class="vrow" data-row data-area="not-yet-assigned">)
    assert_includes html, %(data-count data-noun="in the 119th Congress")
    # No cosponsored bills: no chart for them.
    assert_equal 1, html.scan('<div class="m-areas">').size
  end
end

# The service line and Congressional Directory biography on member pages.
class MemberBioTest < Minitest::Test
  include SiteBuild

  BIO = {
    "edition" => "CDIR-2026-02-20", "date_issued" => "2026-02-20",
    "opening" => %q(of "Oak" <town>, CA; born in O'Fallon & Co, MO, May 1, 1970),
    "education" => "B.A., Example College, 1992", "professional_history" => "teacher, 1992-2000",
    "military_service" => nil
  }.freeze

  def service(fields) = Yan.service_line({ "chamber" => "house", "is_current" => true,
                                           "chamber_first_term_start" => "2021-01-03" }.merge(fields))

  def test_service_line_counts_terms_in_words_through_ninth
    assert_equal "Serving a third term in the House; first term began in 2021.", service("chamber_terms" => 3)
    assert_equal "Serving an eighth term in the House; first term began in 2021.", service("chamber_terms" => 8)
    assert_equal "Serving a 10th term in the House; first term began in 2021.", service("chamber_terms" => 10)
    assert_equal "Serving an 11th term in the House; first term began in 2021.", service("chamber_terms" => 11)
    assert_equal "Serving an 18th term in the House; first term began in 2021.", service("chamber_terms" => 18)
    assert_equal "Serving a 21st term in the House; first term began in 2021.", service("chamber_terms" => 21)
  end

  def test_service_line_for_former_members_and_the_other_chamber
    assert_equal "Served 1 term in the House; first term began in 2021.",
                 service("chamber_terms" => 1, "is_current" => false)
    assert_equal "Serving a second term in the Senate; first term began in 2021. Also served in the House, 2013–2019.",
                 service("chamber" => "senate", "chamber_terms" => 2, "other_chamber_from_year" => 2013, "other_chamber_to_year" => 2019)
    assert_includes service("chamber_terms" => 2, "other_chamber_from_year" => 2019, "other_chamber_to_year" => 2019),
                    "Also served in the Senate, 2019."
    assert_nil service("chamber_terms" => nil)
  end

  def test_bio_keeps_fields_it_has_and_links_the_edition
    bio = Yan.member_bio(BIO)
    assert_equal %q(Of "Oak" <town>, CA; born in O'Fallon & Co, MO, May 1, 1970.), bio["opening"]
    assert_equal %w[Education Career], bio["rows"].map { |r| r["label"] }
    assert_equal "https://www.govinfo.gov/app/details/CDIR-2026-02-20", bio["source_url"]
    assert_nil Yan.member_bio(nil)
  end

  def test_member_page_shows_service_line_and_escaped_bio
    member = EscapingTest::MEMBER.merge("chamber_terms" => 3, "chamber_first_term_start" => "2021-01-03")
    pages = build_site([member], [[EscapingTest::VOTE, EscapingTest::DOC]],
                       member_files: { "Z000001" => { "sponsored" => nil, "cosponsored" => nil, "bio" => BIO } })
    html = pages.fetch("/members/Z000001/index.html")
    assert_includes html, "Serving a third term in the House; first term began in 2021."
    assert_includes html, %(<h2 id="bio-h" class="kicker soft">Before Congress</h2>)
    assert_includes html, "<p>Of &quot;Oak&quot; &lt;town&gt;, CA; born in O&#39;Fallon &amp; Co, MO, May 1, 1970.</p>"
    assert_includes html, "<div><dt>Career</dt><dd>teacher, 1992-2000</dd></div>"
    refute_includes html, "<dt>Military service</dt>"
    assert_includes html, %(<a class="link" href="https://www.govinfo.gov/app/details/CDIR-2026-02-20">Congressional Directory</a>, Feb. 20, 2026 edition.)
  end

  def test_member_page_without_a_bio_has_no_section
    pages = build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]],
                       member_files: { "Z000001" => { "sponsored" => nil, "cosponsored" => nil, "bio" => nil } })
    refute_includes pages.fetch("/members/Z000001/index.html"), "Before Congress"
  end
end

# The missed votes page states each chamber's median and how many members
# missed more than 10%, from the current Congress's members with roll calls.
class MissedVotesPageTest < Minitest::Test
  include SiteBuild

  def member(id, chamber, pct, extra = {})
    EscapingTest::MEMBER.merge("bioguide_id" => id, "chamber" => chamber, "roll_calls" => 100,
                               "missed_votes_pct" => pct).merge(extra)
  end

  def page(members)
    build_site(members, [[EscapingTest::VOTE, EscapingTest::DOC]]).fetch("/how/missed-votes/index.html")
  end

  def test_each_chamber_gives_its_median_and_members_over_ten_percent
    html = page([member("A000001", "house", 2.0), member("A000002", "house", 12.5), member("A000003", "house", 30.0),
                 member("S000001", "senate", 4.0),
                 # None counts: no roll calls yet, under a tenth of the most, or last in an earlier Congress.
                 member("A000006", "house", 50.0, "roll_calls" => 9),
                 member("A000004", "house", 50.0, "roll_calls" => 0),
                 member("A000005", "house", 50.0, "last_congress" => 118)])
    assert_includes html, "The median member missed 12.5% of roll calls, among 3 members. 2 members missed more than 10%."
    assert_includes html, "The median member missed 4.0% of roll calls, among 1 member. 0 members missed more than 10%."
    assert html.index("<dt>House</dt>") < html.index("<dt>Senate</dt>")
  end

  def test_even_count_median_is_the_mean_of_the_middle_two_and_ten_percent_is_not_over
    html = page([member("A000001", "house", 2.0), member("A000002", "house", 10.0)])
    assert_includes html, "The median member missed 6.0% of roll calls, among 2 members. 0 members missed more than 10%."
  end

  def test_one_member_over_ten_percent_is_singular
    assert_includes page([member("A000001", "house", 11.0)]), "1 member missed more than 10%."
  end

  def test_no_current_members_leaves_out_the_figures
    html = page([member("A000001", "house", 2.0, "last_congress" => 118)])
    refute_includes html, 'id="typical"'
    assert_includes html, 'id="rules"'
  end

  def test_member_tile_and_about_link_here
    pages = build_site([member("Z000001", "house", 2.0)], [[EscapingTest::VOTE, EscapingTest::DOC]])
    assert_includes pages.fetch("/members/Z000001/index.html"), %(<a class="link" href="/how/missed-votes/">Missed votes</a>)
    assert_includes without_footer(pages.fetch("/about/index.html")), %(<a href="/how/missed-votes/">How missed votes work</a>)
  end
end

# How the House and Senate vote: linked from About and How a bill becomes law,
# and each dictionary link lands on an entry.
class VotingPageTest < Minitest::Test
  include SiteBuild

  def pages
    @@pages ||= build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])
  end

  def test_page_builds_and_about_and_bills_link_it
    assert_includes pages.fetch("/how/voting/index.html"), %(<h1 class="vote-h">How the House and Senate vote</h1>)
    link = %(<a href="/how/voting/">How the House and Senate vote</a>)
    assert_includes without_footer(pages.fetch("/about/index.html")), link
    assert_includes without_footer(pages.fetch("/how/bills/index.html")), link
  end

  def test_dictionary_links_name_existing_entries
    ids = pages.fetch("/how/dictionary/index.html").scan(/<dt id="([^"]*)">/).flatten
    anchors = pages.fetch("/how/voting/index.html").scan(%r{href="/how/dictionary/#([^"]*)"}).flatten
    refute_empty anchors
    anchors.each { |id| assert_includes ids, id }
  end

  def test_definitions_link_lands_on_about
    assert_includes without_footer(pages.fetch("/how/voting/index.html")), %(href="/about/#definitions")
    assert_includes pages.fetch("/about/index.html"), %(<section id="definitions">)
  end
end

# How the House and Senate differ: linked from About and two other explainers,
# and each dictionary link lands on an entry.
class HouseAndSenatePageTest < Minitest::Test
  include SiteBuild

  def pages
    @@pages ||= build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])
  end

  def test_page_builds_and_about_bills_and_voting_link_it
    assert_includes pages.fetch("/how/house-and-senate/index.html"), %(<h1 class="vote-h">How the House and Senate differ</h1>)
    link = %(<a href="/how/house-and-senate/">How the House and Senate differ</a>)
    %w[/about/ /how/bills/ /how/voting/].each { |url| assert_includes without_footer(pages.fetch("#{url}index.html")), link }
  end

  def test_dictionary_links_name_existing_entries
    ids = pages.fetch("/how/dictionary/index.html").scan(/<dt id="([^"]*)">/).flatten
    anchors = pages.fetch("/how/house-and-senate/index.html").scan(%r{href="/how/dictionary/#([^"]*)"}).flatten
    refute_empty anchors
    anchors.each { |id| assert_includes ids, id }
  end
end

# Opening prayers and the chaplains: linked from About and How the House and
# Senate differ, and links back to the latter.
class OpeningPrayersPageTest < Minitest::Test
  include SiteBuild

  def pages
    @@pages ||= build_site([EscapingTest::MEMBER], [[EscapingTest::VOTE, EscapingTest::DOC]])
  end

  def test_page_builds_and_about_and_house_and_senate_link_it
    page = without_footer(pages.fetch("/how/opening-prayers/index.html"))
    assert_includes page, %(<h1 class="vote-h">Opening prayers and the chaplains</h1>)
    assert_includes page, %(<a href="/how/house-and-senate/">How the House and Senate differ</a>)
    link = %(<a href="/how/opening-prayers/">Opening prayers and the chaplains</a>)
    %w[/about/ /how/house-and-senate/].each { |url| assert_includes without_footer(pages.fetch("#{url}index.html")), link }
  end
end
