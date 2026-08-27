import argparse
import logging
import os
import sys

import uvicorn
from auditview.app import create_app
from auditview import cli


def serve(argv):
    p = argparse.ArgumentParser(prog="auditview", description="auditview — line-level code review tool")
    p.add_argument("path", nargs="?", default=".",
                   help="Root folder to audit (default: current directory)")
    p.add_argument("--db", metavar="FILE",
                   help="SQLite database file path (default: <root>/.auditview.db)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    p.add_argument("--debug", action="store_true", help="Enable debug logging (all requests)")
    args = p.parse_args(argv)

    logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=logging.WARNING)
    if args.debug:
        logging.getLogger("auditview").setLevel(logging.DEBUG)

    root = os.path.abspath(args.path)
    db_path = os.path.abspath(args.db) if args.db else os.path.join(root, ".auditview.db")

    app = create_app(db_path, root)
    print(f"auditview  root={root}")
    print(f"           db={db_path}")
    print(f"           http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "serve":
        serve(argv[1:])
        return
    # A bare query subcommand anywhere in argv routes to the read-only CLI.
    # `auditview serve <path>` is the escape hatch when a directory shares a
    # subcommand's name.
    if any(a in cli.SUBCOMMANDS for a in argv):
        sys.exit(cli.run(argv))
    serve(argv)


if __name__ == "__main__":
    main()
