import argparse
import logging
import os
import sys

from auditview import cli, version_string


SERVE_HELP = "Start the web UI for a directory"


def _build_root_parser():
    p = argparse.ArgumentParser(
        prog="auditview",
        usage="%(prog)s [-h] COMMAND ...\n       %(prog)s [SERVER OPTIONS] [PATH]",
        description="auditview — line-level code review tool",
        epilog=(
            "A directory may be passed without 'serve' as a shortcut.\n"
            "Run 'auditview COMMAND -h' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    sub.add_parser("serve", help=SERVE_HELP, add_help=False)
    for name, help_text in cli.COMMAND_HELP.items():
        sub.add_parser(name, help=help_text, add_help=False)
    return p


def serve(argv, *, prog="auditview"):
    p = argparse.ArgumentParser(
        prog=prog,
        description="auditview — line-level code review tool",
    )
    p.add_argument("path", nargs="?", default=".",
                   help="Root folder to audit (default: current directory)")
    p.add_argument("--db", metavar="FILE",
                   help="SQLite database file path (default: <root>/.auditview.db)")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    p.add_argument("--debug", action="store_true", help="Enable debug logging (all requests)")
    p.add_argument("--lsp", action="store_true",
                   help="Enable symbol navigation by spawning language servers "
                        "found on PATH (off by default; see API.md)")
    # `main()` routes default server options here, so this parser is what a
    # bare `auditview --version` reaches.
    p.add_argument("--version", action="version",
                   version=f"auditview {version_string()}")
    args = p.parse_args(argv)

    # Keep query commands and top-level help lightweight; importing the app
    # initializes the MCP server and is only needed when serving.
    import uvicorn
    from auditview.app import create_app

    logging.basicConfig(format="%(levelname)s:%(name)s:%(message)s", level=logging.WARNING)
    if args.debug:
        logging.getLogger("auditview").setLevel(logging.DEBUG)

    root = os.path.abspath(args.path)
    db_path = os.path.abspath(args.db) if args.db else os.path.join(root, ".auditview.db")

    app = create_app(db_path, root, enable_lsp=args.lsp)
    print(f"auditview  {version_string()}")
    print(f"           root={root}")
    print(f"           db={db_path}")
    print(f"           http://{args.host}:{args.port}")
    if args.lsp:
        print("           lsp=on")
    uvicorn.run(app, host=args.host, port=args.port)


def main():
    argv = sys.argv[1:]

    if not argv:
        serve([])
        return
    if argv[0] in ("-h", "--help"):
        _build_root_parser().parse_args(argv)
        return
    if argv[0] == "serve":
        serve(argv[1:], prog="auditview serve")
        return
    if argv[0] in cli.SUBCOMMANDS:
        sys.exit(cli.run(argv))

    # Preserve query-wide flags before the subcommand, as supported by cli.py.
    # Otherwise an option-leading invocation belongs to the default server
    # command (`auditview --debug PATH`, for example).
    if argv[0].startswith("-"):
        if any(arg in cli.SUBCOMMANDS for arg in argv):
            sys.exit(cli.run(argv))
        serve(argv)
        return

    # A real directory remains a backwards-compatible shortcut for `serve`.
    # Anything else is much more likely to be a misspelled command than an
    # intentional server root, so show the command list instead of starting.
    if os.path.isdir(argv[0]):
        serve(argv)
        return

    parser = _build_root_parser()
    print(f"auditview: error: unknown command or directory: {argv[0]}", file=sys.stderr)
    parser.print_help(sys.stderr)
    parser.exit(2)


if __name__ == "__main__":
    main()
