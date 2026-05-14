import os
import time
import logging
from flask import Flask, send_from_directory, abort, g, request

from auditview.db.connection import open_db
from auditview.db.schema import run_migrations
from auditview.core.watcher import WatcherService

from auditview.api.sessions import bp as sessions_bp
from auditview.api.files import bp as files_bp
from auditview.api.lines import bp as lines_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.checkpoints import bp as checkpoints_bp
from auditview.api.events import bp as events_bp
from auditview.api.coverage import bp as coverage_bp
from auditview.api.config import bp as config_bp


logger = logging.getLogger("auditview")

_SLOW_MS = 200  # log requests that take longer than this


def create_app(db_path, root_path):
    app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
    app.config["DB_PATH"] = db_path
    app.config["ROOT_PATH"] = root_path

    @app.before_request
    def _start_timer():
        g._t = time.perf_counter()

    @app.after_request
    def _log_request(response):
        dt_ms = (time.perf_counter() - g._t) * 1000
        if dt_ms >= _SLOW_MS:
            logger.warning("SLOW %s %s → %d  %.0fms", request.method, request.path, response.status_code, dt_ms)
        else:
            logger.debug("%s %s → %d  %.0fms", request.method, request.path, response.status_code, dt_ms)
        return response

    conn = open_db(db_path)
    run_migrations(conn)
    if hasattr(conn, 'close'):
        conn.close()

    watcher = WatcherService(db_path, root_path)
    watcher.start()
    app.watcher = watcher

    app.register_blueprint(sessions_bp, url_prefix="/api")
    app.register_blueprint(files_bp, url_prefix="/api")
    app.register_blueprint(lines_bp, url_prefix="/api")
    app.register_blueprint(notes_bp, url_prefix="/api")
    app.register_blueprint(checkpoints_bp, url_prefix="/api")
    app.register_blueprint(events_bp, url_prefix="/api")
    app.register_blueprint(coverage_bp, url_prefix="/api")
    app.register_blueprint(config_bp, url_prefix="/api")

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        if path.startswith("api/"):
            abort(404)
        static = app.static_folder
        full = os.path.join(static, path)
        if path and os.path.isfile(full):
            return send_from_directory(static, path)
        return send_from_directory(static, "index.html")

    return app
