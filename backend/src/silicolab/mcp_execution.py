"""Bounded MCP 2025-06-18 tool sessions; no sampling, roots, auth discovery or shell."""
import asyncio
import json
import math
from pathlib import Path
import threading
import time
import uuid
from contextlib import contextmanager
import hashlib
from silicolab.restricted_python import PythonProbe
from silicolab.mcp_resources import read_source
from silicolab.analysis_execution import verify_runtime,runtime_app

VERSION='2025-06-18'

class McpConfigurationRequired(ValueError):
    def __init__(self):super().__init__('MCP_NEEDS_CONFIGURATION:服务要求认证，本版不导入外部认证，请显式配置受支持连接')


def json_equal(first,second):
    if isinstance(first,bool) or isinstance(second,bool):return type(first) is type(second) and first==second
    if isinstance(first,(int,float)) and isinstance(second,(int,float)):return first==second
    return type(first) is type(second) and first==second


def validate_tools(value):
    tools=value.get('tools')
    if not isinstance(tools,list) or len(tools)>30 or value.get('nextCursor'):raise ValueError('MCP工具目录超限或分页不支持')
    for tool in tools:
        schema=tool.get('inputSchema',{})
        if not isinstance(tool.get('name'),str) or len(tool['name'])>100 or schema.get('type')!='object' or set(schema)-{'type','properties','required','additionalProperties'}:raise ValueError('MCP工具schema不兼容')
        if not isinstance(schema.get('properties',{}),dict) or not isinstance(schema.get('required',[]),list) or any(not isinstance(name,str) or name not in schema.get('properties',{}) for name in schema.get('required',[])):raise ValueError('MCP schema字段集合不兼容')
        if schema.get('additionalProperties') is not None and schema['additionalProperties'] is not False:raise ValueError('MCP schema additionalProperties不兼容')
        if len(schema.get('properties',{}))>20:raise ValueError('MCP schema仅支持有界标量对象')
        for spec in schema.get('properties',{}).values():
            if not isinstance(spec,dict):raise ValueError('MCP schema标量格式不兼容')
            for key in ('minLength','maxLength','minimum','maximum'):
                if key in spec:
                    limit=spec[key]
                    if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit):raise ValueError('MCP schema限值类型不兼容')
                    if key.endswith('Length') and (not isinstance(limit,int) or limit<0):raise ValueError('MCP schema长度限值不兼容')
            if 'enum' in spec and (not isinstance(spec['enum'],list) or not 1<=len(spec['enum'])<=100 or any(v is not None and not isinstance(v,(str,int,float,bool)) for v in spec['enum'])):raise ValueError('MCP schema枚举格式不兼容')
            if spec.get('type') not in ('string','number','integer','boolean') or set(spec)-{'type','description','minLength','maxLength','enum','minimum','maximum'}:raise ValueError('MCP schema仅支持标量字段')
    return tools


def validate_arguments(tool,arguments):
    schema=tool['inputSchema'];properties=schema.get('properties',{})
    if not isinstance(arguments,dict) or set(arguments)-set(properties) or set(schema.get('required',[]))-set(arguments):raise ValueError('MCP参数不满足实际schema')
    for name,value in arguments.items():
        spec=properties[name];kind=spec['type']
        if kind=='string':
            if not isinstance(value,str) or len(value)>min(spec.get('maxLength',10000),10000) or len(value)<spec.get('minLength',0):raise ValueError('MCP字符串参数超范围')
        elif kind=='boolean':
            if not isinstance(value,bool):raise ValueError('MCP布尔参数类型不符')
        else:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (kind=='integer' and isinstance(value,float) and not value.is_integer()):raise ValueError('MCP数值参数类型不符')
            if value<spec.get('minimum',float('-inf')) or value>spec.get('maximum',float('inf')):raise ValueError('MCP数值参数超范围')
        if 'enum' in spec and not any(json_equal(value,allowed) for allowed in spec['enum']):raise ValueError('MCP参数不在枚举内')


class StdioSession:
    def __init__(self,config,on_start,cancelled):
        self.config=config;self.cancelled=cancelled;self.offset=0;self.partial=b''
        script=Path(config['script'])
        if script.is_symlink() or any(p.is_symlink() for p in script.parents):raise ValueError('MCP脚本链接不兼容')
        code=read_source(script,100000).decode('utf-8')
        if hashlib.sha256(code.encode()).hexdigest()!=config['scriptSha256']:raise ValueError('MCP脚本已改变；需重新确认来源')
        self.owner=PythonProbe(runtime=verify_runtime(runtime_app()))
        try:
            self.run=self.owner.start(code,interactive=True)
            on_start(self.run)
        except BaseException:
            self.owner.close()
            raise
    def exchange(self,message):
        self.run.send(message)
        if 'id' not in message:return None
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if self.cancelled.is_set():raise InterruptedError('MCP调用已取消')
            raw=self.run.log('stdout')
            chunk=raw[self.offset:];self.offset=len(raw);self.partial+=chunk
            while b'\n' in self.partial:
                line,self.partial=self.partial.split(b'\n',1)
                response=json.loads(line)
                if response.get('jsonrpc')!='2.0' or response.get('id')!=message['id']:raise ValueError('MCP stdio身份或消息不匹配')
                if 'error' in response:raise ValueError('MCP服务返回协议错误')
                return response['result']
            if self.run.status()['status']!='running':raise ValueError('MCP本地进程已结束或无有效响应')
            time.sleep(.01)
        raise TimeoutError('MCP stdio请求超时')
    def close(self):self.owner.close()


class HttpSession:
    def __init__(self,config,cancelled):
        self.url=config['url'];self.cancelled=cancelled;self.session=None
    def exchange(self,message):
        import httpx
        async def operation():
            headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json','MCP-Protocol-Version':VERSION}
            if self.session:headers['Mcp-Session-Id']=self.session
            async with httpx.AsyncClient(timeout=10,trust_env=False,follow_redirects=False) as client:
                async def send():
                    async with client.stream('POST',self.url,json=message,headers=headers) as response:
                        if response.status_code in (401,403):raise McpConfigurationRequired()
                        response.raise_for_status()
                        if response.headers.get('mcp-session-id'):
                            session=response.headers['mcp-session-id']
                            if len(session)>200 or not all(0x21<=ord(c)<=0x7e for c in session):raise ValueError('MCP session身份格式不兼容')
                            self.session=session
                        def result(value):
                            if not isinstance(value,dict) or value.get('jsonrpc')!='2.0' or value.get('id')!=message['id'] or 'error' in value or 'result' not in value:raise ValueError('MCP响应身份或协议不匹配')
                            return value['result']
                        if 'id' not in message:
                            if response.status_code!=202:raise ValueError('MCP通知响应不兼容')
                            return None
                        kind=response.headers.get('content-type','').lower()
                        raw=b'';total=0;data=[];pending_cr=False
                        async for chunk in response.aiter_bytes():
                            total+=len(chunk)
                            if total>1024*1024:raise ValueError('MCP响应超过1MiB')
                            if kind.startswith('text/event-stream'):
                                if pending_cr and chunk.startswith(b'\n'):chunk=chunk[1:]
                                pending_cr=chunk.endswith(b'\r')
                                raw+=chunk.replace(b'\r\n',b'\n').replace(b'\r',b'\n')
                                while b'\n' in raw:
                                    line,raw=raw.split(b'\n',1)
                                    if not line:
                                        if not data:continue
                                        value=json.loads(b'\n'.join(data));data=[]
                                        if isinstance(value,dict) and value.get('id')==message['id']:return result(value)
                                        if not isinstance(value,dict) or 'id' in value:raise ValueError('MCP SSE收到不支持的服务请求或错误身份')
                                    elif line.startswith(b'data:'):
                                        data.append(line[5:].removeprefix(b' '))
                            else:raw+=chunk
                        if kind.startswith('application/json'):return result(json.loads(raw))
                        if kind.startswith('text/event-stream'):raise ValueError('MCP SSE结束前无匹配完整响应事件')
                        raise ValueError('MCP响应transport不兼容')
                task=asyncio.create_task(send())
                try:
                    while not task.done():
                        if self.cancelled.is_set():
                            task.cancel()
                            try:await task
                            except asyncio.CancelledError:pass
                            if message.get('method')!='initialize' and 'id' in message:
                                try:await client.post(self.url,json={'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':message['id'],'reason':'User stopped local call'}},headers=headers,timeout=2)
                                except httpx.HTTPError:pass
                            raise InterruptedError('MCP取消已请求；独立远端效果未确认撤销')
                        await asyncio.sleep(.02)
                    try:
                        return await task
                    except httpx.TimeoutException:
                        if message.get('method')!='initialize' and 'id' in message:
                            try:await client.post(self.url,json={'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':message['id'],'reason':'Request timeout'}},headers=headers,timeout=2)
                            except httpx.HTTPError:pass
                        raise ValueError('MCP请求超时，远端效果未知；未自动重试') from None
                finally:
                    if not task.done():task.cancel()
        return asyncio.run(operation())
    def close(self):
        if self.session:
            import httpx
            try:httpx.delete(self.url,headers={'Mcp-Session-Id':self.session,'MCP-Protocol-Version':VERSION},timeout=2,trust_env=False,follow_redirects=False)
            except (httpx.HTTPError,ValueError):pass


def run_mcp(request,on_start,cancelled):
    config=request['mcp'];session=None
    if hashlib.sha256(read_source(Path(config['path']),256*1024)).hexdigest()!=config['configFileSha256']:
        raise ValueError('MCP配置已改变，未连接旧接收方，请重新确认')
    try:
        if cancelled.is_set():raise InterruptedError('MCP尚未启动已取消')
        session=StdioSession(config,on_start,cancelled) if config['type']=='stdio' else HttpSession(config,cancelled)
        def call(method,params):return session.exchange({'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':method,'params':params})
        initialized=call('initialize',{'protocolVersion':VERSION,'capabilities':{},'clientInfo':{'name':'SilicoLab','version':'0.1'}})
        if initialized.get('protocolVersion')!=VERSION or 'tools' not in initialized.get('capabilities',{}):raise ValueError('MCP版本/工具能力不兼容')
        session.exchange({'jsonrpc':'2.0','method':'notifications/initialized'})
        tools=validate_tools(call('tools/list',{}))
        result={'status':'connected','inputVersionId':'','records':[],'engine_info':{'id':'mcp','label':config['name'],'version':VERSION},'network_attempts':None,'scope':'explicit trusted MCP tool session','tools':tools,'source':config['source'],'fingerprint':config['fingerprint']}
        if request.get('operation')=='call':
            tool=next((t for t in tools if t['name']==request['tool']),None)
            if not tool:raise ValueError('MCP工具已改变或不存在')
            # No external effect permit is inferred from annotations or server trust.
            if tool.get('annotations',{}).get('readOnlyHint') is not True:raise ValueError('首版仅允许明确readOnlyHint工具；副作用/科学提交不开放')
            validate_arguments(tool,request['arguments'])
            response=call('tools/call',{'name':tool['name'],'arguments':request['arguments']})
            if not isinstance(response,dict) or not isinstance(response.get('content'),list) or any(c.get('type')!='text' or not isinstance(c.get('text'),str) for c in response['content']):raise ValueError('MCP工具结果格式不兼容')
            result.update(status='failed' if response.get('isError') else 'completed',tool=tool['name'],arguments=request['arguments'],content=response['content'])
        return {'ok':True,'result':result,'files':[]}
    finally:
        if session:session.close()
