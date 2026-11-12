# Local pipeline: download -> parse -> dbt -> JSON. Run `make all`.
DBT = cd transform && DBT_PROFILES_DIR=. uv run dbt

.PHONY: all ingest stage model export test pytest dbt-test clean

all: ingest stage model export

ingest:          ## download raw XML/JSON into data/raw/
	uv run yan ingest

stage:           ## parse data/raw/ into Parquet under data/staged/
	uv run yan stage

model:           ## build and test dbt models (unit tests, models, data tests)
	$(DBT) build

export:          ## write JSON for the bot and site into data/out/
	uv run yan export

test: pytest     ## parser tests (dbt tests run as part of `make model`)

pytest:
	uv run pytest -q

clean:           ## remove local intermediate files (keeps raw downloads)
	rm -rf data/staged data/warehouse.duckdb transform/target transform/logs
