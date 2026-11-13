# Tests for _plugins/yan_data.rb. Run with `make sitetest`.

require "minitest/autorun"
require "jekyll"
require "yaml"
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
