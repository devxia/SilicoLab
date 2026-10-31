"""Application-owned supervisor: Node pipe loss stops and reaps trusted science workers."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading


def main(channel_fd=None):
    channel = socket.socket(fileno=channel_fd if channel_fd is not None else int(sys.argv[1]))
    send_lock = threading.Lock()
    jobs_lock = threading.Lock()
    jobs = {}
    closing = threading.Event()

    def send(message):
        with send_lock:
            try:
                channel.sendall((json.dumps(message, ensure_ascii=False) + '\n').encode())
            except OSError:
                closing.set()

    def run(identity, request):
        process = None
        try:
            with jobs_lock:
                if closing.is_set() or jobs[identity]['cancelled']:
                    raise ValueError('科学任务在启动前已停止')
                remote = request.get('workflow') == 'protein_factory_remote'
                module = 'remote_science_worker' if remote else 'science_worker'
                env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
                if remote:
                    for key in ('SILICOLAB_SCIENCE_REMOTE', 'SILICOLAB_SCIENCE_REMOTE_TIMEOUT'):
                        if os.environ.get(key):
                            env[key] = os.environ[key]
                process = subprocess.Popen([sys.executable, '-I', '-B', '-c',
                                            f'import sys;sys.path.insert(0,sys.argv[1]);from silicolab.{module} import main;main()',
                                            str(Path(__file__).resolve().parent.parent)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           close_fds=True, env=env)
                jobs[identity]['process'] = process
            send({'id': identity, 'event': 'started', 'pid': process.pid})
            stdout, stderr = process.communicate(json.dumps(request).encode(), timeout=300 if remote else 60)
            if len(stdout) > 16 * 1024 * 1024:
                raise ValueError('科学输出超过协议上限')
            if process.returncode:
                raise ValueError('科学进程已停止：' + stderr.decode(errors='replace')[-2000:])
            send({'id': identity, 'event': 'finished', 'response': json.loads(stdout)})
        except Exception as error:
            if process and process.poll() is None:
                process.kill()
                process.communicate()
            send({'id': identity, 'event': 'finished', 'error': str(error)})
        finally:
            with jobs_lock:
                jobs.pop(identity, None)

    try:
        with channel.makefile('r', encoding='utf-8') as incoming:
            for line in incoming:
                if len(line) > 8 * 1024 * 1024:
                    raise ValueError('科学输入超过协议上限')
                message = json.loads(line)
                identity = message['id']
                if message['op'] == 'start':
                    with jobs_lock:
                        if identity in jobs:
                            raise ValueError('重复科学进程身份')
                        thread = threading.Thread(target=run, args=(identity, message['request']))
                        jobs[identity] = {'thread': thread, 'process': None, 'cancelled': False}
                    thread.start()
                elif message['op'] == 'cancel':
                    with jobs_lock:
                        job = jobs.get(identity)
                        if job:
                            job['cancelled'] = True
                        process = job.get('process') if job else None
                        if process and process.poll() is None:
                            process.kill()
    finally:
        closing.set()
        with jobs_lock:
            remaining = list(jobs.values())
            for job in remaining:
                process = job['process']
                if process and process.poll() is None:
                    process.kill()
        for job in remaining:
            job['thread'].join(timeout=10)
        channel.close()


if __name__ == '__main__':
    main()
