"""SilicoLab macOS application entry point (Cocoa + WKWebView)."""

import argparse
import fcntl
import secrets
import sys
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

from silicolab.branding import APP_NAME
from silicolab.desktop_lifecycle import atomic_json, ensure_service, gui_command, service_info, stop_service
from silicolab.paths import application_directory


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
        if self._window is None or self._window.get_current_url().split("#", 1)[0].split("?", 1)[0].rstrip("/") != self._origin:
            raise ValueError("此页面无法使用本机功能")

    def bootstrap(self):
        self._trusted()
        path = self._directory / "draft.json"
        try:
            draft = json.loads(path.read_text())
        except (OSError, ValueError):
            draft = None
        return {"desktop": True, "draft": draft, "selection": self._load_selection()}

    def _load_selection(self):
        try:
            value = json.loads((self._directory / "workbench-selection.json").read_text())
            if value is None: return None
            uuid.UUID(value["projectId"])
            if not isinstance(value["conversationId"], str) or not value["conversationId"].isdigit(): return None
            return {"projectId": value["projectId"], "conversationId": value["conversationId"]}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save_selection(self, selection):
        self._trusted()
        if selection is not None:
            if not isinstance(selection, dict) or set(selection) != {"projectId", "conversationId"}:
                raise ValueError("工作台选择只接受项目及对话身份")
            uuid.UUID(selection["projectId"])
            if not isinstance(selection["conversationId"], str) or not selection["conversationId"].isdigit() or len(selection["conversationId"]) > 30:
                raise ValueError("对话身份不合法")
        atomic_json(self._directory / "workbench-selection.json", selection)
        return True

    def choose_project_directory(self):
        self._trusted()
        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        return str(Path(selected[0]).resolve()) if selected else None

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
        with urlopen(f'{self._origin}/api/jobs/{job_id}', timeout=10) as response:
            job = json.load(response)
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
        return True

    def desktop_status(self):
        self._trusted()
        info = service_info(self._directory)
        return {"connected": bool(info), "backgroundPid": info["pid"] if info else None, "windowClose": "continues", "quit": "explicit"}

    def reconnect_background(self):
        self._trusted()
        info = ensure_service(self._directory, isolated_resources=getattr(self, '_isolated_resources', False))
        self._origin = info['origin']
        self._window.load_url(self._origin + '/?silicolabDesktop=1')
        return True

    def quit_application(self):
        self._trusted()
        if not self._window.create_confirmation_dialog("完全退出 SilicoLab？", "完全退出会停止本机执行并保存可恢复状态；独立远端作业不会自动取消。关闭窗口则仅离开界面、后台继续。"):
            return False
        stop_service(self._directory)
        self._window.destroy()
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


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--background-service' in arguments:
        from silicolab.desktop_service import main as service_main
        return service_main([arg for arg in arguments if arg != '--background-service'])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quit', action='store_true', help='完全退出独立后台及窗口')
    parser.add_argument('--close-window', action='store_true', help='真实关闭原生窗口，后台继续')
    parser.add_argument('--isolated-resources', action='store_true', help='仅空资源目录，用于人工验收')
    args = parser.parse_args(arguments)
    directory = application_directory()
    if args.quit:
        try:
            stop_service(directory)
        except ValueError as error:
            logging.error('%s', error)
            return 1
        gui_command(directory, 'close')
        return 0
    if args.close_window:
        return 0 if gui_command(directory, 'close') else 1
    configure_logs(directory)
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
    lock_file = (directory / 'app.lock').open('a+')
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        for _ in range(100):
            if gui_command(directory, 'show'): return 0
            time.sleep(0.05)
        raise ValueError('已有窗口尚未就绪；未启动第二个窗口或后台')
    info = ensure_service(directory, isolated_resources=args.isolated_resources)
    bridge = DesktopBridge(directory)
    bridge._isolated_resources = args.isolated_resources
    bridge._origin = info['origin']
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    bridge._window = webview.create_window(APP_NAME, url=info['origin'] + '/?silicolabDesktop=1', width=1440, height=980,
                                          min_size=(1000, 720), background_color='#f6f6f6', js_api=bridge)
    bridge._window.events.closing += bridge._confirm_close
    control = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control.bind(('127.0.0.1', 0)); control.listen(8); control.settimeout(0.2)
    token, gui_id = secrets.token_urlsafe(32), str(uuid.uuid4())
    descriptor = directory / 'gui-session.json'
    stopped = threading.Event()

    def close_window():
        # pywebview's Cocoa destroy calls NSWindow.close on the main thread; it
        # removes the actual WKWebView/window and stops the native event loop.
        bridge._window.destroy()

    def quit_all():
        try:
            stop_service(directory)
        except ValueError:
            show_error('后台未确认完全退出，窗口保持打开。请检查连接后重试。')
            return
        close_window()

    def controls():
        import hmac
        while not stopped.is_set():
            try:
                connection, _ = control.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(2)
                try:
                    raw = connection.makefile('rb').readline(4097)
                    request = json.loads(raw) if len(raw) <= 4096 else {}
                    accepted = hmac.compare_digest(str(request.get('token', '')), token) and request.get('operation') in ('show', 'close')
                    connection.sendall(json.dumps({'accepted': accepted}).encode())
                    if not accepted: continue
                    if request['operation'] == 'close': close_window()
                    else: bridge._window.restore(); bridge._window.show()
                except (OSError, ValueError):
                    pass

    from AppKit import NSObject
    from PyObjCTools import AppHelper
    class SilicoLabLifecycleDelegate(NSObject):
        def applicationShouldTerminate_(self, app):
            try:
                return bool(stop_service(directory) or service_info(directory) is None)
            except Exception:
                show_error('后台尚未确认退出，未停止应用；请重试“完全退出”。')
                return False

        def applicationSupportsSecureRestorableState_(self, app):
            return True

    def ready():
        def install_delegate():
            from webview.platforms.cocoa import BrowserView
            delegate = SilicoLabLifecycleDelegate.alloc().init()
            BrowserView.app.setDelegate_(delegate)
            BrowserView._shared_app_delegate = delegate
        AppHelper.callAfter(install_delegate)
        atomic_json(descriptor, {'pid': os.getpid(), 'port': control.getsockname()[1], 'token': token, 'guiId': gui_id, 'backgroundPid': info['pid']})
        threading.Thread(target=controls, name='silicolab-window-control', daemon=True).start()

    from webview.menu import Menu, MenuAction
    try:
        webview.start(ready, gui='cocoa', debug=os.environ.get('SILICOLAB_DESKTOP_DEBUG') == '1',
                      private_mode=False, storage_path=str(directory / 'WebKit'),
                      menu=[Menu('工作台', [MenuAction('显示主窗口', lambda: bridge._window.show()),
                                          MenuAction('关闭窗口（后台继续）', close_window),
                                          MenuAction('完全退出 SilicoLab', quit_all)])],
                      localization={'global.ok': '确定', 'global.cancel': '取消'})
    finally:
        stopped.set(); control.close()
        with bridge._lock: bridge._flush_draft()
        try:
            if json.loads(descriptor.read_text()).get('guiId') == gui_id: descriptor.unlink()
        except (OSError, ValueError):
            pass
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN); lock_file.close()
        # The service is intentionally NOT stopped by window/event-loop teardown.
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Desktop startup failed")
        show_error(str(error))
        raise SystemExit(1)
