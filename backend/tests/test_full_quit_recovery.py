"""Explicit quit of actual generated analysis, queue, user wait, and another project."""
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

from silicolab.desktop_lifecycle import ensure_service, service_info, stop_service
from test_model_configuration import FakeModelEndpoint
from test_restricted_analysis import RUNTIME_APP, SCRIPT


@unittest.skipUnless(RUNTIME_APP.exists(), 'Build the verified analysis runtime before quit/recovery integration')
class FullQuitRecoveryTests(unittest.TestCase):
    def test_separate_executor_survives_quit_and_only_explicit_operation_cancels(self):
        import subprocess
        import sys
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=Path(__file__).resolve().parents[2]
            executor=subprocess.Popen([sys.executable,'-B',str(repo/'tests/e2e/fixtures/independent_executor.py'),str(root)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            service=None
            env={**os.environ,'SILICOLAB_APP_DATA':str(root),'SILICOLAB_ARTIFICIAL_EXECUTOR':str(root/'independent-executor.json')}
            def wait(fn):
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    value=fn()
                    if value:return value
                    time.sleep(.03)
                self.fail('independent executor state timeout')
            def start():
                nonlocal service
                service=subprocess.Popen([sys.executable,'-B',str(repo/'tests/e2e/fixtures/quit_service_fixture.py')],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return wait(lambda:service_info(root))['origin']
            def api(path,body=None):
                req=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=10) as r:return json.load(r)
            try:
                wait(lambda:(root/'independent-executor.json').exists())
                external=json.loads((root/'independent-executor.json').read_text())
                def find(key):
                    with urlopen(external['url']+'/find?'+urlencode({'requestKey':key}),timeout=3) as r:return json.load(r)
                origin=start();project=root/'project';project.mkdir()
                p=api('/projects',{'path':str(project)})
                url='/projects/'+p['id'];chat=api(url+'/conversations',{'title':'independent jobs'})['id']
                tasks=[]
                for i,duration in enumerate((1500,30000)):
                    tasks.append(api(url+'/tasks',{'conversationId':chat,'requestId':f'external-{i}','goal':'independent artificial executor','workflow':'simulated_external','authorizedTools':['simulated_external'],'simulation':{'payload':'ABC','durationMs':duration,'queryable':True,'responseMode':'normal'}}))
                keys=[t['externalJob']['requestKey'] for t in tasks]
                api(url+f'/tasks/{tasks[1]["id"]}/pause',{})
                self.assertEqual(find(keys[1])['state'],'running')
                stop_service(root);service.wait(timeout=10)
                self.assertIsNone(executor.poll())
                self.assertEqual(wait(lambda:(value if (value:=find(keys[0]))['state']=='succeeded' else None))['jobId'],tasks[0]['externalJob']['jobId'])
                self.assertEqual(find(keys[1])['state'],'running')
                origin=start()
                opened=api('/projects/open',{'path':str(project)})
                self.assertEqual(opened['tasks'][0]['id'],tasks[0]['id'])
                self.assertEqual(api(url+f'/tasks/{tasks[0]["id"]}/external/reconcile',{})['status'],'answered')
                self.assertEqual(api(url+f'/tasks/{tasks[1]["id"]}/external/cancel',{})['externalJob']['state'],'cancelled')
                self.assertEqual(find(keys[1])['state'],'cancelled')
                with urlopen(external['url']+'/info') as r:info=json.load(r)
                self.assertTrue(all(j['submit_attempts']==1 for j in info['jobs']))
                self.assertEqual(info['createdJobs'],2)
            finally:
                stop_service(root)
                if service:service.wait(timeout=10)
                executor.stdin.close();executor.wait(timeout=10)

    def test_full_quit_stops_analysis_and_queue_and_preserves_waiting_then_selects_one_task(self):
        with tempfile.TemporaryDirectory() as directory,FakeModelEndpoint('openai-responses','artificial-quit-analysis',tool_name='python_analysis',tool_arguments={'code':'import time;time.sleep(3)\n'+SCRIPT}) as model:
            root=Path(directory);info=ensure_service(root,isolated_resources=True);origin=info['origin']
            def api(path,body=None,method=None):
                request=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=12) as response:return json.load(response)
            def wait(predicate):
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    result=predicate()
                    if result:return result
                    time.sleep(.02)
                self.fail('quit/recovery state timed out')
            projects=[];nodes=[];cfg=None
            try:
                for name in ('A','B'):
                    path=root/name;path.mkdir()
                    project=api('/projects',{'path':str(path),'name':name});projects.append(project);nodes.append(project['runtimePid'])
                first='/projects/'+projects[0]['id'];second='/projects/'+projects[1]['id']
                chat=api(first+'/conversations',{'title':'analysis and queue'})['id']
                csv=api(first+'/files',{'name':'artificial.csv','contentBase64':base64.b64encode(b'value\n1\n2\n6\n').decode()})
                fixed=api(first+'/input-versions',{'conversationId':chat,'fileIds':[csv['id']]})
                cfg=api('/model-configs',{'name':'artificial quit model','protocol':model.protocol,'baseUrl':model.url,'modelId':'artificial-model','apiKey':model.key})
                api(first+f'/conversations/{chat}/model',{'configurationId':cfg['id']},'PUT')
                running=api(first+'/tasks',{'conversationId':chat,'requestId':'quit-analysis','goal':'temporary numeric analysis','workflow':'python_analysis','inputVersionId':fixed['id'],'authorizedTools':['python_analysis']})
                queued=api(first+'/tasks',{'conversationId':chat,'requestId':'quit-queued','goal':'queued artificial text','authorizedTools':['synthetic_count']})
                other_chat=api(second+'/conversations',{'title':'waiting decision'})['id']
                waiting=api(second+'/tasks',{'conversationId':other_chat,'requestId':'quit-wait','goal':'need explicit tool decision','authorizedTools':[]})
                self.assertEqual(waiting['status'],'needs_decision')
                pending=wait(lambda:next((t for t in api(first)['tasks'] if t['id']==running['id'] and t['toolExecutions'] and t['toolExecutions'][0].get('pythonPid')),None))
                pid=pending['toolExecutions'][0]['pythonPid']
                self.assertEqual(api(first)['tasks'][1]['status'],'queued')
                stop_service(root)
                self.assertIsNone(service_info(root))
                for child in nodes+[pid]:
                    with self.assertRaises(ProcessLookupError):os.kill(child,0)
                requests=len(model.requests);time.sleep(.15);self.assertEqual(len(model.requests),requests)
                # All app owners are gone; a fresh service reads only persisted state (reboot-recovery scenario).
                info2=ensure_service(root,isolated_resources=True);origin=info2['origin']
                self.assertNotEqual(info2['serviceId'],info['serviceId'])
                restored=api('/projects/open',{'path':str(root/'A')})
                other=api('/projects/open',{'path':str(root/'B')})
                self.assertEqual([t['status'] for t in restored['tasks']],['paused','paused'])
                self.assertEqual(restored['tasks'][0]['id'],running['id'])
                self.assertEqual(other['tasks'][0]['decisions'],waiting['decisions'])
                self.assertEqual(other['tasks'][0]['status'],'needs_decision')
                time.sleep(.15);self.assertEqual(len(model.requests),requests)
                # Select only the queued text task; neither analysis nor other project's wait is awakened.
                api(first+f'/conversations/{chat}/model',{'configurationId':None},'PUT')
                api(first+f'/tasks/{queued["id"]}/resume',{},'POST')
                finished=wait(lambda:next((t for t in api(first)['tasks'] if t['id']==queued['id'] and t['status']=='answered'),None))
                self.assertEqual(finished['toolExecutions'][0]['result']['characters'],len('queued artificial text'))
                self.assertEqual(api(first)['tasks'][0]['status'],'paused')
                self.assertEqual(api(second)['tasks'][0]['status'],'needs_decision')
                self.assertEqual(len(model.requests),requests)
                api(first+f'/tasks/{running["id"]}/resume',{},'POST')
                complete=wait(lambda:next((t for t in api(first)['tasks'] if t['id']==running['id'] and t['status']=='answered'),None))
                self.assertEqual(complete['toolExecutions'][-1]['result']['summary']['mean'],3)
                self.assertEqual(len(complete['toolExecutions']),2)
                before=complete['toolExecutions']
                self.assertEqual(api(first+f'/tasks/{running["id"]}/resume',{},'POST')['toolExecutions'],before)
            finally:
                stop_service(root)
                if cfg:
                    from silicolab.model_configuration import KeychainSecrets
                    KeychainSecrets().delete(cfg['id'])


if __name__=='__main__':unittest.main()
