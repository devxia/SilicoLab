"""Open or stop the local SilicoLab production server."""
import argparse
import json
import os
import signal
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn
from silicolab.branding import SERVICE_ID

URL = 'http://127.0.0.1:8765'

def running_server():
    try:
        with urlopen(URL + '/api/health', timeout=1) as response:
            data = json.load(response)
            return data if data.get('app') == SERVICE_ID else None
    except (URLError, OSError, ValueError):
        return None

def open_when_ready():
    for _ in range(50):
        if running_server():
            webbrowser.open(URL)
            return
        time.sleep(0.2)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true', help='停止本地服务；已发送的请求无法撤回')
    args = parser.parse_args()
    existing = running_server()
    if args.stop:
        if existing:
            os.kill(existing['pid'], signal.SIGINT)
            print('已请求停止 SilicoLab。本次未完成项将在重启后标记为中断。')
        else:
            print('SilicoLab 当前没有运行。')
    elif existing:
        webbrowser.open(URL)
        print('SilicoLab 已在运行：' + URL)
    else:
        threading.Thread(target=open_when_ready, daemon=True).start()
        print('SilicoLab · ' + URL + '\n按 Ctrl+C 停止本地服务。')
        uvicorn.run('silicolab.server:create_app', factory=True, host='127.0.0.1', port=8765)


if __name__ == '__main__':
    main()
