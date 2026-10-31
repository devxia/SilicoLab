"""Loopback protocol fixtures for exercising the opt-in runner; never real evidence."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import time
from test_restricted_analysis import SCRIPT


class AcceptanceEndpoint:
    def __init__(self,protocol):
        self.protocol=protocol;self.key='artificial-'+protocol;self.requests=[];endpoint=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                credential=self.headers.get('x-api-key') if protocol=='anthropic-messages' else self.headers.get('Authorization','').removeprefix('Bearer ')
                endpoint.requests.append({'body':data,'authorized':credential==endpoint.key})
                if data.get('model')=='silicolab-acceptance-no-such-model-8c074a9b':
                    self.send_response(404);self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(json.dumps({'error':{'type':'model_not_found','message':str(credential)+' ARTIFICIAL_RAW_AUTH_RESPONSE_NOT_FOR_HISTORY'}}).encode());return
                if credential!=endpoint.key:
                    self.send_response(401);self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(json.dumps({'error':{'type':'authentication_error','message':str(credential)+' ARTIFICIAL_RAW_AUTH_RESPONSE_NOT_FOR_HISTORY'}}).encode());return
                result_present=any(x.get('type')=='function_call_output' for x in data.get('input',[]) if isinstance(x,dict)) or any(b.get('type')=='tool_result' for m in data.get('messages',[]) for b in m.get('content',[]) if isinstance(b,dict))
                cancelling='2000' in json.dumps(data,ensure_ascii=False)
                tool=not cancelling and not result_present
                reply=('人工取消演示文字。'*120) if cancelling else 'summary.json 与 summary.xlsx：count=3, sum=9, mean=3。结果来自已执行的本地Python。'
                chunks=[reply[i:i+12] for i in range(0,len(reply),12)]
                if protocol=='openai-responses':
                    response={'id':'resp_fixture','object':'response','status':'completed','output':[],'usage':{'input_tokens':11,'output_tokens':13,'total_tokens':24}}
                    item={'id':'fc_fixture','type':'function_call','call_id':'call_fixture','name':'python_analysis','arguments':json.dumps({'code':SCRIPT}),'status':'completed'} if tool else {'id':'msg_fixture','type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':reply,'annotations':[]}]}
                    response['output']=[item]
                    start=item if tool else {**item,'content':[],'status':'in_progress'}
                    events=[{'type':'response.created','response':{**response,'output':[],'status':'in_progress'}},{'type':'response.output_item.added','output_index':0,'item':start}]
                    if not tool:
                        events.append({'type':'response.content_part.added','item_id':item['id'],'output_index':0,'content_index':0,'part':{'type':'output_text','text':'','annotations':[]}})
                        events.extend({'type':'response.output_text.delta','item_id':item['id'],'output_index':0,'content_index':0,'delta':chunk} for chunk in chunks)
                    events.extend([{'type':'response.output_item.done','output_index':0,'item':item},{'type':'response.completed','response':response}])
                else:
                    block={'type':'tool_use','id':'toolu_fixture','name':'python_analysis','input':{}} if tool else {'type':'text','text':''}
                    events=[{'type':'message_start','message':{'id':'msg_fixture','type':'message','role':'assistant','model':'artificial-messages','content':[],'usage':{'input_tokens':11,'output_tokens':0},'stop_reason':None,'stop_sequence':None}},{'type':'content_block_start','index':0,'content_block':block}]
                    if tool:events.append({'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':json.dumps({'code':SCRIPT})}})
                    else:events.extend({'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':chunk}} for chunk in chunks)
                    events.extend([{'type':'content_block_stop','index':0},{'type':'message_delta','delta':{'stop_reason':'tool_use' if tool else 'end_turn','stop_sequence':None},'usage':{'output_tokens':13}},{'type':'message_stop'}])
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                try:
                    for event in events:
                        self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode());self.wfile.flush();time.sleep(.13)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])+('/v1' if protocol=='openai-responses' else '')
    def __enter__(self):return self
    def __exit__(self,*_):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
