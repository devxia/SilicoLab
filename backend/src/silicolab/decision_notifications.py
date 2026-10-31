"""Application-owned, privacy-minimal pending-decision notifications.

Only an explicit user action requests OS permission. The durable task/decision is
always the source of truth; macOS delivery is advisory and may be refused.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

from silicolab.desktop_lifecycle import atomic_json

TITLE='SilicoLab 需要你的决定'
BODY='一个任务已保存待处理问题。打开原任务查看并答复；任务没有自动继续。'


def valid_target(value):
    if not isinstance(value,dict) or set(value)!={'projectId','conversationId','taskId','decisionId'}:return False
    try:
        for key in ('projectId','taskId','decisionId'):uuid.UUID(value[key])
    except (ValueError,TypeError,AttributeError):return False
    chat=value['conversationId']
    return isinstance(chat,str) and chat.isascii() and chat.isdigit() and len(chat)<=30


def helper_app():
    if getattr(sys,'frozen',False):return Path(sys._MEIPASS)/'notifications/SilicoLabNotifications.app'
    return Path(__file__).resolve().parents[3]/'release/SilicoLabNotifications.app'


class NotificationTransportError(OSError):pass


class NativeNotifications:
    def __init__(self,selected):
        app=helper_app();manifest=app.with_name(app.stem+'-manifest.json')
        try:inventory=json.loads(manifest.read_text())
        except (OSError,ValueError):raise ValueError('原生通知组件未预装；应用待处理项仍可使用') from None
        if inventory.get('bundleId')!='com.silicolab.notifications':raise ValueError('原生通知组件身份不符')
        for name,expected in inventory['files'].items():
            path=app/name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('原生通知组件完整性不符')
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True,timeout=10)
        self.pending={};self.lock=threading.Lock();self.serial=threading.Lock();self.selected=selected
        self.process=subprocess.Popen([str(app/'Contents/MacOS/SilicoLabNotifications')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,close_fds=True,env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8'})
        self.ready=threading.Event();self.handshake=False;self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        if not self.ready.wait(5) or not self.handshake:self.close();raise ValueError('原生通知组件未就绪')
    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line)>65536:break
                message=json.loads(line)
                if message.get('event')=='ready' and message.get('bundleId')=='com.silicolab.notifications':self.handshake=True;self.ready.set()
                elif message.get('event')=='selected' and valid_target(message.get('target')):
                    threading.Thread(target=self.selected,args=(message['target'],),daemon=True).start()
                else:
                    with self.lock:pending=self.pending.get(message.get('id'))
                    if pending:pending.put(message)
        finally:
            self.ready.set()
            with self.lock:waiting=list(self.pending.values())
            for pending in waiting:
                try:pending.put_nowait({'transportLost':True})
                except queue.Full:pass
    def call(self,op,**values):
        with self.serial:
            identity=str(uuid.uuid4());result=queue.Queue(maxsize=1)
            with self.lock:self.pending[identity]=result
            try:
                self.process.stdin.write(json.dumps({'id':identity,'op':op,**values})+'\n');self.process.stdin.flush()
                response=result.get(timeout=60 if op=='enable' else 8)
                if response.get('transportLost'):raise NotificationTransportError('原生通知连接已关闭')
                if response.get('error'):raise ValueError('原生通知操作未确认；应用待处理项仍保留')
                return response
            except (OSError,queue.Empty):raise NotificationTransportError('原生通知连接失败；应用待处理项仍保留') from None
            finally:
                with self.lock:self.pending.pop(identity,None)
    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        self.reader.join(timeout=2)
        self.process.stdout.close()


class DecisionNotifications:
    def __init__(self,workbench,directory,center_factory=NativeNotifications,activate=None):
        self.workbench=workbench;self.directory=Path(directory);self.path=self.directory/'notification-state.json'
        self.factory=center_factory;self.activate=activate or self._activate;self.center=None;self.lock=threading.RLock();self.stop=threading.Event();self.thread=None
        try:
            state=json.loads(self.path.read_text())
            if not isinstance(state,dict) or type(state.get('enabled')) is not bool or not isinstance(state.get('sent'),dict):raise ValueError()
            self.state=state
        except FileNotFoundError:self.state={'enabled':False,'sent':{}}
        except (OSError,ValueError):self.state={'enabled':False,'sent':{},'error':'通知设置损坏；未请求权限，待处理项仍保留'}
    def _save(self):atomic_json(self.path,self.state)
    def _center(self):
        if self.center is None:self.center=self.factory(self.selected)
        return self.center
    def _call(self,op,**values):
        center=self._center()
        try:return center.call(op,**values)
        except OSError:
            try:center.close()
            finally:self.center=None
            raise
    def pending(self):
        found=[]
        for snapshot in self.workbench.notification_snapshots():
            for task in snapshot['tasks']:
                for decision in task.get('decisions',[]):
                    if decision['status']=='pending':
                        target={'projectId':snapshot['id'],'conversationId':task['conversationId'],'taskId':task['id'],'decisionId':decision['id']}
                        if valid_target(target):found.append(target)
        return found
    def selected(self,target):
        if not valid_target(target):return False
        try:
            snapshot=self.workbench.call(target['projectId'],'status')
            task=next((task for task in snapshot['tasks'] if task['id']==target['taskId'] and task['conversationId']==target['conversationId']),None)
            if not task or not any(d['id']==target['decisionId'] and d['status']=='pending' for d in task.get('decisions',[])):return False
            with self.lock:self.state['selection']=target;self._save()
            self.activate(target)
            return True
        except (OSError,ValueError):return False
    def _activate(self,target):
        from silicolab.desktop_lifecycle import gui_command
        if gui_command(self.directory,'show'):return
        command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-B','-m','silicolab.desktop']
        env={k:os.environ[k] for k in ('PATH','LANG','SSL_CERT_FILE','SILICOLAB_RUNTIME','SILICOLAB_NODE','SILICOLAB_FRONTEND_DIST') if k in os.environ};env['SILICOLAB_APP_DATA']=str(self.directory)
        with (self.directory/'notification-window.log').open('ab') as log:
            child=subprocess.Popen(command,cwd='/',env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,start_new_session=True)
        threading.Thread(target=child.wait,daemon=True).start()
    def status(self):
        with self.lock:
            result={'enabled':self.state['enabled'],'authorization':'not_requested','pending':len(self.pending()),'error':self.state.get('error')}
            if self.center:
                try:
                    status=self._call('status');result['authorization']={0:'not_requested',1:'denied',2:'authorized',3:'provisional',4:'ephemeral'}.get(status.get('authorization'),'unknown')
                    result['delivered']=len(status.get('delivered',[]));result['nativePid']=getattr(getattr(self.center,'process',None),'pid',None)
                except (OSError,ValueError):result['authorization']='unavailable'
            return result
    def configure(self,enabled):
        if type(enabled) is not bool:raise ValueError('通知设置必须为明确布尔值')
        with self.lock:
            if enabled:
                response=self._call('enable',explicitUserEnabled=True)
                self.state['enabled']=True
                self.state['authorization']='authorized' if response.get('granted') else 'denied'
            else:
                self.state['enabled']=False
                self._save()
                self._call('disable')
            self._save()
        self.scan()
        return self.status()
    def consume(self):
        # Read without consuming: only a successful UI navigation acknowledges it.
        with self.lock:selected=self.state.get('selection')
        return selected
    def acknowledge(self,target):
        if not valid_target(target):raise ValueError('通知定位身份不合法')
        with self.lock:
            if self.state.get('selection')!=target:return {'acknowledged':False}
            self.state.pop('selection');self._save()
        return {'acknowledged':True}
    def scan(self):
        with self.lock:
            if not self.state['enabled']:return
            try:
                settings=self._call('status')
                if settings.get('authorization') not in (2,3,4):self.state['authorization']='denied';self._save();return
                current=self.pending();identities={t['decisionId'] for t in current}
                obsolete=[identity for identity in self.state['sent'] if identity not in identities and self.state['sent'][identity]!='cleared']
                for offset in range(0,len(obsolete),200):
                    batch=obsolete[offset:offset+200]
                    self._call('remove',identifiers=['silicolab-decision-'+i for i in batch])
                    self.state['sent'].update({i:'cleared' for i in batch});self._save()
                for target in current:
                    identity=target['decisionId']
                    if identity in self.state['sent']:continue
                    # Persist admission before submission: never duplicate after crash/reconnect.
                    self.state['sent'][identity]='admitted';self._save()
                    result=self._call('notify',target=target)
                    self.state['sent'][identity]='submitted' if result.get('submitted') else 'unconfirmed';self._save()
                self.state.pop('error',None)
            except (OSError,ValueError,subprocess.SubprocessError):self.state['error']='系统提醒未确认；请在应用待处理项查看，不影响任务保存';self._save()
    def start(self):
        def loop():
            while not self.stop.wait(1):self.scan()
        self.thread=threading.Thread(target=loop,name='silicolab-decision-notifications',daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=70)
        if self.center:
            try:self.center.call('disable')
            except (ValueError,OSError):pass
            self.center.close()
