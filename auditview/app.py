import asyncio
import os
import signal
import time
import logging
from quart import Quart, send_from_directory, abort, g, request

from auditview.db.connection import open_db
from auditview.db.schema import run_migrations
from auditview.core.watcher import WatcherService
from auditview.core.lsp import LspService

from auditview.api.sessions import bp as sessions_bp
from auditview.api.files import bp as files_bp
from auditview.api.lines import bp as lines_bp
from auditview.api.notes import bp as notes_bp
from auditview.api.issues import bp as issues_bp
from auditview.api.events import bp as events_bp
from auditview.api.coverage import bp as coverage_bp
from auditview.api.config import bp as config_bp
from auditview.api.lsp import bp as lsp_bp
from auditview.api.mcp import setup_mcp, get_mcp_handler, mcp as _mcp


logger = logging.getLogger("auditview")

_SLOW_MS = 200


def create_app(db_path, root_path, enable_lsp=False):
    app = Quart(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
    app.config["DB_PATH"] = db_path
    app.config["ROOT_PATH"] = root_path
    # Always defined so routes can report "disabled" rather than 404, and so a
    # test client that never runs before_serving still has the attribute.
    app.lsp = None

    @app.before_request
    async def _start_timer():
        g._t = time.perf_counter()

    @app.after_request
    async def _log_request(response):
        dt_ms = (time.perf_counter() - g._t) * 1000
        if dt_ms >= _SLOW_MS:
            logger.warning("SLOW %s %s → %d  %.0fms", request.method, request.path, response.status_code, dt_ms)
        else:
            logger.debug("%s %s → %d  %.0fms", request.method, request.path, response.status_code, dt_ms)
        return response

    @app.before_serving
    async def startup():
        async with open_db(db_path) as conn:
            await run_migrations(conn)

        loop = asyncio.get_running_loop()
        watcher = WatcherService(db_path, root_path)
        watcher.start(loop)
        app.watcher = watcher
        app.worker_task = asyncio.create_task(watcher.run_worker())

        # Catch shutdown before uvicorn's drain: by the time after_serving
        # runs, SSE connections are already gone and clients miss the goodbye.
        def on_shutdown(sig, uv):
            watcher.broadcast_all({"type": "shutdown"}, drain_first=True)
            if callable(uv):
                uv(sig, None)

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, on_shutdown, sig, signal.getsignal(sig))

    @app.after_serving
    async def shutdown():
        app.watcher.stop()
        app.worker_task.cancel()

    app.register_blueprint(sessions_bp, url_prefix="/api")
    app.register_blueprint(files_bp, url_prefix="/api")
    app.register_blueprint(lines_bp, url_prefix="/api")
    app.register_blueprint(notes_bp, url_prefix="/api")
    app.register_blueprint(issues_bp, url_prefix="/api")
    app.register_blueprint(events_bp, url_prefix="/api")
    app.register_blueprint(coverage_bp, url_prefix="/api")
    app.register_blueprint(config_bp, url_prefix="/api")
    app.register_blueprint(lsp_bp, url_prefix="/api")

    setup_mcp(app)
    mcp_handler = get_mcp_handler()

    @app.before_serving
    async def _start_mcp():
        stop = asyncio.Event()
        app._mcp_stop = stop

        async def _run():
            async with _mcp.session_manager.run():
                await stop.wait()

        app._mcp_task = asyncio.create_task(_run())
        await asyncio.sleep(0)  # yield so task group initializes before first request

    @app.after_serving
    async def _stop_mcp():
        app._mcp_stop.set()
        try:
            await asyncio.wait_for(app._mcp_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    # Its own hook pair rather than sharing the watcher's: subprocess teardown
    # wants a bounded graceful wait, which is the MCP pair's shape, not the
    # watcher's fire-and-forget cancel.
    @app.before_serving
    async def _start_lsp():
        if not enable_lsp:
            return
        lsp = LspService(root_path)
        lsp.start(asyncio.get_running_loop())
        app.lsp = lsp
        app.lsp_task = asyncio.create_task(lsp.run_worker())

    @app.after_serving
    async def _stop_lsp():
        if app.lsp is None:
            return
        app.lsp_task.cancel()
        try:
            await asyncio.wait_for(app.lsp.aclose(), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    async def serve_spa(path):
        if path.startswith("api/"):
            abort(404)
        static = app.static_folder
        static_real = os.path.realpath(static)
        # Resolve before probing so traversal candidates ("../etc/passwd") can
        # never reach os.path.isfile against arbitrary filesystem paths.
        if path:
            candidate = os.path.realpath(os.path.join(static, path))
            inside = candidate == static_real or candidate.startswith(static_real + os.sep)
            if inside and os.path.isfile(candidate):
                return await send_from_directory(static, path)
        return await send_from_directory(static, "index.html")

    async def asgi_app(scope, receive, send):
        if scope.get("path", "").startswith("/mcp"):
            await mcp_handler(scope, receive, send)
        else:
            await app(scope, receive, send)

    return asgi_app
