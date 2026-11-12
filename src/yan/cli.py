"""Command-line entry point: `yan ingest | stage | export`."""

import argparse
import logging

from yan.http import Client


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yan", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="download raw source files into data/raw/")
    ingest.add_argument(
        "--source",
        choices=["legislators", "house", "senate"],
        action="append",
        help="limit to one source (repeatable); default is all",
    )
    sub.add_parser("stage", help="parse data/raw/ into Parquet under data/staged/")
    sub.add_parser("export", help="write JSON from the dbt marts into data/out/")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "ingest":
        from yan.ingest import house, legislators, senate

        modules = {"legislators": legislators, "house": house, "senate": senate}
        with Client() as client:
            for name in args.source or modules:
                modules[name].ingest(client)
    elif args.command == "stage":
        from yan.stage.run import run

        run()
    elif args.command == "export":
        from yan.export.json_export import run

        run()


if __name__ == "__main__":
    main()
