"""Bounded MCP-only JSON discovery and application-owned trust (never execute on scan)."""
import hashlib
import os
import stat
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from silicolab.desktop_lifecycle import atomic_json


def sha(content):return hashlib.sha256(content).hexdigest()


def read_source(path,limit):
    """Read untrusted MCP input with bounded descriptors, never wait on a FIFO."""
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('MCP来源不支持符号链接')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise ValueError('MCP来源必须为有界普通文件')
        chunks=[];size=0
        while size<=limit:
            chunk=os.read(fd,min(65536,limit+1-size))
            if not chunk:break
            chunks.append(chunk);size+=len(chunk)
        after=os.fstat(fd)
        if size>limit or size!=before.st_size or (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns):raise ValueError('MCP来源读取期间改变或超限')
        return b''.join(chunks)
    finally:os.close(fd)


class McpResources:
    def __init__(self,path,roots=None):
        self.path=Path(path).parent.resolve()/Path(path).name;self.roots=roots;self.lock=threading.RLock()
        self.states={}

    def locations(self,project):
        paths=[(Path(project)/'.mcp.json','project:.mcp.json')]
        if self.roots is None:
            paths.append((Path.home()/'.config/silicolab/mcp.json','user:~/.config/silicolab/mcp.json'))
        else:paths += [(Path(p).parent.resolve()/Path(p).name,f'test:mcp-{i}') for i,p in enumerate(self.roots)]
        return paths

    def list(self,project):
        resources=[];names=set()
        for path,source in self.locations(project):
            if not path.exists():continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                resources.append({'id':sha(str(path).encode()),'source':source,'status':'incompatible','reason':'MCP来源不支持符号链接'});continue
            try:
                raw=read_source(path,256*1024);data=json.loads(raw)
                if set(data)!={'mcpServers'} or not isinstance(data['mcpServers'],dict) or len(data['mcpServers'])>50:raise ValueError('只支持独立mcpServers对象(最多50项)，不读取混合模型/认证配置')
            except (OSError,ValueError,TypeError) as e:
                resources.append({'id':sha(str(path).encode()),'source':source,'status':'incompatible','reason':'MCP JSON格式或独立配置结构不兼容'});continue
            for name,config in sorted(data['mcpServers'].items()):
                identity=sha((str(path)+'\n'+name).encode())
                item={'id':identity,'name':name,'source':source,'path':str(path),'status':'incompatible'}
                try:
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',name) or not isinstance(config,dict):raise ValueError('MCP名称/配置格式不兼容')
                    normalized={'configFileSha256':sha(raw)}
                    if any(k in config for k in ('env','headers','apiKey','token','authorization')):
                        item['status']='needs_configuration';raise ValueError('需要显式安全连接信息；不导入配置中的环境或认证')
                    if config.get('type')=='http':
                        if set(config)!={'type','url'} or not isinstance(config['url'],str):raise ValueError('HTTP配置只接受type/url')
                        url=urlsplit(config['url'])
                        if url.username or url.password or url.query or url.fragment or not url.hostname or url.scheme not in ('http','https') or (url.scheme=='http' and url.hostname not in ('127.0.0.1','localhost','::1')):raise ValueError('MCP地址须HTTPS或回环HTTP且无认证/查询')
                        url.port
                        normalized.update(type='http',url=config['url'])
                    elif config.get('type')=='stdio':
                        if set(config)!={'type','command','args'} or config['command']!='silicolab-restricted-python' or not isinstance(config['args'],list) or len(config['args'])!=1 or not isinstance(config['args'][0],str):raise ValueError('仅支持受限独立Python单脚本stdio；任意命令/参数/安装均不执行')
                        relative=Path(config['args'][0])
                        if relative.is_absolute() or '..' in relative.parts or relative.suffix!='.py':raise ValueError('stdio脚本须为配置目录内相对.py文件')
                        script=path.parent/relative
                        if script.is_symlink() or any(p.is_symlink() for p in script.parents) or not script.is_file() or script.stat().st_size>100000:raise ValueError('MCP脚本来源不兼容或超限')
                        code=read_source(script,100000).decode('utf-8')
                        normalized.update(type='stdio',command=config['command'],script=str(script),scriptSha256=sha(code.encode()))
                    else:raise ValueError('MCP transport方言不兼容')
                    fingerprint=sha(json.dumps({'config':normalized,'source':str(path)},sort_keys=True).encode())
                    item.update(normalized,fingerprint=fingerprint,status='discovered')
                    if name in names:item.update(status='shadowed',reason='相同名称由高优先级来源提供')
                    else:
                        names.add(name)
                        if self.trusted(identity,fingerprint):item['status']='trusted'
                    state=self.states.get((identity,fingerprint))
                    if state and item['status']=='trusted':item.update(state)
                except (OSError,ValueError,TypeError,KeyError):
                    item['reason']=item.get('reason','来源或权限边界不兼容；仅支持独立HTTP/受限Python单脚本stdio，无环境认证导入')
                resources.append(item)
        return {'resources':resources}

    def trust_records(self):
        try:
            values=json.loads(read_source(self.path,256*1024))
            if not isinstance(values,list) or any(not isinstance(v,dict) or set(v)!={'id','fingerprint'} or any(not isinstance(v[k],str) or not re.fullmatch('[0-9a-f]{64}',v[k]) for k in ('id','fingerprint')) for v in values):raise ValueError('无效信任记录结构')
            if len({v['id'] for v in values})!=len(values):raise ValueError('重复信任记录身份')
            return values
        except FileNotFoundError:return []
        except (OSError,ValueError):raise ValueError('MCP信任记录损坏；原文件保留，不自动信任') from None

    def trusted(self,identity,fingerprint):
        return any(i=={'id':identity,'fingerprint':fingerprint} for i in self.trust_records())

    def resolve(self,project,identity,fingerprint,require_trust=True):
        item=next((r for r in self.list(project)['resources'] if r['id']==identity),None)
        if not item or item.get('fingerprint')!=fingerprint or item['status'] in ('incompatible','shadowed','needs_configuration'):raise ValueError('MCP来源/配置/脚本已改变或不兼容，请重新发现并确认')
        if require_trust and not self.trusted(identity,fingerprint):raise ValueError('MCP来源尚未确认信任，未执行启动命令或连接')
        fields=('id','name','source','path','fingerprint','configFileSha256','type','url','command','script','scriptSha256')
        return {key:item[key] for key in fields if key in item}

    def trust(self,project,identity,fingerprint):
        with self.lock:
            self.resolve(project,identity,fingerprint,False)
            values=self.trust_records()
            values=[v for v in values if v['id']!=identity]+[{'id':identity,'fingerprint':fingerprint}]
            atomic_json(self.path,values)
        return {'trusted':True,'id':identity,'fingerprint':fingerprint}
