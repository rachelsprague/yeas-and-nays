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
