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

    bot = sub.add_parser("bot", help="Bluesky bot (dry run unless `bot run --publish`)")
    bot_sub = bot.add_subparsers(dest="bot_command", required=True)
    preview = bot_sub.add_parser("preview", help="print the most recent postable votes, ignoring state")
    preview.add_argument("-n", type=int, default=10, help="number of recent postable votes (default 10)")
    preview.add_argument("--vote", action="append", default=[], help="also show this vote ID (repeatable)")
    bot_run = bot_sub.add_parser("run", help="post votes not yet handled, per data/bot/state.json (dry run by default)")
    bot_run.add_argument("--publish", action="store_true",
                         help="publish to Bluesky and advance state (needs BLUESKY_HANDLE / BLUESKY_APP_PASSWORD)")
    bot_sub.add_parser("init", help="mark every vote up to the latest as handled")

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
    elif args.command == "bot":
        from yan.bot import run as bot

        if args.bot_command == "preview":
            bot.preview(args.n, args.vote)
        elif args.bot_command == "run":
            bot.run(publish=args.publish)
        elif args.bot_command == "init":
            print(f"bot state set to: {bot.init()}")


if __name__ == "__main__":
    main()
