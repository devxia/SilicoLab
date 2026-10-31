"""Build an artificial complete project with the actual prior public release.

Uses only a fixed Git commit, offline npm cache and the explicitly built analysis
runtime; no user credentials or real scientific/provider endpoints.
"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

BASE='c6052b4ca46baafd5486764c01755ac18a816a75'
CHILD=r'''
import base64,json,sys,time
from pathlib import Path
from fastapi.testclient import TestClient
from app_fixture import create_app
from test_model_configuration import MemorySecrets,FakeModelEndpoint
from test_workbench_science import wait_task
from test_workbench_recovery import wait_state
project=Path(sys.argv[1]);app=Path(sys.argv[2]);out=Path(sys.argv[3])
with FakeModelEndpoint('openai-responses','artificial-archive-key') as endpoint,TestClient(create_app(app,delay=0,credential_store=MemorySecrets())) as client:
 opened=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+opened['id']
 chat=client.post(url+'/conversations',json={'title':'真实旧版本模型来源'}).json()['id']
 config=client.post('/api/workbench/model-configs',json={'name':'artificial archived provider','protocol':'openai-responses','baseUrl':endpoint.url,'modelId':'artificial','apiKey':'artificial-archive-key'}).json()
 client.put(url+f'/conversations/{chat}/model',json={'configurationId':config['id']})
 client.put(url+f'/conversations/{chat}/draft',json={'text':'旧版本已保存草稿','revision':0})
 task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'old-model','goal':'ABC','authorizedTools':['synthetic_count']}).json();wait_task(client,url,chat,task['id'])
 science=client.post(url+'/conversations',json={'title':'旧版科学与脚本产物'}).json()['id']
 for name,content,workflow,extras in [('old.fasta',b'>old\nK*\n','d2p_local',{'specialtyAcknowledged':True,'parameters':{'stopPolicy':'preserve','avoid':''}}),('old.csv',b'value\n1\n2\n3\n','python_analysis',{})]:
  file=client.post(url+'/files',json={'name':name,'contentBase64':base64.b64encode(content).decode()}).json()
  version=client.post(url+'/input-versions',json={'conversationId':science,'fileIds':[file['id']]}).json()
  task=client.post(url+'/tasks',json={'conversationId':science,'requestId':workflow,'goal':'明确人工本地科学与分析','workflow':workflow,'inputVersionId':version['id'],'authorizedTools':[workflow],**extras}).json();done=wait_task(client,url,science,task['id'])
  assert done['toolExecutions'][0]['status']=='completed',done
 waiting=client.post(url+'/tasks',json={'conversationId':science,'requestId':'old-waiting','goal':'保留必要决定','authorizedTools':[]}).json()
 held=client.post(url+'/tasks',json={'conversationId':science,'requestId':'old-paused','goal':'ABC'*1000,'authorizedTools':['synthetic_count']}).json()
 client.post(url+f'/tasks/{held["id"]}/pause')
 result={'project':client.get(url).json(),'chats':{c['id']:client.get(url+'/conversations/'+c['id']).json() for c in client.get(url).json()['conversations']},'pausedTaskId':held['id'],'waitingTaskId':waiting['id']}
 out.write_text(json.dumps(result,ensure_ascii=False))
'''


def create_previous_project(project):
    project=Path(project);project.mkdir()
    source=subprocess.check_output(['git','archive',BASE,'backend/src','backend/tests','runtime/src','runtime/package.json','runtime/package-lock.json'])
    with tempfile.TemporaryDirectory(prefix='silicolab-prior-archive-fixture-') as directory:
        root=Path(directory).resolve()
        with tarfile.open(fileobj=io.BytesIO(source)) as archive:archive.extractall(root,filter='data')
        empty=root/'empty-user.npmrc';empty.touch();global_config=root/'empty-global.npmrc';global_config.touch()
        env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','LANG')}
        subprocess.run(['npm','ci','--offline','--ignore-scripts','--no-audit','--no-fund','--userconfig='+str(empty),'--globalconfig='+str(global_config)],cwd=root/'runtime',env=env,check=True,capture_output=True,timeout=60)
        runtime=Path('release/PythonBoundaryProbe.app').resolve();manifest=runtime.parent/'PythonBoundaryProbe-manifest.json'
        if not runtime.is_dir() or not manifest.is_file():raise AssertionError('Previous-release analysis fixture requires explicitly built independent runtime')
        (root/'release').mkdir();shutil.copytree(runtime,root/'release'/runtime.name,symlinks=True);shutil.copy2(manifest,root/'release'/manifest.name)
        env['PYTHONPATH']=os.pathsep.join([str(root/'backend/tests'),str(root/'backend/src')]);env['SILICOLAB_SCIENCE_REMOTE']='http://127.0.0.1:9/never'
        output=root/'result.json'
        completed=subprocess.run([sys.executable,'-B','-c',CHILD,str(project),str(root/'app.sqlite3'),str(output)],cwd=root,env=env,capture_output=True,text=True,timeout=90)
        if completed.returncode:raise AssertionError('Artificial prior-release fixture failed: '+completed.stderr)
        return json.loads(output.read_text())
