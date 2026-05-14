import argparse
import os

from waitress import serve
from auditview.app import create_app


def main():
    p = argparse.ArgumentParser(description="auditview — line-level code review tool")
    p.add_argument("path", help="Root folder to audit")
    args = p.parse_args()
    root = os.path.abspath(args.path)
    db_path = os.path.join(root, ".auditview.db")
    app = create_app(db_path, root)
    print(f"auditview running at http://localhost:5000")
    serve(app, host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
