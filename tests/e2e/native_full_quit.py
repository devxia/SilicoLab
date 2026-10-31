"""Real native full quit stops sandbox/owners, new service exposes only selected recovery."""
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from urllib.request import Request,urlopen
from Quartz import CGWindowListCopyWindowInfo,kCGWindowListOptionOnScreenOnly,kCGNullWindowID
from silicolab.desktop_lifecycle import ensure_service,service_info,stop_service,gui_command
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend/tests'))
from test_model_configuration import FakeModelEndpoint
from test_restricted_analysis import SCRIPT

OUT=Path('outputs/native/full-quit');OUT.mkdir(parents=True,exist_ok=True)

def wait(fn,seconds=25):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=fn()
        if result:return result
        time.sleep(.03)
    raise AssertionError('Native full quit condition timed out')

with tempfile.TemporaryDirectory(prefix='silicolab-native-quit-') as directory,FakeModelEndpoint('openai-responses','artificial-native-quit',tool_name='python_analysis',tool_arguments={'code':'import time;time.sleep(7)\n'+SCRIPT}) as model:
    root=Path(directory);env={**os.environ,'SILICOLAB_APP_DATA':directory,'SILICOLAB_NATIVE_EVIDENCE':str(root/'evidence.json')}
    python=str(Path('.desktop-venv/bin/python').absolute());driver=str(Path('tests/e2e/fixtures/native_window_driver.py').absolute())
    processes=[];log=(root/'gui.log').open('ab');config=None;origin=None
    def api(path,body=None,method=None):
        request=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=15) as response:return json.load(response)
    def launch(prepare):
        process=subprocess.Popen([python,'-B',driver],cwd='/tmp',env=dict(env,SILICOLAB_NATIVE_PREPARE_SELECTION='1' if prepare else '0'),stdout=log,stderr=log);processes.append(process)
        wait(lambda:(root/'gui-session.json').exists() and process.poll() is None)
        return process
    try:
        info=ensure_service(root,isolated_resources=True);origin=info['origin']
        paths=[root/'A',root/'B']
        for path in paths:path.mkdir()
        projects=[api('/projects',{'path':str(path),'name':'native close evidence' if i==0 else 'other waiting project'}) for i,path in enumerate(paths)]
        url='/projects/'+projects[0]['id'];other='/projects/'+projects[1]['id']
        api(url+'/conversations',{'title':'decoy first'})
        chat=api(url+'/conversations',{'title':'same background task'})['id'];env['SILICOLAB_NATIVE_TARGET_CHAT']=chat
        config=api('/model-configs',{'name':'temporary native quit','protocol':model.protocol,'baseUrl':model.url,'modelId':'artificial-model','apiKey':model.key})
        api(url+f'/conversations/{chat}/model',{'configurationId':config['id']},'PUT')
        source=api(url+'/files',{'name':'artificial.csv','contentBase64':base64.b64encode(b'value\n1\n2\n6\n').decode()})
        fixed=api(url+'/input-versions',{'conversationId':chat,'fileIds':[source['id']]})
        running=api(url+'/tasks',{'conversationId':chat,'requestId':'native-quit-script','workflow':'python_analysis','inputVersionId':fixed['id'],'goal':'人工临时分析','authorizedTools':['python_analysis']})
        queued=api(url+'/tasks',{'conversationId':chat,'requestId':'native-quit-queue','goal':'ABC','authorizedTools':['synthetic_count']})
        second_chat=api(other+'/conversations',{'title':'waiting'})['id']
        waiting=api(other+'/tasks',{'conversationId':second_chat,'requestId':'native-quit-wait','goal':'need permission','authorizedTools':[]})
        gui=launch(True)
        wait(lambda:(root/'evidence.json').exists())
        active=wait(lambda:next((t for t in api(url)['tasks'] if t['id']==running['id'] and t['toolExecutions'] and t['toolExecutions'][0].get('pythonPid')),None))
        script_pid=active['toolExecutions'][0]['pythonPid']
        quit_result=subprocess.run([python,'-B','-m','silicolab.desktop','--quit'],cwd='/tmp',env=env,stdout=log,stderr=log,timeout=20)
        assert quit_result.returncode==0
        gui.wait(timeout=15)
        assert not [w for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly,kCGNullWindowID) if w.get('kCGWindowOwnerPID')==gui.pid and w.get('kCGWindowLayer')==0]
        assert service_info(root) is None
        for pid in [script_pid,*[p['runtimePid'] for p in projects]]:
            try:os.kill(pid,0)
            except ProcessLookupError:pass
            else:raise AssertionError('Full quit left a managed process alive')
        requests=len(model.requests)
        (root/'evidence.json').unlink(missing_ok=True)
        reopened=launch(False)
        replacement=wait(lambda:service_info(root));origin=replacement['origin']
        wait(lambda:(root/'evidence.json').exists())
        snapshot=api(url)
        assert [t['status'] for t in snapshot['tasks']]==['paused','paused']
        assert api(other)['tasks'][0]['decisions']==waiting['decisions']
        assert json.loads((root/'workbench-selection.json').read_text())['conversationId']==chat
        time.sleep(.2);assert len(model.requests)==requests
        api(url+f'/conversations/{chat}/model',{'configurationId':None},'PUT')
        api(url+f'/tasks/{queued["id"]}/resume',{},'POST')
        done=wait(lambda:next((t for t in api(url)['tasks'] if t['id']==queued['id'] and t['status']=='answered'),None))
        assert done['toolExecutions'][0]['result']['characters']==3
        assert api(url)['tasks'][0]['status']=='paused'
        assert api(other)['tasks'][0]['status']=='needs_decision'
        assert len(model.requests)==requests
        report={'result':'passed','real_cocoa_full_quit':True,'sandbox_and_nodes_reaped':True,'relaunch_no_auto_execution':True,'same_nonfirst_chat':True,'queued_task_selected_only':True,'waiting_decision_unchanged':True,'system_reboot_scenario':'all managed owners stopped, fresh service, persisted projects; OS not rebooted','artificial_data_only':True}
        (OUT/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        log.flush()
        if any(process.poll() is None for process in processes):
            for name in ('gui.log','desktop.log','background-launch.log'):
                if (root/name).exists(): print(name,(root/name).read_text(errors='replace')[-5000:])
        if config and service_info(root):
            origin=service_info(root)['origin']
            try:api('/model-configs/'+config['id'],method='DELETE')
            except Exception:pass
        if config:
            from silicolab.model_configuration import KeychainSecrets
            KeychainSecrets().delete(config['id'])
        try:stop_service(root)
        except Exception:pass
        gui_command(root,'close')
        for process in processes:
            if process.poll() is None:
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
