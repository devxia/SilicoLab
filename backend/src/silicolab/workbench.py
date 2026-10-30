"""Project application contract; one owner and real durable Node host per project."""
import asyncio
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal


class ProjectPath(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(default='科研项目', min_length=1, max_length=200)


class ConversationTitle(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ScienceParameters(BaseModel):
    stopPolicy: Literal['preserve', 'add']
    avoid: str = Field(default='', max_length=2000)


class TaskInput(BaseModel):
    conversationId: str = Field(min_length=1, max_length=100)
    requestId: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=100000)
    authorizedTools: list[str] = Field(default_factory=list, max_length=20)
    workflow: Literal['validation', 'd2p_local'] = 'validation'
    specialtyAcknowledged: bool = False
    inputVersionId: str | None = Field(default=None, max_length=100)
    parameters: ScienceParameters | None = None


class ImportFile(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contentBase64: str = Field(max_length=7 * 1024 * 1024)


class FreezeInputs(BaseModel):
    conversationId: str = Field(min_length=1, max_length=100)
    fileIds: list[str] = Field(min_length=1, max_length=20)


class DraftInput(BaseModel):
    text: str = Field(max_length=100000)
    revision: int = Field(ge=0)


class ProjectHost:
    def __init__(self, path, create, name):
        self.path = Path(path).resolve(strict=True)
        if not self.path.is_dir():
            raise ValueError('请选择存在的项目目录')
        self.state = self.path / '.silicolab'
        if self.state.is_symlink():
            raise ValueError('项目状态目录不能是符号链接')
        if not create and not (self.state / 'session.sqlite').is_file():
            raise ValueError('所选目录没有 SilicoLab 项目')
        self.state.mkdir(mode=0o700, exist_ok=True)
        for file in ['owner.lock', 'session.sqlite', 'session.sqlite-wal', 'session.sqlite-shm']:
            if (self.state / file).is_symlink():
                raise ValueError('项目状态文件不能是符号链接')
        self._lease = (self.state / 'owner.lock').open('a')
        self._process = None
        self._serial = threading.Lock()
        self._next = 0
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            runtime = Path(os.environ.get('SILICOLAB_RUNTIME', Path(__file__).resolve().parents[3] / 'runtime'))
            node = os.environ.get('SILICOLAB_NODE') or shutil.which('node')
            if not node or not (runtime / 'node_modules/@earendil-works/pi-durable/package.json').is_file():
                raise ValueError('智能体运行时未安装，请按开发文档安装 runtime 依赖')
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8',
                   'SILICOLAB_PYTHON': sys.executable, 'SILICOLAB_BACKEND': str(Path(__file__).resolve().parent.parent)}
            self._process = subprocess.Popen([node, str(runtime / 'src/host.ts'), str(self.state),
                                              'create' if create else 'open', name],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             text=True, bufsize=1, close_fds=True, pass_fds=(self._lease.fileno(),), env=env)
            if not self._read().get('ready'):
                raise ValueError('智能体宿主未就绪')
        except BaseException:
            self.close()
            raise

    def _read(self):
        if not select.select([self._process.stdout], [], [], 10)[0]:
            raise ValueError('智能体宿主响应超时')
        line = self._process.stdout.readline()
        if not line:
            raise ValueError('智能体宿主已退出')
        return json.loads(line)

    def call(self, op, **values):
        with self._serial:
            if self._process.poll() is not None:
                raise ValueError('智能体宿主已退出')
            self._next += 1
            self._process.stdin.write(json.dumps({'id': self._next, 'op': op, **values}) + '\n')
            self._process.stdin.flush()
            response = self._read()
            if response.get('id') != self._next:
                raise ValueError('智能体宿主响应身份不匹配')
            if 'error' in response:
                raise ValueError(response['error'])
            return response['result']

    def alive(self):
        return self._process is not None and self._process.poll() is None

    def close(self):
        if self._process:
            if self._process.poll() is None:
                try:
                    self.call('close')
                    self._process.wait(timeout=5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self._process.kill()
                    self._process.wait(timeout=5)
            self._process.stdin.close()
            self._process.stdout.close()
        if not self._lease.closed:
            self._lease.close()


class Workbench:
    def __init__(self, index):
        self.index = Path(index)
        self._hosts = {}
        self._lock = threading.RLock()
        self._index_error = None
        try:
            self._projects = json.loads(self.index.read_text())
            if not isinstance(self._projects, list) or any(
                not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key] for key in ['id', 'name', 'path'])
                for item in self._projects
            ):
                raise ValueError('项目索引结构不完整')
        except FileNotFoundError:
            self._projects = []
        except (OSError, ValueError):
            self._projects = []
            self._index_error = '项目索引无法读取；原文件已保留，请明确重新打开项目目录恢复关联'

    def list(self):
        with self._lock:
            if self._index_error:
                raise ValueError(self._index_error)
            return [dict(item) for item in self._projects]

    def open(self, path, create=False, name='科研项目', expected_id=None):
        with self._lock:
            canonical = str(Path(path).resolve(strict=True))
            host = self._hosts.get(canonical)
            if host is not None and not host.alive():
                host.close()
                del self._hosts[canonical]
                host = None
            fresh = host is None
            if fresh:
                host = ProjectHost(canonical, create, name)
                self._hosts[canonical] = host
            try:
                snapshot = host.call('status')
                if expected_id is not None and snapshot['id'] != expected_id:
                    raise ValueError('所选目录的项目身份已改变；未执行操作，请重新定位并核对项目')
            except BaseException:
                if fresh:
                    host.close()
                    self._hosts.pop(canonical, None)
                raise
            item = {'id': snapshot['id'], 'name': snapshot['name'], 'path': canonical}
            existing = next((item for item in self._projects if item['id'] == snapshot['id']), None)
            if existing:
                existing.update(item)
            else:
                self._projects.append(item)
            self.index.parent.mkdir(parents=True, exist_ok=True)
            if self._index_error:
                backup = self.index.with_name(f'projects.corrupt-{uuid.uuid4().hex}.json')
                shutil.copyfile(self.index, backup)
                backup.chmod(0o600)
            temporary = self.index.with_suffix('.tmp')
            temporary.write_text(json.dumps(self._projects, ensure_ascii=False))
            temporary.chmod(0o600)
            temporary.replace(self.index)
            self._index_error = None
            return {**snapshot, 'path': canonical}

    def call(self, project_id, op, **values):
        with self._lock:
            item = next((p for p in self._projects if p['id'] == project_id), None)
            if item is None:
                raise ValueError('项目不存在')
            self.open(item['path'], expected_id=project_id)
            result = self._hosts[str(Path(item['path']).resolve())].call(op, **values)
            return {**result, 'path': item['path']} if op == 'status' else result

    def close(self):
        with self._lock:
            for host in self._hosts.values():
                host.close()
            self._hosts.clear()


def router(workbench):
    routes = APIRouter(prefix='/api/workbench')

    def invoke(action, *args, **kwargs):
        try:
            return action(*args, **kwargs)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise HTTPException(409, str(error)) from error

    @routes.get('/projects')
    def projects():
        return invoke(workbench.list)

    @routes.post('/projects', status_code=201)
    def create_project(body: ProjectPath):
        return invoke(workbench.open, body.path, True, body.name)

    @routes.post('/projects/open')
    def open_project(body: ProjectPath):
        return invoke(workbench.open, body.path)

    @routes.get('/projects/{project_id}')
    def project(project_id: str):
        return invoke(workbench.call, project_id, 'status')

    @routes.post('/projects/{project_id}/conversations', status_code=201)
    def conversation(project_id: str, body: ConversationTitle):
        return invoke(workbench.call, project_id, 'conversation.create', title=body.title)

    @routes.put('/projects/{project_id}/conversations/{conversation_id}/draft')
    def draft(project_id: str, conversation_id: str, body: DraftInput):
        return invoke(workbench.call, project_id, 'draft.save', conversationId=conversation_id,
                      text=body.text, revision=body.revision)

    @routes.post('/projects/{project_id}/files', status_code=201)
    def import_file(project_id: str, body: ImportFile):
        return invoke(workbench.call, project_id, 'file.import', name=body.name, contentBase64=body.contentBase64)

    @routes.get('/projects/{project_id}/files/{file_id}')
    def preview_file(project_id: str, file_id: str):
        return invoke(workbench.call, project_id, 'file.preview', fileId=file_id)

    @routes.post('/projects/{project_id}/input-versions', status_code=201)
    def freeze_inputs(project_id: str, body: FreezeInputs):
        return invoke(workbench.call, project_id, 'input.freeze', conversationId=body.conversationId, fileIds=body.fileIds)

    @routes.get('/projects/{project_id}/input-versions/{version_id}')
    def fixed_inputs(project_id: str, version_id: str):
        return invoke(workbench.call, project_id, 'input.read', versionId=version_id)

    @routes.post('/projects/{project_id}/tasks', status_code=201)
    def start_task(project_id: str, body: TaskInput):
        return invoke(workbench.call, project_id, 'task.start', **body.model_dump(exclude_none=True))

    @routes.post('/projects/{project_id}/tasks/{task_id}/cancel')
    def cancel_task(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'task.cancel', taskId=task_id)

    @routes.get('/projects/{project_id}/tasks/{task_id}/artifacts/{execution_id}/{name}')
    def download_artifact(project_id: str, task_id: str, execution_id: str, name: str):
        artifact = invoke(workbench.call, project_id, 'task.artifact', taskId=task_id, executionId=execution_id, name=name)
        safe_name = artifact['name']
        return Response(base64.b64decode(artifact['contentBase64']), media_type=artifact['mediaType'],
                        headers={'Content-Disposition': f'attachment; filename="{safe_name}"'})

    @routes.get('/projects/{project_id}/conversations/{conversation_id}')
    def conversation_status(project_id: str, conversation_id: str):
        return invoke(workbench.call, project_id, 'conversation.status', conversationId=conversation_id)

    @routes.get('/projects/{project_id}/conversations/{conversation_id}/events')
    async def conversation_events(project_id: str, conversation_id: str, request: Request):
        # Stream committed state snapshots; observing does not admit input or resume tasks.
        previous = request.headers.get('last-event-id', '')
        async def stream():
            nonlocal previous
            while not await request.is_disconnected() and not request.app.state.stopping.is_set():
                try:
                    state = await asyncio.to_thread(workbench.call, project_id, 'conversation.status', conversationId=conversation_id)
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    yield 'event: problem\ndata: ' + json.dumps({'error': str(error)}) + '\n\n'
                    return
                content = json.dumps(state, ensure_ascii=False, sort_keys=True)
                version = hashlib.sha256(content.encode()).hexdigest()
                if version != previous:
                    yield f'id: {version}\ndata: {content}\n\n'
                    previous = version
                else:
                    yield ': keepalive\n\n'
                await asyncio.sleep(0.12)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})

    return routes
