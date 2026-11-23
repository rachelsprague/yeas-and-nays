# Local pipeline: download -> parse -> dbt -> JSON. Run `make all`.
DBT = cd transform && DBT_PROFILES_DIR=. uv run dbt

.PHONY: all ingest stage model export cards bot-preview site site-search site-serve test pytest sitetest jstest datatest clean

all: ingest stage model export

ingest:          ## download raw XML/JSON into data/raw/
	uv run yan ingest

stage:           ## parse data/raw/ into Parquet under data/staged/
	uv run yan stage

model:           ## build and test dbt models (unit tests, models, data tests)
	$(DBT) build

export:          ## write JSON for the bot and site into data/out/
	uv run yan export

cards:           ## draw vote pages' link card images into site/assets/cards/
	uv run yan cards

bot-preview:     ## print the 10 most recent postable votes (dry run, never publishes)
	uv run yan bot preview -n 10

site: cards      ## build the Jekyll site from data/out/ into site/_site/
	cd site && bundle install --quiet && bundle exec jekyll build

site-search: cards  ## build the site and its Pagefind search index, then serve both (Pagefind prints the address)
	cd site && bundle install --quiet && npm ci --ignore-scripts --no-audit --no-fund && bundle exec jekyll build && npx --no-install pagefind --site _site --serve

site-serve: cards  ## build and serve the site at http://localhost:4000
	cd site && bundle install --quiet && bundle exec jekyll serve

test: pytest sitetest jstest  ## Python, site plugin and site JS tests (dbt tests run as part of `make model`)

pytest:
	uv run pytest -q

sitetest:        ## tests for the site's Jekyll plugin
	cd site && bundle install --quiet && bundle exec ruby test/yan_data_test.rb

jstest:          ## tests for the site's JS (Node and jsdom, pinned in site/package-lock.json)
	cd site && npm ci --ignore-scripts --no-audit --no-fund && node --test "test/*.test.js"

datatest:        ## check the site's definitions and district map against data/out/
	cd site && bundle install --quiet && bundle exec ruby test/data_test.rb

clean:           ## remove local intermediate files (keeps raw downloads)
	rm -rf data/staged data/warehouse.duckdb transform/target transform/logs site/_site site/.jekyll-cache site/assets/cards
