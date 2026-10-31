"""Project application contract; one owner and real durable Node host per project."""
import asyncio
import base64
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
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
    stopPolicy: Literal['preserve', 'add', 'ask']
    avoid: str = Field(default='', max_length=2000)


class SimulationInput(BaseModel):
    payload: str = Field(max_length=10000)
    durationMs: int = Field(default=1000, ge=0, le=60000)
    queryable: bool = True
    responseMode: Literal['normal', 'lost', 'hold_after_accept'] = 'normal'


class TaskInput(BaseModel):
    conversationId: str = Field(min_length=1, max_length=100)
    requestId: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=100000)
    authorizedTools: list[str] = Field(default_factory=list, max_length=20)
    workflow: Literal['validation', 'd2p_local', 'simulated_external', 'protein_factory_remote', 'python_analysis'] = 'validation'
    simulation: SimulationInput | None = None
    specialtyAcknowledged: bool = False
    inputVersionId: str | None = Field(default=None, max_length=100)
    parameters: ScienceParameters | None = None


class DecisionAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=100)


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
    def __init__(self, path, create, name, simulated, model_configuration, skill_roots=None, expected_id=None):
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
        self._offline_reason = None
        self._last_snapshot = None
        self._monitor_stop = threading.Event()
        self._monitor = None
        self._identities = [(p, p.stat().st_dev, p.stat().st_ino) for p in (self.path, self.state) + (() if create else (self.state / 'session.sqlite',))]
        self._lease = (self.state / 'owner.lock').open('a')
        self._process = None
        self._supervisor = None
        self._credentials = None
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
            if expected_id:
                env['SILICOLAB_EXPECTED_PROJECT'] = expected_id
            env['SILICOLAB_SIMULATED_EXECUTOR'] = simulated.url
            env['SILICOLAB_SIMULATED_EXECUTOR_ID'] = simulated.info()['serviceId']
            from silicolab.model_configuration import ModelCredentialChannel
            self._credentials = ModelCredentialChannel(model_configuration)
            env['SILICOLAB_MODEL_FD'] = str(self._credentials.client.fileno())
            if skill_roots is None:
                skill_sources = [{'path': str(self.path / folder), 'anchor': str(self.path), 'source': 'project:' + folder} for folder in ('.agents/skills', '.claude/skills', '.pi/skills')]
                home = Path.home()
                skill_sources += [{'path': str(home / folder), 'anchor': str(home), 'source': 'user:~/' + folder} for folder in ('.agents/skills', '.claude/skills', '.pi/agent/skills')]
            else:
                skill_sources = [{'path': str(self.path / '.agents/skills'), 'anchor': str(self.path), 'source': 'project:.agents/skills'}]
                skill_sources += [{'path': str(Path(folder).resolve()), 'anchor': str(Path(folder).resolve()), 'source': f'test:skills-{index}'} for index, folder in enumerate(skill_roots)]
            env['SILICOLAB_SKILL_ROOTS'] = json.dumps(skill_sources)
            science_env = {'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}
            for key in ('SILICOLAB_SCIENCE_REMOTE', 'SILICOLAB_SCIENCE_REMOTE_TIMEOUT'):
                if os.environ.get(key):
                    science_env[key] = os.environ[key]
            node_channel, supervisor_channel = socket.socketpair()
            try:
                self._supervisor = subprocess.Popen([sys.executable, '-I', '-B', '-c',
                                                     'import sys;sys.path.insert(0,sys.argv[1]);from silicolab.science_supervisor import main;main(int(sys.argv[2]))',
                                                     str(Path(__file__).resolve().parent.parent), str(supervisor_channel.fileno())],
                                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                    env=science_env, close_fds=True,
                                                    pass_fds=(supervisor_channel.fileno(),))
                env['SILICOLAB_SCIENCE_FD'] = str(node_channel.fileno())
                self._process = subprocess.Popen([node, str(runtime / 'src/host.ts'), str(self.state),
                                                  'create' if create else 'open', name],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                 text=True, bufsize=1, close_fds=True,
                                                 pass_fds=(self._lease.fileno(), node_channel.fileno(), self._credentials.client.fileno()), env=env)
            finally:
                node_channel.close()
                supervisor_channel.close()
                self._credentials.detach_client()
            if not self._read().get('ready'):
                raise ValueError('智能体宿主未就绪')
            self._identities = [(p, p.stat().st_dev, p.stat().st_ino) for p in (self.path, self.state, self.state / 'session.sqlite')]
            self._monitor = threading.Thread(target=self._watch, daemon=True)
            self._monitor.start()
        except BaseException:
            self.close()
            raise

    def available(self):
        if self._offline_reason:
            return False
        try:
            for path, device, inode in self._identities:
                info = path.stat()
                if path.is_symlink() or info.st_dev != device or info.st_ino != inode or not info.st_mode & 0o222 or not os.access(path, os.R_OK | os.W_OK):
                    raise OSError()
        except OSError:
            self._offline_reason = '项目目录不可访问、不可写或身份改变；本机执行已停止，请重新定位核对'
            return False
        return True

    def _watch(self):
        while not self._monitor_stop.wait(0.075):
            if not self.available():
                self.emergency_stop()
                return

    def emergency_stop(self):
        # Do not ask a host to flush state onto an unavailable/replaced directory.
        with self._serial:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._supervisor:
            try:
                self._supervisor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._supervisor.kill()
                self._supervisor.wait(timeout=5)

    def offline_snapshot(self):
        self.emergency_stop()
        saved = copy.deepcopy(self._last_snapshot or {})
        saved['availability'] = {'status': 'offline', 'reason': self._offline_reason or '项目目录不可用', 'progressSaved': False}
        saved['scheduling'] = 'offline'
        for task in saved.get('tasks', []):
            if task['status'] in ('running', 'queued', 'admission_pending'):
                task['status'] = 'paused'
                task['pauseReason'] = '目录离线；仅显示最后已观察快照，最新进度未确认保存'
        return saved

    def _read(self):
        if not select.select([self._process.stdout], [], [], 10)[0]:
            raise ValueError('智能体宿主响应超时')
        line = self._process.stdout.readline()
        if not line:
            raise ValueError('智能体宿主已退出')
        return json.loads(line)

    def call(self, op, **values):
        if not self.available():
            self.emergency_stop()
            raise ValueError(self._offline_reason)
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
            if op == 'status':
                self._last_snapshot = copy.deepcopy(response['result'])
            return response['result']

    def alive(self):
        return self._process is not None and self._process.poll() is None and self._supervisor is not None and self._supervisor.poll() is None

    def close(self):
        self._monitor_stop.set()
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=5)
        if not self.available():
            self.emergency_stop()
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
        if self._supervisor:
            try:
                self._supervisor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._supervisor.kill()
                self._supervisor.wait(timeout=5)
        if self._credentials:
            self._credentials.close()
        if not self._lease.closed:
            self._lease.close()


class Workbench:
    def __init__(self, index):
        self.index = Path(index)
        self._hosts = {}
        self._lock = threading.RLock()
        self._index_error = None
        self._offline = {}
        self._project_lines = {}
        self._path_lines = {}
        self._opening = set()
        self._simulated = None
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

    def simulated(self):
        with self._lock:
            if self._simulated is None:
                from silicolab.simulated_executor import SimulatedExecutor
                self._simulated = SimulatedExecutor(self.index.with_name('simulated-executor.sqlite3'))
            return self._simulated

    def list(self):
        with self._lock:
            if self._index_error:
                raise ValueError(self._index_error)
            return [dict(item) for item in self._projects]

    def _project_line(self, identity):
        with self._lock:
            return self._project_lines.setdefault(identity, threading.RLock())

    def _path_line(self, canonical):
        with self._lock:
            return self._path_lines.setdefault(canonical, threading.RLock())

    def _write_index(self, candidate):
        # Caller holds only the short index publication lock, never a content-read lock.
        self.index.parent.mkdir(parents=True, exist_ok=True)
        if self._index_error:
            backup = self.index.with_name(f'projects.corrupt-{uuid.uuid4().hex}.json')
            shutil.copyfile(self.index, backup)
            backup.chmod(0o600)
        temporary = self.index.with_name(f'projects-{uuid.uuid4().hex}.tmp')
        try:
            with open(temporary, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as output:
                json.dump(candidate, output, ensure_ascii=False)
                output.flush(); os.fsync(output.fileno())
            temporary.replace(self.index)
        finally:
            temporary.unlink(missing_ok=True)
        self._projects = candidate
        self._index_error = None

    def open(self, path, create=False, name='科研项目', expected_id=None):
        canonical = str(Path(path).resolve(strict=True))
        fresh, host, reserved = False, None, False
        try:
            # Provisional hosts do not run tasks or publish a new association.
            with self._path_line(canonical):
                with self._lock:
                    if canonical in self._opening:
                        raise ValueError('该目录正在打开核验，请稍后重试')
                    host = self._hosts.get(canonical)
                if host is not None and (not host.alive() or not host.available()):
                    host.close()
                    with self._lock: self._hosts.pop(canonical, None)
                    host = None
                fresh = host is None
                if fresh:
                    with self._lock:
                        if len(self._hosts) + len(self._opening) >= 4:
                            raise ValueError('当前最多打开4个项目宿主；请结束并重新打开应用选择项目')
                        self._opening.add(canonical); reserved = True
                    host = ProjectHost(canonical, create, name, self.simulated(), self.model_configuration, self.skill_roots, expected_id)
                snapshot = host.call('status')
                if expected_id is not None and snapshot['id'] != expected_id:
                    raise ValueError('所选目录的项目身份已改变；未执行操作，请重新定位并核对项目')
            # Release the path line before joining the actual UUID's lifecycle line.
            # All operation/publication lock ordering is project -> path -> index.
            with self._project_line(snapshot['id']):
                with self._path_line(canonical):
                    with self._lock:
                        prior = next((dict(p) for p in self._projects if p['id'] == snapshot['id']), None)
                        prior_host = self._hosts.get(prior['path']) if prior and prior['path'] != canonical else None
                    if prior_host:
                        if prior_host.available() and prior_host.alive():
                            raise ValueError('原项目目录仍在线，不能将另一份同身份副本冒充重新定位')
                        with self._path_line(prior['path']):
                            prior_host.close()
                            with self._lock: self._hosts.pop(prior['path'], None)
                    host.call('project.verify')
                    snapshot = host.call('status')
                    item = {'id': snapshot['id'], 'name': snapshot['name'], 'path': canonical}
                    with self._lock:
                        candidate = [dict(item) if p['id'] == snapshot['id'] else dict(p) for p in self._projects]
                        if not any(p['id'] == snapshot['id'] for p in candidate): candidate.append(item)
                        self._write_index(candidate)
                        self._hosts[canonical] = host
                        self._offline.pop(snapshot['id'], None)
                    return {**snapshot, 'path': canonical, 'availability': {'status': 'online', 'progressSaved': True}}
        except BaseException:
            if fresh and host: host.close()
            raise
        finally:
            if reserved:
                with self._lock: self._opening.discard(canonical)

    def call(self, project_id, op, **values):
        with self._project_line(project_id):
            with self._lock:
                item = next((dict(p) for p in self._projects if p['id'] == project_id), None)
            if item is None: raise ValueError('项目不存在')
            canonical = str(Path(item['path']).resolve())
            with self._path_line(canonical):
                with self._lock: host = self._hosts.get(canonical)
                if host is not None and not host.available():
                    snapshot = host.offline_snapshot()
                    with self._lock:
                        if self._hosts.get(canonical) is host:
                            self._offline[project_id] = snapshot
                with self._lock: offline = copy.deepcopy(self._offline.get(project_id))
                if offline:
                    if op == 'status': return {**offline, 'path': item['path']}
                    raise ValueError(offline['availability']['reason'])
                if host is None or not host.alive():
                    try:
                        self.open(item['path'], expected_id=project_id)
                    except (OSError, ValueError):
                        snapshot = {'id': project_id, 'name': item['name'], 'conversations': [], 'files': [], 'inputVersions': [], 'tasks': [], 'scheduling': 'offline', 'modelRequests': 0, 'availability': {'status': 'offline', 'progressSaved': False, 'reason': '项目目录不可访问；未创建替代项目，请重新定位'}}
                        with self._lock: self._offline[project_id] = snapshot
                        if op == 'status': return {**snapshot, 'path': item['path']}
                        raise
                    with self._lock: host = self._hosts[canonical]
                result = host.call(op, **values)
                if op == 'task.pause' and result.get('pausedHost'):
                    host.close()
                    with self._lock: self._hosts.pop(canonical, None)
                    snapshot = self.open(item['path'], expected_id=project_id)
                    return next(task for task in snapshot['tasks'] if task['id'] == values['taskId'])
                return {**result, 'path': item['path'], 'availability': {'status': 'online', 'progressSaved': True}} if op == 'status' else result

    def relocate(self, project_id, path):
        with self._project_line(project_id):
            with self._lock:
                item = next((dict(p) for p in self._projects if p['id'] == project_id), None)
            if not item: raise ValueError('项目不存在')
            canonical = str(Path(item['path']).resolve())
            with self._path_line(canonical):
                with self._lock: old = self._hosts.pop(canonical, None)
                if old: old.close()
            return self.open(path, expected_id=project_id)

    def remove(self, project_id):
        with self._project_line(project_id):
            state = self.call(project_id, 'status')
            if state.get('availability', {}).get('status') == 'offline':
                raise ValueError('项目离线，请先重新定位核对后移除关联')
            if any(t['status'] in ('running', 'queued', 'admission_pending', 'external_submitting') for t in state['tasks']):
                raise ValueError('项目有活动或排队任务，请先明确暂停/取消再移除关联')
            canonical = str(Path(state['path']).resolve())
            with self._path_line(canonical):
                with self._lock: host = self._hosts.get(canonical)
                if host: host.close()
                with self._lock:
                    self._write_index([dict(p) for p in self._projects if p['id'] != project_id])
                    self._hosts.pop(canonical, None)
                    self._offline.pop(project_id, None)
            return {'removed': True, 'directoryDeleted': False}

    def close(self):
        with self._lock:
            for host in self._hosts.values():
                host.close()
            self._hosts.clear()
            if self._simulated:
                self._simulated.close()
                self._simulated = None


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

    @routes.post('/projects/{project_id}/relocate')
    def relocate_project(project_id: str, body: ProjectPath):
        return invoke(workbench.relocate, project_id, body.path)

    @routes.delete('/projects/{project_id}')
    def remove_project(project_id: str):
        return invoke(workbench.remove, project_id)

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

    @routes.post('/projects/{project_id}/tasks/{task_id}/decisions/{decision_id}')
    def answer_decision(project_id: str, task_id: str, decision_id: str, body: DecisionAnswer):
        return invoke(workbench.call, project_id, 'task.answer', taskId=task_id, decisionId=decision_id, answer=body.answer)

    @routes.post('/projects/{project_id}/tasks/{task_id}/continue')
    def continue_task(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'task.continue', taskId=task_id)

    @routes.get('/simulated-executor')
    def simulated_executor_status():
        return workbench.simulated().info()

    @routes.get('/projects/{project_id}/resources/skills')
    def list_skills(project_id: str):
        return invoke(workbench.call, project_id, 'skills.list')

    @routes.get('/model-configs')
    def model_configs():
        return invoke(workbench.model_configuration.list)

    @routes.post('/model-configs', status_code=201)
    def save_model_config(values: dict):
        return invoke(workbench.model_configuration.save, values)

    @routes.post('/model-configs/{configuration_id}/verify')
    def verify_model_config(configuration_id: str):
        return invoke(workbench.model_configuration.verify, configuration_id)

    @routes.delete('/model-configs/{configuration_id}')
    def delete_model_config(configuration_id: str):
        return invoke(workbench.model_configuration.delete, configuration_id)

    @routes.put('/projects/{project_id}/conversations/{conversation_id}/model')
    def select_model(project_id: str, conversation_id: str, values: dict):
        identity = values.get('configurationId')
        if identity is not None and identity not in [item['id'] for item in workbench.model_configuration.list()]:
            raise HTTPException(409, '模型未配置，未切换接收方')
        return invoke(workbench.call, project_id, 'conversation.model', conversationId=conversation_id, configurationId=identity)

    @routes.post('/projects/{project_id}/tasks/{task_id}/reconcile')
    def reconcile_science(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'science.reconcile', taskId=task_id)

    @routes.post('/projects/{project_id}/tasks/{task_id}/external/reconcile')
    def reconcile_external(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'external.reconcile', taskId=task_id)

    @routes.post('/projects/{project_id}/tasks/{task_id}/external/cancel')
    def cancel_external(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'external.cancel', taskId=task_id)

    @routes.post('/projects/{project_id}/tasks/{task_id}/pause')
    def pause_task(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'task.pause', taskId=task_id)

    @routes.post('/projects/{project_id}/tasks/{task_id}/resume')
    def resume_task(project_id: str, task_id: str):
        return invoke(workbench.call, project_id, 'task.resume', taskId=task_id)

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
