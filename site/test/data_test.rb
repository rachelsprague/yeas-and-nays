# Checks of the site's own files against the exported data in data/out/. Run
# with `make datatest`. The hourly data job changes that data, so these run
# after it (.github/workflows/data-check.yml) rather than with yan_data_test.rb.

require "minitest/autorun"
require "jekyll"
require "yaml"
require "json"
require_relative "../_plugins/yan_data"

class DataTest < Minitest::Test
  OUT = File.expand_path("../../data/out", __dir__)

  # Every question in the exported votes has a definition, so a new kind of
  # vote gets one in procedures.yml rather than showing none.
  def test_every_exported_question_has_a_definition
    procedures = YAML.load_file(File.expand_path("../_data/procedures.yml", __dir__))
    votes = JSON.parse(File.read(File.join(OUT, "votes.json")))["votes"]
    assert_empty votes.reject { |v| Yan.procedure(v, procedures) }.map { |v| v["question"] }.uniq
  end

  # Every current representative in the exported data has a seat on the map
  # for the exported Congress, so district numbering matches after a switchover.
  def test_every_current_representative_is_on_the_current_map
    congress = JSON.parse(File.read(File.join(OUT, "meta.json")))["congress"]
    doc = JSON.parse(File.read(File.expand_path("../_maps/#{congress}.json", __dir__)))
    seats = doc["districts"].map { |d| [d["state"], d["district"]] }
    reps = JSON.parse(File.read(File.join(OUT, "members.json")))["members"]
               .select { |m| m["is_current"] && m["is_voting_member"] && m["chamber"] == "house" }
    assert_empty reps.map { |m| [m["state"], m["district"].to_i] } - seats
  end
end
