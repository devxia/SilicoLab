"""Acceptance tooling must not promote simulated evidence or dispatch without approval."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]/'tools/provider-compatibility/verify.py'
spec=importlib.util.spec_from_file_location('provider_acceptance',SOURCE)
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)
import sys
sys.modules['silicolab_acceptance']=acceptance
error_spec=importlib.util.spec_from_file_location('provider_errors',SOURCE.with_name('verify_errors.py'))
error_probe=importlib.util.module_from_spec(error_spec);error_spec.loader.exec_module(error_probe)


def configurations():
    return [{'id':'11111111-1111-4111-8111-111111111111','protocol':'openai-responses','baseUrl':'https://responses.example.invalid/v1','modelId':'artificial-response-model','hasKey':True},
            {'id':'22222222-2222-4222-8222-222222222222','protocol':'anthropic-messages','baseUrl':'https://messages.example.invalid','modelId':'artificial-message-model','hasKey':True}]


class ProviderAcceptanceTests(unittest.TestCase):
    def test_plan_is_metadata_only_pins_receivers_and_missing_keys_cannot_execute(self):
        rows=configurations();rows[0]['apiKey']='PRIVATE_ARTIFICIAL_SENTINEL'
        plan=acceptance.build_plan(rows,[row['id'] for row in rows])
        self.assertNotIn('PRIVATE_ARTIFICIAL',json.dumps(plan));self.assertNotIn('apiKey',json.dumps(plan))
        self.assertEqual(plan['protocols'],['openai-responses','anthropic-messages'])
        self.assertEqual(plan['inputSha256'],acceptance.sha256(acceptance.ARTIFICIAL_CSV))
        changed=configurations();changed[0]['modelId']='different'
        self.assertNotEqual(plan['digest'],acceptance.build_plan(changed,[row['id'] for row in changed])['digest'])
        from unittest.mock import patch
        with patch.object(acceptance,'source_identity',return_value={'sha256':'f'*64,'files':1}):
            self.assertNotEqual(plan['digest'],acceptance.build_plan(configurations(),[r['id'] for r in configurations()])['digest'])
        rows[1]['hasKey']=False
        with self.assertRaisesRegex(ValueError,'key'):acceptance.build_plan(rows,[row['id'] for row in rows])

    def test_real_local_gateway_requires_explicit_plan_scope_and_never_promotes_fixture(self):
        rows=configurations()
        for row in rows:row['baseUrl']='http://127.0.0.1:3425'+('/v1' if row['protocol']=='openai-responses' else '')
        ids=[row['id'] for row in rows]
        with self.assertRaisesRegex(ValueError,'回环'):acceptance.build_plan(rows,ids)
        approved=acceptance.build_plan(rows,ids,allow_local_gateway=True)
        self.assertTrue(approved['allowLocalGateway']);self.assertEqual(approved['evidenceKind'],'real')
        fixture=acceptance.build_plan(rows,ids,evidence_kind='fixture',allow_local_gateway=True)
        self.assertEqual(fixture['evidenceKind'],'fixture');self.assertNotEqual(approved['digest'],fixture['digest'])
        self.assertIn('上游',approved['limits'])
        rows[0]['baseUrl']='http://remote.example.invalid/v1'
        with self.assertRaises(ValueError):acceptance.build_plan(rows,ids,allow_local_gateway=True)

    def test_authorization_failure_performs_no_writes_or_provider_requests(self):
        class NoWrites:
            def request(self,*args,**kwargs):raise AssertionError('must reject before application side effects')
        rows=configurations();plan=acceptance.build_plan(rows,[row['id'] for row in rows])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'授权'):
                acceptance.run_suite(NoWrites(),plan,Path(directory),'wrong-digest')
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_receipt_requires_actual_output_and_streaming_and_never_calls_fixture_real(self):
        config=configurations()[0]
        task={'id':'artificial-task','status':'answered','modelRequests':[{'id':'r','configurationId':config['id'],'protocol':config['protocol'],'endpoint':config['baseUrl'],'model':config['modelId'],'status':'completed','parameters':{'transport':'sse'},'usage':{'input':4,'output':3,'cacheRead':None,'cacheWrite':None}}],
              'toolExecutions':[{'id':'exec','tool':'python_analysis','status':'completed','result':{'checks':{'independent_numeric_summary':True},'summary':{'count':3,'sum':9.0,'mean':3.0}},'artifacts':[{'name':'summary.json','sha256':'a'*64},{'name':'summary.xlsx','sha256':'b'*64},{'name':'analysis.py','sha256':'c'*64}]}]}
        state={'entries':[{'model':[{'role':'assistant','content':[{'type':'text','text':'summary.json 与 summary.xlsx：count=3, sum=9, mean=3'}]}]}]}
        receipt=acceptance.science_receipt(task,state,config,{'distinctPartials':2},evidence_kind='fixture')
        self.assertTrue(receipt['checks']['toolAndArtifacts']);self.assertFalse(receipt['realCompatibilityPassed'])
        task['toolExecutions'][0]['result']['summary']['sum']=10
        receipt=acceptance.science_receipt(task,state,config,{'distinctPartials':1},evidence_kind='real')
        self.assertFalse(receipt['checks']['toolAndArtifacts']);self.assertFalse(receipt['checks']['streaming']);self.assertFalse(receipt['realCompatibilityPassed'])

    @unittest.skipUnless((SOURCE.parents[2]/'release/PythonBoundaryProbe.app').exists(),'Build the independent analysis runtime first')
    def test_entire_runner_uses_real_app_kernel_and_python_but_marks_loopback_evidence_fixture(self):
        import socket
        import threading
        import time
        import uvicorn
        from app_fixture import create_app
        from test_model_configuration import MemorySecrets
        from provider_acceptance_fixture import AcceptanceEndpoint
        with tempfile.TemporaryDirectory() as directory,AcceptanceEndpoint('openai-responses') as responses,AcceptanceEndpoint('anthropic-messages') as messages:
            root=Path(directory);app=create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(64)
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',loop='asyncio',ws='none'))
            thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
            deadline=time.monotonic()+5
            while not server.started and time.monotonic()<deadline:time.sleep(.02)
            client=acceptance.Application('http://127.0.0.1:'+str(listener.getsockname()[1]))
            try:
                configs=[client.request('/model-configs',{'name':'artificial acceptance','protocol':e.protocol,'baseUrl':e.url,'modelId':'artificial-model','apiKey':e.key}) for e in (responses,messages)]
                plan=acceptance.build_plan(configs,[c['id'] for c in configs],evidence_kind='fixture')
                self.assertEqual(responses.requests+messages.requests,[])
                report=acceptance.run_suite(client,plan,root/'output',plan['digest'])
                self.assertEqual(len(report['cases']),8)
                self.assertTrue(all(all(case['checks'].values()) for case in report['cases']),json.dumps(report,ensure_ascii=False))
                self.assertFalse(report['realCompatibilityPassed']);self.assertEqual(report['evidenceKind'],'fixture')
                self.assertIn('versions',json.loads((root/'output/compatibility-report.json').read_text()))
                for endpoint in (responses,messages):self.assertNotIn(endpoint.key,json.dumps(report))
                self.assertEqual(len(client.request('/model-configs')),2,'temporary invalid-key configs cleaned')
                before=client.request('/projects');project_before=client.request('/projects/'+before[0]['id'])
                error_plan=error_probe.build_plan(report)
                with self.assertRaises(ValueError):error_probe.run(client,report,error_plan,root/'not-approved','wrong')
                from unittest.mock import patch
                import copy,httpx
                original_request=client.request;original_bytes=client.bytes;changed_script=b'print("same values but changed code")\n'
                def altered_manifest(path,body=None,method=None):
                    if body is not None:raise AssertionError('changed original artifact must block all writes')
                    value=original_request(path,body,method)
                    if path=='/projects/'+before[0]['id']:
                        value=copy.deepcopy(value)
                        for artifact in value['tasks'][0]['toolExecutions'][0]['artifacts']:
                            if artifact['name']=='analysis.py':artifact['sha256']=acceptance.sha256(changed_script);artifact['size']=len(changed_script)
                    return value
                with patch.object(client,'request',side_effect=altered_manifest),patch.object(client,'bytes',side_effect=lambda path:changed_script if path.endswith('/analysis.py') and '/tasks/'+report['cases'][0]['taskId']+'/' in path else original_bytes(path)):
                    with self.assertRaisesRegex(ValueError,'原报告产物'):error_probe.run(client,report,error_plan,root/'changed',error_plan['digest'])
                for failure in ('lost-response','interrupt'):
                    def lose_created_configuration(path,body=None,method=None):
                        value=original_request(path,body,method)
                        if path=='/model-configs' and body:
                            if failure=='interrupt':raise KeyboardInterrupt()
                            raise httpx.ReadTimeout('configuration created; response lost')
                        return value
                    with patch.object(client,'request',side_effect=lose_created_configuration):
                        with self.assertRaises(KeyboardInterrupt if failure=='interrupt' else httpx.ReadTimeout):error_probe.run(client,report,error_plan,root/failure,error_plan['digest'])
                    self.assertEqual(len(client.request('/model-configs')),2,'reconcile and clean only this attempted temporary configuration')
                def stop_before_second_probe(path,body=None,method=None):
                    if path=='/model-configs' and body and body['protocol']=='anthropic-messages':raise KeyboardInterrupt()
                    return original_request(path,body,method)
                with patch.object(client,'request',side_effect=stop_before_second_probe):
                    with self.assertRaises(KeyboardInterrupt):error_probe.run(client,report,error_plan,root/'error-prefix',error_plan['digest'])
                prefix=json.loads((root/'error-prefix/error-probe-report.json').read_text());self.assertEqual(len(prefix['cases']),1)
                first_error=client.request('/projects/'+before[0]['id'])['tasks'][-1]
                continued_plan=error_probe.build_plan(report,resume_error=prefix);self.assertEqual(continued_plan['maximumTasks'],1)
                errors=error_probe.run(client,report,continued_plan,root/'errors',continued_plan['digest'],resume_error=prefix)
                self.assertEqual(client.request('/projects/'+before[0]['id'])['tasks'][-2],first_error)
                self.assertTrue(all(all(case['checks'].values()) for case in errors['cases']))
                self.assertFalse(error_probe.compatibility_passed(report,errors),'fixture never promoted')
                project_after=client.request('/projects/'+before[0]['id'])
                self.assertEqual(project_after['tasks'][:8],project_before['tasks'])
                self.assertEqual(len(client.request('/model-configs')),2)
            finally:
                client.close();server.should_exit=True;thread.join(timeout=10);listener.close()

    @unittest.skipUnless((SOURCE.parents[2]/'release/PythonBoundaryProbe.app').exists(),'Build the independent analysis runtime first')
    def test_continuation_reuses_only_a_verified_two_case_prefix_without_repeating_model_or_tool(self):
        import socket,threading,time,uvicorn,copy
        from unittest.mock import patch
        from app_fixture import create_app
        from test_model_configuration import MemorySecrets
        from provider_acceptance_fixture import AcceptanceEndpoint
        with tempfile.TemporaryDirectory() as directory,AcceptanceEndpoint('openai-responses') as responses,AcceptanceEndpoint('anthropic-messages') as messages:
            root=Path(directory);app=create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(64)
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',loop='asyncio',ws='none'));thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
            deadline=time.monotonic()+5
            while not server.started and time.monotonic()<deadline:time.sleep(.02)
            client=acceptance.Application('http://127.0.0.1:'+str(listener.getsockname()[1]))
            try:
                configs=[client.request('/model-configs',{'name':'artificial continuation','protocol':e.protocol,'baseUrl':e.url,'modelId':'artificial-model','apiKey':e.key}) for e in (responses,messages)]
                ids=[c['id'] for c in configs];plan=acceptance.build_plan(configs,ids,evidence_kind='fixture')
                with patch.object(acceptance,'references_result',return_value=False):
                    with self.assertRaises(ValueError):acceptance.run_suite(client,plan,root/'first',plan['digest'])
                prior=json.loads((root/'first/compatibility-report.json').read_text());self.assertEqual(len(prior['cases']),2)
                for case in prior['cases']:case['checks']['resultReference']=True
                continuation=acceptance.build_plan(configs,ids,evidence_kind='fixture',resume_prefix=prior)
                self.assertEqual(continuation['maximumTasks'],6);self.assertNotEqual(continuation['digest'],plan['digest'])
                project=client.request('/projects')[0];before=client.request('/projects/'+project['id'])
                # Finish the next two cases, then interrupt before sending any cancellation task.
                original_request=client.request
                def stop_after_four(path,body=None,method=None):
                    if body and path.endswith('/conversations') and '取消' in body.get('title',''):raise KeyboardInterrupt()
                    return original_request(path,body,method)
                with patch.object(client,'request',side_effect=stop_after_four):
                    with self.assertRaises(KeyboardInterrupt):acceptance.run_suite(client,continuation,root/'middle',continuation['digest'],resume_prefix=prior)
                four=json.loads((root/'middle/compatibility-report.json').read_text());self.assertEqual(len(four['cases']),4)
                next_plan=acceptance.build_plan(configs,ids,evidence_kind='fixture',resume_prefix=four);self.assertEqual(next_plan['maximumTasks'],4)
                four_before=client.request('/projects/'+project['id'])['tasks']
                report=acceptance.run_suite(client,next_plan,root/'remaining',next_plan['digest'],resume_prefix=four)
                after=client.request('/projects/'+project['id'])
                self.assertEqual(after['tasks'][:4],four_before)
                self.assertEqual(after['tasks'][:2],before['tasks']);self.assertEqual(len(after['tasks']),8)
                self.assertTrue(all(all(c['checks'].values()) for c in report['cases']));self.assertFalse(report['realCompatibilityPassed'])
                altered=copy.deepcopy(prior);altered['cases'][0]['checks']['artifactBytes']=False
                with self.assertRaises(ValueError):acceptance.build_plan(configs,ids,evidence_kind='fixture',resume_prefix=altered)
                with self.assertRaises(ValueError):acceptance.run_suite(client,continuation,root/'illegal',continuation['digest'],resume_prefix=prior)
            finally:client.close();server.should_exit=True;thread.join(timeout=10);listener.close()

    def test_prefix_and_final_verdict_reject_missing_or_nonboolean_required_evidence(self):
        import copy
        configs=configurations();ids=[c['id'] for c in configs]
        base=acceptance.build_plan(configs,ids)
        cases=[{'case':'science-openai-responses','status':'answered','checks':{k:True for k in ('completed','receiver','streaming','toolAndArtifacts','resultReference','usage','artifactBytes')}},
               {'case':'switch-openai-responses-to-anthropic-messages','status':'answered','checks':{k:True for k in ('nextReceiver','completed','historyRetained','noRepeatedPython','resultReference','artifactBytes')}}]
        prior={'plan':base,'cases':cases}
        self.assertEqual(acceptance.build_plan(configs,ids,resume_prefix=prior)['maximumTasks'],6)
        for index,key in [(0,'streaming'),(0,'usage'),(1,'historyRetained'),(1,'noRepeatedPython')]:
            for bad in ('missing',1,None,False):
                changed=copy.deepcopy(prior)
                if bad=='missing':del changed['cases'][index]['checks'][key]
                else:changed['cases'][index]['checks'][key]=bad
                with self.subTest(index=index,key=key,bad=bad),self.assertRaises(ValueError):acceptance.build_plan(configs,ids,resume_prefix=changed)
        complete={'evidenceKind':'real','cases':[{'case':name,'checks':{k:True for k in keys}} for name,keys in acceptance.CASE_CHECKS.items()]}
        self.assertTrue(acceptance.report_passed(complete))
        del complete['cases'][0]['checks']['streaming'];self.assertFalse(acceptance.report_passed(complete))
        complete['cases'][0]['checks']['streaming']=1;self.assertFalse(acceptance.report_passed(complete))
        complete['cases'][0]['checks']['streaming']=True;complete['cases'][1]=copy.deepcopy(complete['cases'][0]);self.assertFalse(acceptance.report_passed(complete))

    def test_interrupt_and_lost_submission_response_cancel_original_task_without_resubmission(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app_fixture import create_app
        from test_model_configuration import FakeModelEndpoint,MemorySecrets
        import httpx
        class Observation:
            def __init__(self,*args,**kwargs):pass
            def snapshot(self):return {'requests':[],'streaming':False,'sensitiveContentObserved':False}
            def close(self):pass
        for failure in ('interrupt','lost_response'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,FakeModelEndpoint('openai-responses','artificial-cleanup','hold') as endpoint:
                root=Path(directory)
                with TestClient(create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())) as client:
                    configs=[]
                    for protocol in acceptance.PROTOCOLS:
                        configs.append(client.post('/api/workbench/model-configs',json={'name':'cleanup','protocol':protocol,'baseUrl':endpoint.url,'modelId':'artificial','apiKey':endpoint.key}).json())
                    class InterruptedApp:
                        def __init__(self):self.identity=None;self.url=None;self.submissions=0;self.injected=False
                        def request(self,path,body=None,method=None):
                            if failure=='interrupt' and self.identity and not self.injected and path.startswith(self.url+'/conversations/') and body is None:
                                self.injected=True;raise KeyboardInterrupt()
                            response=client.request(method or ('POST' if body is not None else 'GET'),'/api/workbench'+path,json=body)
                            self_outer.assertLess(response.status_code,400,response.text)
                            value=response.json()
                            if body is not None and path.endswith('/tasks'):
                                self.submissions+=1;self.identity=value['id'];self.url=path.removesuffix('/tasks');self_outer.assertTrue(endpoint.entered.wait(5))
                                if failure=='lost_response':raise httpx.ReadTimeout('artificial response lost after creation')
                            return value
                    self_outer=self;application=InterruptedApp();plan=acceptance.build_plan(configs,[c['id'] for c in configs],evidence_kind='fixture')
                    with patch.object(acceptance,'StreamObservation',Observation):
                        with self.assertRaises(KeyboardInterrupt if failure=='interrupt' else httpx.ReadTimeout):acceptance.run_suite(application,plan,root/'run',plan['digest'])
                    state=client.get('/api/workbench'+application.url).json();task=state['tasks'][0]
                    self.assertEqual(task['id'],application.identity);self.assertEqual(task['status'],'cancelled')
                    self.assertEqual(application.submissions,1);self.assertEqual(len(state['tasks']),1)
                    report=json.loads((root/'run/compatibility-report.json').read_text())
                    self.assertEqual(report['failureType'],'KeyboardInterrupt' if failure=='interrupt' else 'ReadTimeout')
                    self.assertEqual(report['cases'][-1]['taskId'],application.identity)
                    self.assertFalse(report['realCompatibilityPassed'])

    def test_opt_in_acceptance_guard_blocks_changed_receiver_before_dispatch_and_after_inflight(self):
        from fastapi.testclient import TestClient
        from app_fixture import create_app
        from test_model_configuration import FakeModelEndpoint,MemorySecrets
        from test_workbench_recovery import wait_state
        for when in ('before-first','after-inflight'):
            with self.subTest(when=when),tempfile.TemporaryDirectory() as directory,FakeModelEndpoint('openai-responses','artificial-approved','hold') as approved,FakeModelEndpoint('anthropic-messages','artificial-unapproved') as unapproved:
                root=Path(directory);(root/'project').mkdir()
                with TestClient(create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())) as client:
                    configs=[client.post('/api/workbench/model-configs',json={'name':'guard','protocol':e.protocol,'baseUrl':e.url,'modelId':'artificial-model','apiKey':e.key}).json() for e in (approved,unapproved)]
                    project=client.post('/api/workbench/projects',json={'path':str(root/'project')}).json();url='/api/workbench/projects/'+project['id']
                    chat=client.post(url+'/conversations',json={'title':'scope race'}).json()['id']
                    guard={k:configs[0][k] for k in ('id','protocol','baseUrl','modelId')}
                    client.put(url+'/conversations/'+chat+'/model',json={'configurationId':configs[1 if when=='before-first' else 0]['id']})
                    body={'conversationId':chat,'requestId':'guarded','goal':'人工ABC字符数','authorizedTools':['synthetic_count'],'acceptanceModel':guard}
                    response=client.post(url+'/tasks',json=body);self.assertEqual(response.status_code,201,response.text)
                    if when=='after-inflight':
                        self.assertTrue(approved.entered.wait(5));client.put(url+'/conversations/'+chat+'/model',json={'configurationId':configs[1]['id']});approved.release.set()
                    task=wait_state(client,url+'/conversations/'+chat,lambda s:s['tasks'][0]['status'] in ('paused','answered','failed'))['tasks'][0]
                    self.assertEqual(unapproved.requests,[],'reject before sending to an unapproved receiver')
                    self.assertEqual(task['status'],'paused');self.assertIn('验收',task['pauseReason'])
                    self.assertEqual(len(task['toolExecutions']),1 if when=='after-inflight' else 0)
                    changed={**body,'acceptanceModel':{**guard,'modelId':'different'}}
                    self.assertEqual(client.post(url+'/tasks',json=changed).status_code,409,'request ID cannot change expected recipient')

    @unittest.skipUnless((SOURCE.parents[2]/'release/PythonBoundaryProbe.app').exists(),'Build the independent analysis runtime first')
    def test_runner_stops_after_completed_python_when_next_model_request_is_guard_paused(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app_fixture import create_app
        from test_model_configuration import FakeModelEndpoint,MemorySecrets
        from test_restricted_analysis import SCRIPT
        class Observation:
            def __init__(self,*args,**kwargs):pass
            def snapshot(self):return {'requests':[],'streaming':False,'sensitiveContentObserved':False}
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory,FakeModelEndpoint('openai-responses','artificial-guard-runner','hold',tool_name='python_analysis',tool_arguments={'code':SCRIPT}) as first,FakeModelEndpoint('anthropic-messages','artificial-alternate') as second:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())) as client:
                configs=[client.post('/api/workbench/model-configs',json={'name':'runner guard','protocol':e.protocol,'baseUrl':e.url,'modelId':'artificial','apiKey':e.key}).json() for e in (first,second)]
                case=self
                class Application:
                    def __init__(self):self.submissions=0;self.url=None
                    def request(self,path,body=None,method=None):
                        response=client.request(method or ('POST' if body is not None else 'GET'),'/api/workbench'+path,json=body)
                        case.assertLess(response.status_code,400,response.text);value=response.json()
                        if body is not None and path.endswith('/tasks'):
                            self.submissions+=1;self.url=path.removesuffix('/tasks')
                            if self.submissions==1:
                                case.assertTrue(first.entered.wait(5))
                                client.put('/api/workbench'+self.url+'/conversations/'+body['conversationId']+'/model',json={'configurationId':configs[1]['id']});first.release.set()
                        return value
                    def bytes(self,path):return client.get('/api/workbench'+path).content
                application=Application();plan=acceptance.build_plan(configs,[c['id'] for c in configs],evidence_kind='fixture')
                with patch.object(acceptance,'StreamObservation',Observation):
                    with self.assertRaises(ValueError):acceptance.run_suite(application,plan,root/'run',plan['digest'])
                self.assertEqual(application.submissions,1,'a guard pause ends this whole approval run')
                self.assertEqual(second.requests,[])
                task=client.get('/api/workbench'+application.url).json()['tasks'][0]
                self.assertEqual(task['status'],'paused');self.assertEqual(task['toolExecutions'][0]['status'],'completed')
                report=json.loads((root/'run/compatibility-report.json').read_text())
                self.assertEqual(len(report['cases']),1);self.assertTrue(report['cases'][0]['checks']['artifactBytes']);self.assertFalse(report['cases'][0]['checks']['completed'])

    def test_safe_error_attempts_accept_bounded_retry_and_reject_replay_or_unbounded_attempts(self):
        for attempts in ([1],[1,2],[1,2,3]):
            self.assertTrue(error_probe.bounded_attempts([{'attempt':v,'status':'error'} for v in attempts]))
        for attempts in ([],[2],[1,3],[1,1],[1,2,3,4]):
            self.assertFalse(error_probe.bounded_attempts([{'attempt':v,'status':'error'} for v in attempts]))
        self.assertFalse(error_probe.bounded_attempts([{'attempt':1,'status':'completed'}]))

    def test_supplemental_errors_cannot_hide_missing_core_checks(self):
        import copy
        core_names=[name for name in acceptance.CASE_CHECKS if not name.startswith('invalid-key-')]
        base={'evidenceKind':'real','plan':{'configurations':configurations()},'cases':[{'case':name,'taskId':'task-'+str(i),'checks':{key:True for key in acceptance.CASE_CHECKS[name]}} for i,name in enumerate(acceptance.CASE_CHECKS)]}
        errors={'evidenceKind':'real','sourceReportSha256':acceptance.sha256(acceptance.canonical(base)),'cases':[{'protocol':p,'checks':{k:True for k in error_probe.REQUIRED}} for p in acceptance.PROTOCOLS]}
        self.assertTrue(error_probe.compatibility_passed(base,errors))
        for corruption in ('missing','duplicate-case','duplicate-task'):
            changed=copy.deepcopy(base)
            if corruption=='missing':changed['cases']=[c for c in changed['cases'] if c['case'] in core_names]
            elif corruption=='duplicate-case':changed['cases'][-1]['case']=changed['cases'][0]['case']
            else:changed['cases'][-1]['taskId']=changed['cases'][0]['taskId']
            errors['sourceReportSha256']=acceptance.sha256(acceptance.canonical(changed))
            with self.subTest(corruption=corruption):self.assertFalse(error_probe.compatibility_passed(changed,errors))
        changed=copy.deepcopy(base);changed['cases'][0]['checks'].pop('streaming')
        errors['sourceReportSha256']=acceptance.sha256(acceptance.canonical(changed));self.assertFalse(error_probe.compatibility_passed(changed,errors))
        errors['sourceReportSha256']=acceptance.sha256(acceptance.canonical(base));errors['cases'][0]['checks']['noTool']=1
        self.assertFalse(error_probe.compatibility_passed(base,errors))

    def test_result_references_compare_complete_numbers_including_exponents(self):
        prefix='summary.json 与 summary.xlsx：'
        for wrong in ('count=3.7, sum=9.5, mean=3.2','count=3e2, sum=9e-1, mean=3e1','count=3, sum=9, mean=3; sum=9.5'):
            with self.subTest(wrong=wrong):self.assertFalse(acceptance.references_result(prefix+wrong))
        self.assertTrue(acceptance.references_result(prefix+'count=3.0, sum=9e0, mean=3'))
        self.assertTrue(acceptance.references_result(prefix+'**count=3, sum=9, mean=3**。'))
        for ending in ('：`value`列统计',': actual result','）','；已核验','，已核验'):
            with self.subTest(ending=ending):self.assertTrue(acceptance.references_result(prefix+'**count=3, sum=9, mean=3**'+ending))
        self.assertTrue(acceptance.references_result(prefix+'`count=3`, `sum=9`, `mean=3`'))
        self.assertFalse(acceptance.references_result(prefix+'**count=3.7, sum=9.5, mean=3.2**'))

    def test_streaming_requires_two_partials_of_the_same_running_request(self):
        evidence=acceptance.PartialEvidence('task')
        def state(request,status,text):return {'tasks':[{'id':'task','status':'running','modelRequests':[{'id':request,'status':status}]}],'partial':[{'type':'text','text':text}]}
        evidence.add(state('first','running','one'))
        evidence.add(state('first','completed','one-final'))
        evidence.add(state('second','running','two'))
        self.assertFalse(evidence.snapshot()['streaming'])
        evidence.add(state('second','running','two-more'))
        self.assertTrue(evidence.snapshot()['streaming'])
        self.assertEqual(evidence.snapshot()['requests'][1]['distinctPartials'],2)

    def test_authentication_evidence_rejects_sentinel_and_raw_response_leaks(self):
        config=configurations()[0];sentinel='artificial-invalid-sentinel'
        task={'id':'t','status':'paused','toolExecutions':[],'modelRequests':[{'id':'r','configurationId':config['id'],'protocol':config['protocol'],'endpoint':config['baseUrl'],'model':config['modelId'],'status':'error','error':'所选模型凭据无效（401/403）'}]}
        state={'entries':[],'tasks':[task]};stream={'sensitiveContentObserved':False}
        self.assertTrue(all(acceptance.authentication_checks(task,state,config,stream,sentinel).values()))
        task['modelRequests'][0]['error']+=' '+sentinel
        self.assertFalse(acceptance.authentication_checks(task,state,config,stream,sentinel)['safeError'])
        task['modelRequests'][0]['error']='所选模型凭据无效（401/403）'
        state['entries']=[{'model':[{'role':'assistant','content':acceptance.ERROR_RESPONSE_MARKER}]}]
        self.assertFalse(acceptance.authentication_checks(task,state,config,stream,sentinel)['safeError'])
        evidence=acceptance.PartialEvidence('t',sensitive=(sentinel,acceptance.ERROR_RESPONSE_MARKER));evidence.add(state)
        self.assertTrue(evidence.snapshot()['sensitiveContentObserved'])
        self.assertNotIn(acceptance.ERROR_RESPONSE_MARKER,json.dumps(evidence.snapshot()))

    def test_source_identity_detects_dirty_application_code_without_lock_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'backend/src/silicolab').mkdir(parents=True);(root/'runtime/src').mkdir(parents=True)
            module=root/'runtime/src/agent.ts';module.write_text('before')
            before=acceptance.source_identity(root)
            module.write_text('after')
            self.assertNotEqual(before['sha256'],acceptance.source_identity(root)['sha256'])
            self.assertNotIn(directory,json.dumps(before))

    def test_report_strips_non_evidence_fields_and_rejects_mixed_recipients(self):
        config=configurations()[0]
        task={'id':'t','status':'answered','goal':'PRIVATE_ARTIFICIAL_PROMPT','modelRequests':[{'id':'r','configurationId':config['id'],'protocol':config['protocol'],'endpoint':config['baseUrl'],'model':config['modelId'],'status':'completed','usage':{'input':1,'output':2},'apiKey':'PRIVATE_ARTIFICIAL_KEY','rawResponse':'PRIVATE_ARTIFICIAL_RESPONSE'}],'toolExecutions':[]}
        result=acceptance.request_evidence(task,config)
        self.assertNotIn('PRIVATE_ARTIFICIAL',json.dumps(result));self.assertTrue(result['sameReceiver'])
        task['modelRequests'][0]['configurationId']='unexpected-recipient'
        self.assertFalse(acceptance.request_evidence(task,config)['sameReceiver'])


if __name__=='__main__':unittest.main()
