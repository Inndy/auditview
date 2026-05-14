import argparse
import logging
import os

from waitress import serve
from auditview.app import create_app


def main():
    p = argparse.ArgumentParser(description="auditview — line-level code review tool")
    p.add_argument("path", nargs="?", default=".",
                   help="Root folder to audit (default: current directory)")
    p.add_argument("--db", metavar="FILE",
                   help="SQLite database file path (default: <root>/.auditview.db)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    p.add_argument("--debug", action="store_true", help="Enable debug logging (all requests)")
    args = p.parse_args()

    level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=level)

    root = os.path.abspath(args.path)
    db_path = os.path.abspath(args.db) if args.db else os.path.join(root, ".auditview.db")

    app = create_app(db_path, root)
    print(f"auditview  root={root}")
    print(f"           db={db_path}")
    print(f"           http://{args.host}:{args.port}")
    serve(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
