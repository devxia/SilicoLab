"""SilicoLab macOS application entry point (Cocoa + WKWebView)."""

import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import uuid

import certifi
import webview

from silicolab.branding import APP_NAME, DATABASE_FILENAME
from silicolab.paths import application_directory, read_preferences, write_preferences


class DesktopBridge:
    """Small native surface: clipboard, file saving and persistent editor draft."""

    def __init__(self, directory):
        self._directory = directory
        self._window = None
        self._app = None
        self._origin = None
        self._pending_draft = None
        self._lock = threading.Lock()
        self._last_draft_write = time.monotonic()

    def _trusted(self):
        if self._window is None or self._window.get_current_url().split("?", 1)[0].rstrip("/") != self._origin:
            raise ValueError("此页面无法使用本机功能")

    def bootstrap(self):
        self._trusted()
        path = self._directory / "draft.json"
        try:
            draft = json.loads(path.read_text())
        except (OSError, ValueError):
            draft = None
        return {"desktop": True, "draft": draft}

    def save_draft(self, draft):
        self._trusted()
        if not isinstance(draft, dict) or len(json.dumps(draft)) > 8 * 1024 * 1024:
            raise ValueError("草稿格式或大小不受支持")
        with self._lock:
            self._pending_draft = draft
            if time.monotonic() - self._last_draft_write >= 2:
                self._flush_draft()
        return True

    def _flush_draft(self):
        if self._pending_draft is None:
            return
        path = self._directory / "draft.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._pending_draft, ensure_ascii=False))
        temporary.chmod(0o600)
        temporary.replace(path)
        self._pending_draft = None
        self._last_draft_write = time.monotonic()

    def copy_text(self, text):
        self._trusted()
        if not isinstance(text, str) or len(text) > 100000:
            raise ValueError("复制内容过长")
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)
        return True

    def save_export(self, payload):
        """Write an atomic export into Downloads/SilicoLab without overwriting."""
        self._trusted()
        if not isinstance(payload, dict):
            raise ValueError("导出参数不合法")
        job_id, format, record_id, filename = (payload.get(key) for key in ["job_id", "format", "record_id", "filename"])
        uuid.UUID(job_id)
        if format not in {"fasta", "xlsx", "zip"}:
            raise ValueError("导出格式不受支持")
        if record_id:
            uuid.UUID(record_id)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("文件名称不合法")
        from Foundation import NSDownloadsDirectory, NSUserDomainMask, NSSearchPathForDirectoriesInDomains
        directory = Path(NSSearchPathForDirectoriesInDomains(NSDownloadsDirectory, NSUserDomainMask, True)[0]) / APP_NAME
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = directory / filename
        index = 2
        while output.exists():
            output = directory / f"{Path(filename).stem}-{index}{Path(filename).suffix}"
            index += 1
            if index > 1000:
                raise ValueError("同名导出文件过多，请清理下载目录")
        job = self._app.state.store.get(job_id)
        records = job["records"]
        if record_id:
            records = [record for record in records if record["id"] == record_id]
            if not records:
                raise ValueError("序列不存在")
        from silicolab.features.codon.spreadsheets import synthesis_workbook
        content = synthesis_workbook(records) if format == "xlsx" else None
        if content is None:
            query = urlencode({"format": format, **({"record_id": record_id} if record_id else {})})
            with urlopen(f"{self._origin}/api/jobs/{job_id}/export?{query}", timeout=60) as response:
                content = response.read()
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return {"saved": True, "directory": str(directory)}

    def open_export_directory(self):
        self._trusted()
        from Foundation import NSDownloadsDirectory, NSUserDomainMask, NSSearchPathForDirectoriesInDomains, NSURL
        from AppKit import NSWorkspace
        directory = Path(NSSearchPathForDirectoriesInDomains(NSDownloadsDirectory, NSUserDomainMask, True)[0]) / APP_NAME
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(directory)))
        return True

    def _confirm_close(self):
        with self._lock:
            self._flush_draft()
        active = self._app and self._app.state.store.active_count() > 0
        if active:
            return self._window.create_confirmation_dialog(
                "退出 SilicoLab？", "当前还有未完成任务。退出后未完成项将在下次启动时标记为中断；已发送的远端请求无法撤回。")
        return True


def show_error(message):
    from AppKit import NSAlert, NSApplication
    NSApplication.sharedApplication()
    alert = NSAlert.alloc().init()
    alert.setMessageText_("SilicoLab 无法启动")
    alert.setInformativeText_(message)
    alert.runModal()


def configure_logs(directory):
    handler = RotatingFileHandler(directory / "desktop.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ["uvicorn", "uvicorn.error", "pywebview"]:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False


def bind_server(directory):
    preferences = read_preferences(directory)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    port = preferences.get("port", 0)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        port = 0
    try:
        listener.bind(("127.0.0.1", port))
    except OSError:
        listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    write_preferences(directory, preferences | {"port": port})
    return listener, f"http://127.0.0.1:{port}"


LOADING_SCREEN = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
body{margin:0;display:grid;place-items:center;height:100vh;background:#f6f6f6;color:#191919;
font:15px -apple-system,BlinkMacSystemFont,sans-serif}main{text-align:center}
h1{font-size:25px;font-weight:600}p{color:#888;font-size:12px}</style>
<main><h1>SilicoLab</h1><p>正在准备本地工作台…</p></main></html>"""


def main():
    directory = application_directory()
    configure_logs(directory)
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    lock_file = (directory / "app.lock").open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        logging.info("Another desktop instance is already running")
        return 0
    bridge = DesktopBridge(directory)
    listener, origin = bind_server(directory)
    bridge._origin = origin
    runtime = {}
    stop_requested = threading.Event()
    boot_failed = threading.Event()

    def serve():
        try:
            # Prepare the API concurrently with Cocoa/WebKit instead of blocking
            # the main thread on FastAPI's imports before the window exists.
            import uvicorn
            from silicolab.server import create_app
            app = create_app(db_path=directory / DATABASE_FILENAME)
            bridge._app = app
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=listener.getsockname()[1],
                                                 loop="asyncio", http="h11", ws="none", log_config=None,
                                                 access_log=False, timeout_graceful_shutdown=2))
            runtime.update(app=app, server=server)
            if stop_requested.is_set():
                return
            server.run(sockets=[listener])
        except Exception:
            logging.exception("Local API startup failed")
            boot_failed.set()

    thread = threading.Thread(target=serve, name="silicolab-api", daemon=True)
    thread.start()
    debug = os.environ.get("SILICOLAB_DESKTOP_DEBUG") == "1"
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    bridge._window = webview.create_window(APP_NAME, html=LOADING_SCREEN, width=1440, height=980,
                                          min_size=(1000, 720), background_color="#f6f6f6", js_api=bridge)
    bridge._window.events.closing += bridge._confirm_close

    def open_workspace():
        for _ in range(300):
            if stop_requested.is_set():
                return
            server = runtime.get("server")
            if server is not None and server.started:
                logging.info("Desktop server ready at %s", origin)
                bridge._window.load_url(origin)
                return
            if boot_failed.is_set():
                break
            time.sleep(.05)
        bridge._window.load_html(LOADING_SCREEN.replace("正在准备本地工作台…", "启动未完成，请重新打开应用；详情见应用数据目录 desktop.log。"))

    try:
        webview.start(open_workspace, gui="cocoa", debug=debug, private_mode=False, storage_path=str(directory / "WebKit"),
                      localization={"global.ok": "确定", "global.cancel": "取消", "global.quitConfirmation": "确定退出？"})
    finally:
        stop_requested.set()
        if "app" in runtime and hasattr(runtime["app"].state, "loop"):
            # End SSE before Uvicorn waits for open HTTP responses.
            def stop_api_work():
                runtime["app"].state.stopping.set()
                runtime["app"].state.worker_task.cancel()
            runtime["app"].state.loop.call_soon_threadsafe(stop_api_work)
        if "server" in runtime:
            runtime["server"].should_exit = True
        thread.join(timeout=3)
        listener.close()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Desktop startup failed")
        show_error(str(error))
        raise SystemExit(1)
