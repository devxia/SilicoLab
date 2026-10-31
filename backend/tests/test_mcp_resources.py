"""Artificial MCP stdio/HTTP: no real local MCP commands or credentials."""
import json
import os
import socket
from pathlib import Path
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from app_fixture import create_app
from fastapi.testclient import TestClient
from test_model_configuration import MemorySecrets
from test_workbench_science import wait_task
from test_workbench_recovery import wait_state

SERVER='''import sys,json,os,socket
for line in sys.stdin:
 message=json.loads(line);method=message.get('method');result={}
 if method=='initialize':result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'artificial-stdio','version':'1'}}
 elif method=='tools/list':result={'tools':[{'name':'echo','description':'artificial text only','inputSchema':{'type':'object','properties':{'text':{'type':'string','maxLength':100}},'required':['text'],'additionalProperties':False},'annotations':{'readOnlyHint':True}}]}
 elif method=='tools/call':
  checks={}
  try:socket.socket().connect(('127.0.0.1',9));checks['network']='allowed'
  except OSError as e:checks['network']=e.errno
  try:open('/private/var/empty/artificial-secret');checks['outside']='allowed'
  except OSError as e:checks['outside']=e.errno
  checks['environmentKey']=os.environ.get('OPENAI_API_KEY')
  result={'content':[{'type':'text','text':json.dumps({'echo':message['params']['arguments']['text'],'checks':checks})}]}
 if 'id' in message:print(json.dumps({'jsonrpc':'2.0','id':message['id'],'result':result}),flush=True)
'''


class HttpMcp:
    def __init__(self,mode='json',field=None,delay=0):
        self.mode=mode;self.field=field;self.delay=delay
        self.messages=[];self.calling=threading.Event();self.cancelled=threading.Event()
        endpoint=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_DELETE(self):self.send_response(200);self.end_headers()
            def do_POST(self):
                message=json.loads(self.rfile.read(int(self.headers['Content-Length'])));endpoint.messages.append(message)
                method=message['method']
                if endpoint.mode=='auth':
                    self.send_response(401);self.end_headers();return
                if method in ('initialize','tools/list') and endpoint.delay:time.sleep(endpoint.delay)
                if 'id' not in message:
                    if method=='notifications/cancelled':endpoint.cancelled.set()
                    self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'artificial-http','version':'1'}}
                elif method=='tools/list':
                    result={'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'text':endpoint.field or {'type':'string','maxLength':100}},'required':['text']},'annotations':{'readOnlyHint':True}}]}
                elif method=='tools/call':
                    endpoint.calling.set()
                    text=message['params']['arguments']['text']
                    if text=='hold':endpoint.cancelled.wait(5)
                    result={'content':[{'type':'text','text':text if isinstance(text,str) else json.dumps(text)}]}
                else:result={}
                value={'jsonrpc':'2.0','id':message['id'],'result':result}
                raw=json.dumps(value).encode();kind='application/json'
                if endpoint.mode in ('multiline_sse','cr_sse','split_crlf_sse'):
                    # One event, two data fields; split CRLF can span transport chunks.
                    parts=json.dumps(value).split(', "result":',1)
                    ending='\r' if endpoint.mode=='cr_sse' else '\r\n'
                    raw=(ending.join(['event: message','data: '+parts[0]+',','data: "result":'+parts[1],'',''])).encode();kind='text/event-stream'
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.end_headers()
                try:
                    if endpoint.mode=='split_crlf_sse':
                        for byte in raw:self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.001)
                    else:self.wfile.write(raw)
                except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_address[1]}/mcp'
    def __enter__(self):return self
    def __exit__(self,*_):self.cancelled.set();self.server.shutdown();self.server.server_close();self.thread.join(5)


class McpResourceTests(unittest.TestCase):
    def setup(self,client,root,config):
        project=root/'project';project.mkdir();(project/'.mcp.json').write_text(json.dumps(config))
        (project/'server.py').write_text(SERVER)
        opened=client.post('/api/workbench/projects',json={'path':str(project)}).json()
        url='/api/workbench/projects/'+opened['id'];chat=client.post(url+'/conversations',json={'title':'MCP task'}).json()['id']
        response=client.get(url+'/resources/mcp');self.assertEqual(response.status_code,200,response.text)
        return url,chat,response.json()['resources'][0],project

    def test_stdio_trust_real_schema_result_and_changed_script_requires_new_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,project=self.setup(client,root,{'mcpServers':{'artificial':{'type':'stdio','command':'silicolab-restricted-python','args':['server.py']}}})
                self.assertEqual(item['status'],'discovered')
                target=url+'/resources/mcp/'+item['id']
                self.assertEqual(client.post(target+'/connect',json={'fingerprint':item['fingerprint']}).status_code,409)
                self.assertEqual(client.post(target+'/trust',json={'fingerprint':item['fingerprint']}).status_code,200)
                connected=client.post(target+'/connect',json={'fingerprint':item['fingerprint']})
                self.assertEqual(connected.status_code,200,connected.text)
                self.assertEqual(connected.json()['tools'][0]['name'],'echo')
                body={'conversationId':chat,'requestId':'mcp-stdio','goal':'/mcp echo artificial text','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'ABC'},'authorizedTools':['mcp_call']}
                denied=client.post(url+'/tasks',json=body|{'authorizedTools':[]});self.assertEqual(denied.status_code,409)
                started=client.post(url+'/tasks',json=body);self.assertEqual(started.status_code,201,started.text)
                done=wait_task(client,url,chat,started.json()['id'])
                execution=done['toolExecutions'][0];self.assertEqual(execution['status'],'completed',execution)
                result=json.loads(execution['result']['content'][0]['text'])
                self.assertEqual(result['echo'],'ABC');self.assertEqual(result['checks']['network'],1);self.assertIsNone(result['checks']['environmentKey'])
                self.assertEqual(client.post(url+'/tasks',json=body).json()['id'],done['id'])
                (project/'server.py').write_text(SERVER+'\n# artificial change')
                changed=client.get(url+'/resources/mcp').json()['resources'][0]
                self.assertNotEqual(changed['fingerprint'],item['fingerprint']);self.assertEqual(changed['status'],'discovered')
                self.assertEqual(client.post(target+'/connect',json={'fingerprint':item['fingerprint']}).status_code,409)

    def test_http_real_connection_and_cancel_notification_not_remote_cancel_claim(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp() as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,project=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                self.assertEqual(server.messages,[])
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                self.assertEqual(client.post(target+'/connect',json={'fingerprint':item['fingerprint']}).status_code,200)
                body={'conversationId':chat,'requestId':'mcp-http','goal':'MCP人工回环','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'hold'},'authorizedTools':['mcp_call']}
                task=client.post(url+'/tasks',json=body);self.assertEqual(task.status_code,201,task.text)
                self.assertTrue(server.calling.wait(8))
                cancelled=client.post(url+f'/tasks/{task.json()["id"]}/cancel');self.assertEqual(cancelled.status_code,200,cancelled.text)
                self.assertTrue(server.cancelled.wait(3));self.assertEqual(cancelled.json()['status'],'cancelled')
                self.assertEqual(len([m for m in server.messages if m['method']=='tools/call']),1)

    def test_stdio_live_file_network_and_cancellation_boundaries(self):
        with tempfile.TemporaryDirectory() as directory,socket.socket() as listener:
            root=Path(directory);sentinel=root/'artificial-key.txt';sentinel.write_text('artificial-mcp-key-sentinel')
            listener.bind(('127.0.0.1',0));listener.listen()
            with TestClient(create_app(root/'app.sqlite3',delay=0,credential_store=MemorySecrets())) as client:
                url,chat,item,project=self.setup(client,root,{'mcpServers':{'artificial':{'type':'stdio','command':'silicolab-restricted-python','args':['server.py']}}})
                config=client.post('/api/workbench/model-configs',json={'name':'separate artificial model key','protocol':'openai-responses','baseUrl':'http://127.0.0.1:9/v1','modelId':'artificial','apiKey':'artificial-mcp-key-sentinel'})
                self.assertEqual(config.status_code,201,config.text)
                code=SERVER.replace("('127.0.0.1',9)",f"('127.0.0.1',{listener.getsockname()[1]})").replace("'/private/var/empty/artificial-secret'",repr(str(sentinel)))
                code=code.replace("  checks={}","  import time\n  if message['params']['arguments']['text']=='hold':time.sleep(20)\n  checks={}")
                protected=project/'artificial-original.txt';protected.write_text('unchanged original')
                code=code.replace("  checks={}",f"  checks={{}}\n  try:open({str(protected)!r},'w').write('changed');checks['original']='allowed'\n  except OSError as e:checks['original']=e.errno\n  try:os.fork();checks['fork']='allowed'\n  except OSError as e:checks['fork']=e.errno\n  try:__import__('ensurepip').bootstrap();checks['install']='allowed'\n  except (OSError,ImportError) as e:checks['install']=getattr(e,'errno',None) or 'unavailable'")
                (project/'server.py').write_text(code)
                item=client.get(url+'/resources/mcp').json()['resources'][0];target=url+'/resources/mcp/'+item['id']
                client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                body={'conversationId':chat,'requestId':'mcp-live','goal':'explicit MCP text only','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'ABC'},'authorizedTools':['mcp_call']}
                task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                result=json.loads(done['toolExecutions'][0]['result']['content'][0]['text'])
                self.assertEqual(result['checks']['outside'],1);self.assertEqual(result['checks']['network'],1)
                self.assertEqual(result['checks']['original'],1);self.assertEqual(protected.read_text(),'unchanged original')
                self.assertEqual(result['checks']['fork'],1);self.assertIn(result['checks']['install'],(1,13,'unavailable'))
                self.assertIsNone(result['checks']['environmentKey'])
                listener.settimeout(.05)
                with self.assertRaises(TimeoutError):listener.accept()
                self.assertEqual(sentinel.read_text(),'artificial-mcp-key-sentinel')
                held=client.post(url+'/tasks',json=body|{'requestId':'held','mcpArguments':{'text':'hold'}}).json()
                state=wait_state(client,url+f'/conversations/{chat}',lambda s:s['tasks'][-1]['toolExecutions'] and s['tasks'][-1]['toolExecutions'][0].get('pythonPid'))
                pid=state['tasks'][-1]['toolExecutions'][0]['pythonPid']
                cancelled=client.post(url+f'/tasks/{held["id"]}/cancel');self.assertEqual(cancelled.status_code,200,cancelled.text)
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
                self.assertEqual(cancelled.json()['status'],'cancelled')

    def test_conflicts_bad_schema_and_reopen_keep_only_same_configuration_trust(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp() as server:
            root=Path(directory);extra=root/'user-mcp.json';extra.write_text(json.dumps({'mcpServers':{'artificial':{'type':'http','url':server.url}}}))
            with TestClient(create_app(root/'app.sqlite3',delay=0,mcp_roots=[str(extra)])) as client:
                url,chat,item,project=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                self.assertEqual([r['status'] for r in client.get(url+'/resources/mcp').json()['resources']],['discovered','shadowed'])
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                wrong={'conversationId':chat,'requestId':'badargs','goal':'invalid MCP args','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':17},'authorizedTools':['mcp_call']}
                task=client.post(url+'/tasks',json=wrong).json();done=wait_task(client,url,chat,task['id'])
                self.assertEqual(done['toolExecutions'][0]['status'],'failed')
                self.assertEqual([m for m in server.messages if m['method']=='tools/call'],[])
            with TestClient(create_app(root/'app.sqlite3',delay=0,mcp_roots=[str(extra)])) as client:
                client.post('/api/workbench/projects/open',json={'path':str(project)})
                self.assertEqual(client.get(url+'/resources/mcp').json()['resources'][0]['status'],'trusted')

    def test_multiline_sse_connects_and_calls_real_tool(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp(mode='multiline_sse') as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                connected=client.post(target+'/connect',json={'fingerprint':item['fingerprint']})
                self.assertEqual(connected.status_code,200,connected.text)
                body={'conversationId':chat,'requestId':'multiline','goal':'MCP人工SSE','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'ABC'},'authorizedTools':['mcp_call']}
                task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                self.assertEqual(done['toolExecutions'][0]['result']['content'][0]['text'],'ABC')

    def test_sse_cr_only_and_crlf_split_across_chunks_connect_and_return_result(self):
        for mode in ('cr_sse','split_crlf_sse'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory,HttpMcp(mode=mode) as server:
                root=Path(directory)
                with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                    url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                    target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                    connected=client.post(target+'/connect',json={'fingerprint':item['fingerprint']})
                    self.assertEqual(connected.status_code,200,connected.text)
                    body={'conversationId':chat,'requestId':'line-endings','goal':'MCP SSE line endings','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'ABC'},'authorizedTools':['mcp_call']}
                    task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                    self.assertEqual(done['toolExecutions'][0]['result']['content'][0]['text'],'ABC')

    def test_json_enum_does_not_equate_booleans_and_numbers(self):
        for field,value in [({'type':'boolean','enum':[1]},True),({'type':'number','enum':[True]},1)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as directory,HttpMcp(field=field) as server:
                root=Path(directory)
                with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                    url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                    client.post(url+'/resources/mcp/'+item['id']+'/trust',json={'fingerprint':item['fingerprint']})
                    body={'conversationId':chat,'requestId':'enum','goal':'MCPenum','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':value},'authorizedTools':['mcp_call']}
                    task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                    self.assertEqual(done['toolExecutions'][0]['status'],'failed')
                    self.assertEqual([m for m in server.messages if m['method']=='tools/call'],[])

    def test_integer_schema_accepts_integral_json_numbers_but_not_fraction_or_boolean(self):
        # Exercise the supervisor's JSON seam directly: JS otherwise canonicalizes 1.0 to 1.
        from silicolab.mcp_resources import McpResources
        from silicolab.mcp_execution import run_mcp
        with tempfile.TemporaryDirectory() as directory,HttpMcp(field={'type':'integer','enum':[1]}) as server:
            root=Path(directory).resolve();project=root/'project';project.mkdir()
            (project/'.mcp.json').write_text(json.dumps({'mcpServers':{'artificial':{'type':'http','url':server.url}}}))
            resources=McpResources(root/'trust.json',[]);item=resources.list(project)['resources'][0]
            resources.trust(project,item['id'],item['fingerprint']);config=resources.resolve(project,item['id'],item['fingerprint'])
            request={'mcp':config,'operation':'call','tool':'echo','arguments':{'text':1.0}}
            result=run_mcp(request,lambda _:None,threading.Event())
            self.assertEqual(result['result']['status'],'completed')
            for value in [1.5,True,float('inf'),float('nan')]:
                with self.subTest(value=value),self.assertRaises(ValueError):
                    run_mcp(request|{'arguments':{'text':value}},lambda _:None,threading.Event())
            calls=[m for m in server.messages if m['method']=='tools/call']
            self.assertEqual(len(calls),1);self.assertEqual(calls[0]['params']['arguments'],{'text':1.0})

    def test_ipc_deadline_failure_retires_host_instead_of_leaving_late_response(self):
        from unittest.mock import patch
        from silicolab.workbench import ProjectHost
        with tempfile.TemporaryDirectory() as directory,HttpMcp() as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                node=client.get(url).json()['runtimePid']
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                read=ProjectHost._read
                def timeout_mcp(host,timeout=10):
                    if timeout==70:raise ValueError('artificial IPC deadline')
                    return read(host,timeout=timeout)
                with patch.object(ProjectHost,'_read',timeout_mcp):
                    self.assertEqual(client.post(target+'/connect',json={'fingerprint':item['fingerprint']}).status_code,409)
                with self.assertRaises(ProcessLookupError):os.kill(node,0)
                self.assertEqual(client.get(url).status_code,200)
                self.assertNotEqual(client.get(url).json()['runtimePid'],node)
                self.assertEqual(client.post(url+'/conversations',json={'title':'new clean IPC'}).status_code,201)

    def test_slow_connect_does_not_poison_host_ipc(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp(delay=6) as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                connected=client.post(target+'/connect',json={'fingerprint':item['fingerprint']})
                self.assertEqual(connected.status_code,200,connected.text)
                self.assertEqual(client.get(url).status_code,200)
                self.assertEqual(client.post(url+'/conversations',json={'title':'IPC still consistent'}).status_code,201)

    def test_http_auth_required_is_configuration_state_not_generic_failure(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp(mode='auth') as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                self.assertEqual(client.post(target+'/connect',json={'fingerprint':item['fingerprint']}).status_code,409)
                state=client.get(url+'/resources/mcp').json()['resources'][0]
                self.assertEqual(state['status'],'needs_configuration')
                self.assertIn('认证',state['reason'])
                self.assertEqual(len(server.messages),1)

    def test_connection_state_does_not_change_stable_request_identity(self):
        with tempfile.TemporaryDirectory() as directory,HttpMcp() as server:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':server.url}}})
                target=url+'/resources/mcp/'+item['id'];client.post(target+'/trust',json={'fingerprint':item['fingerprint']})
                body={'conversationId':chat,'requestId':'stable','goal':'MCPstable','workflow':'mcp_tool','mcpResourceId':item['id'],'mcpFingerprint':item['fingerprint'],'mcpTool':'echo','mcpArguments':{'text':'ABC'},'authorizedTools':['mcp_call']}
                task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                client.post(target+'/connect',json={'fingerprint':item['fingerprint']})
                retry=client.post(url+'/tasks',json=body);self.assertEqual(retry.status_code,201,retry.text)
                self.assertEqual(retry.json()['id'],done['id'])
                self.assertEqual(len([m for m in server.messages if m['method']=='tools/call']),1)

    def test_malformed_trust_structure_returns_409_and_preserves_original_bytes(self):
        for bad in ([{}],{},None,[{'id':'x','fingerprint':'y'}],[{'id':'a'*64,'fingerprint':'b'*64,'extra':True}]):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                with TestClient(create_app(root/'app.sqlite3',delay=0),raise_server_exceptions=False) as client:
                    url,_,item,_=self.setup(client,root,{'mcpServers':{'artificial':{'type':'http','url':'http://127.0.0.1:9/mcp'}}})
                    path=root/'mcp-trust.json';original=json.dumps(bad).encode();path.write_bytes(original)
                    state=client.get(url+'/resources/mcp').json()['resources'][0]
                    self.assertNotIn(state['status'],('trusted','callable'))
                    target=url+'/resources/mcp/'+item['id'];body={'fingerprint':item['fingerprint']}
                    result=client.post(target+'/trust',json=body)
                    self.assertEqual(result.status_code,409,result.text);self.assertIn('信任记录损坏',result.json()['detail'])
                    self.assertEqual(client.post(target+'/connect',json=body).status_code,409)
                    self.assertEqual(path.read_bytes(),original)

    def test_fifo_source_is_rejected_before_trust_without_blocking_discovery(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();project=root/'project';project.mkdir();os.mkfifo(project/'.mcp.json')
            code="import json,sys;from silicolab.mcp_resources import McpResources;print(json.dumps(McpResources(sys.argv[2],[]).list(sys.argv[1])))"
            try:
                result=subprocess.run([sys.executable,'-B','-c',code,str(project),str(root/'trust.json')],capture_output=True,text=True,timeout=2)
            except subprocess.TimeoutExpired:
                self.fail('MCP discovery blocked on an untrusted FIFO')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['resources'][0]['status'],'incompatible')

    def test_arbitrary_command_and_embedded_auth_are_not_executed_or_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                url,chat,_,project=self.setup(client,root,{'mcpServers':{'a':{'type':'stdio','command':'/bin/sh','args':['-c','touch must-not-exist']},'b':{'type':'http','url':'https://example.invalid/mcp','headers':{'Authorization':'artificial-secret'}}}})
                catalog=client.get(url+'/resources/mcp').json()['resources']
                self.assertEqual([r['status'] for r in catalog],['incompatible','needs_configuration'])
                self.assertNotIn('artificial-secret',json.dumps(catalog));self.assertFalse((project/'must-not-exist').exists())


if __name__=='__main__':unittest.main()
