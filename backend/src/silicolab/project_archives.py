"""Versioned managed project state and quiescent, hash-verified archives.

No project execution, credential lookup or application-index ownership lives here.
Callers hold the project lease across every snapshot/migration operation.
"""
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager,closing
from pathlib import Path
import stat
import uuid
from silicolab.desktop_lifecycle import atomic_json

VERSION=2
FORMAT='silicolab-project'


@contextmanager
def regular_stream(path,limit):
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('项目记录不支持符号链接')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise ValueError('项目记录须为有界普通文件')
        with os.fdopen(fd,'rb',closefd=False) as stream:yield stream,before
        after=os.fstat(fd)
        if (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns):raise ValueError('项目记录读取期间改变')
    finally:os.close(fd)


def read_regular(path,limit):
    with regular_stream(path,limit) as (stream,before):
        content=stream.read(limit+1)
        if len(content)>limit or len(content)!=before.st_size:raise ValueError('项目记录读取期间改变或超限')
        return content


def execution_contract(runtime,backend):
    """Public shipped source/lock identities, not local paths or model configuration."""
    runtime=Path(runtime);backend=Path(backend)
    import importlib.metadata
    import platform
    import sys
    import sysconfig
    identities={'backend-environment':{
        'python':sys.version,'implementation':sys.implementation.name,'cacheTag':sys.implementation.cache_tag,
        'platform':sysconfig.get_platform(),'machine':platform.machine(),
        'packages':{name:importlib.metadata.version(name) for name in ('openpyxl','et-xmlfile','httpx','fastapi','uvicorn')},
    }}
    sources=[('runtime/'+p.relative_to(runtime).as_posix(),p) for p in sorted((runtime/'src').glob('*.ts'))]
    sources += [('backend/'+p.relative_to(backend).as_posix(),p) for p in sorted(backend.rglob('*')) if p.is_file() and p.suffix in ('.py','.json','.xlsx')]
    sources += [('runtime/package-lock.json',runtime/'package-lock.json')]
    lock=runtime.parent/'tools/python-runtime/runtime-lock.json'
    if lock.is_file():sources.append(('analysis/runtime-lock.json',lock))
    inventory=runtime.parent/'release/PythonBoundaryProbe-manifest.json'
    if inventory.is_file():sources.append(('analysis/runtime-inventory.json',inventory))
    for name,path in sources:identities[name]=hashlib.sha256(read_regular(path,MAX_FILE)).hexdigest()
    return hashlib.sha256(json.dumps(identities,sort_keys=True).encode()).hexdigest()


def write_format(state,project_id):
    marker={'format':FORMAT,'version':VERSION,'projectId':project_id}
    atomic_json(Path(state)/'project-format.json',marker)
    return marker


def check_format(state):
    try:marker=json.loads(read_regular(Path(state)/'project-format.json',65536))
    except FileNotFoundError:return {'format':FORMAT,'version':1}
    except (OSError,ValueError):raise ValueError('项目版本记录损坏；保留原数据，请从完整备份恢复') from None
    if not isinstance(marker,dict) or marker.get('format')!=FORMAT or type(marker.get('version')) is not int or marker['version'] not in (1,VERSION):raise ValueError('项目状态版本不兼容；未启动宿主或修改原数据，请使用对应版本应用')
    if 'projectId' in marker:
        try:uuid.UUID(marker['projectId'])
        except (ValueError,TypeError,AttributeError):raise ValueError('项目版本记录身份损坏') from None
    return marker


MAX_FILE=128*1024*1024
MAX_TOTAL=512*1024*1024
MAX_FILES=10000
ROOTS={'files','inputs','outputs','runs'}


def internal_database(name):
    parts=name.split('/')
    return name=='session.sqlite' or (len(parts)==3 and parts[0]=='runs' and parts[-1]=='session.sqlite')


def sqlite_sidecar(name):
    parts=name.split('/')
    return (len(parts)==1 or parts[0]=='runs') and parts[-1] in ('session.sqlite-wal','session.sqlite-shm','session.sqlite-journal')


def managed_name(name):
    parts=name.split('/')
    if not parts or any(not part or part in ('.','..') or '\\' in part or any(ord(c)<32 for c in part) for part in parts):return False
    return name in ('session.sqlite','project-format.json') or (parts[0] in ROOTS and len(parts)>1 and not sqlite_sidecar(name))


def tree_files(state):
    """Enumerate only application-managed state, never arbitrary project/config files."""
    found={}
    def walk(folder):
        for path in sorted(folder.iterdir()):
            relative=path.relative_to(state).as_posix();info=path.lstat()
            if relative=='owner.lock':
                if not stat.S_ISREG(info.st_mode):raise ValueError('项目所有者锁不是普通文件')
                continue
            if stat.S_ISDIR(info.st_mode):
                if relative.split('/')[0] not in ROOTS:raise ValueError('未知项目状态目录；未静默省略')
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                if sqlite_sidecar(relative):continue
                if not managed_name(relative):raise ValueError('未知项目状态文件；未静默省略')
                if info.st_size>MAX_FILE or len(found)>=MAX_FILES:raise ValueError('项目备份文件数量或大小超限')
                found[relative]=path
            else:raise ValueError('项目备份不支持链接/设备/FIFO')
    walk(state)
    if 'session.sqlite' not in found:raise ValueError('项目状态库缺失')
    if sum(p.stat().st_size for p in found.values())>MAX_TOTAL:raise ValueError('项目备份总大小超限')
    return found


def sqlite_snapshot(source,target):
    # All application writers are stopped while the caller retains owner.lock.
    read_regular(source,MAX_FILE)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as database:
        if database.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('项目SQLite完整性不符')
        with closing(sqlite3.connect(target)) as output:database.backup(output)
    target.chmod(0o600)


def create_archive(state,snapshot,destination):
    state=Path(state);destination=Path(destination).parent.resolve()/Path(destination).name
    if destination.is_symlink() or destination.exists() or not destination.parent.is_dir() or destination.parent.resolve()!=destination.parent.absolute():raise ValueError('备份须使用存在目录中的新文件路径，不覆盖原件或跟随链接')
    if state==destination.parent or state in destination.parents:raise ValueError('备份不能写入项目状态目录')
    files=tree_files(state);check_format(state)
    manifest={'format':'silicolab-backup','version':1,'projectId':snapshot['id'],'files':{}}
    fd,temporary=tempfile.mkstemp(prefix='.silicolab-backup-',suffix='.tmp',dir=destination.parent)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='silicolab-sqlite-snapshot-') as directory,zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for index,(name,path) in enumerate(files.items()):
                if internal_database(name):
                    target=Path(directory).resolve()/str(index);sqlite_snapshot(path,target);data=read_regular(target,MAX_FILE)
                else:data=read_regular(path,MAX_FILE)
                key='.silicolab/'+name;manifest['files'][key]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                archive.writestr(key,data)
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True))
        if set(tree_files(state))!=set(files):raise ValueError('项目备份期间文件集合改变')
        with open(temporary,'rb') as stream:os.fsync(stream.fileno())
        os.link(temporary,destination)  # Atomic publication without overwrite.
        return {'projectId':snapshot['id'],'path':str(destination),'files':len(files),'sha256':hashlib.sha256(read_regular(destination,MAX_TOTAL)).hexdigest()}
    finally:Path(temporary).unlink(missing_ok=True)


@contextmanager
def unpack_archive(archive_path,target):
    """Validate everything in staging; caller verifies the real project before publication."""
    target=Path(target)
    if not target.is_dir() or target.is_symlink() or target.resolve()!=target.absolute() or any(target.iterdir()):raise ValueError('恢复目标须为现有空普通目录，不覆盖原项目')
    # Retain one regular-file descriptor while ZIP validates and extracts entries.
    path=Path(archive_path).parent.resolve()/Path(archive_path).name
    try:
        with regular_stream(path,MAX_TOTAL) as (stream,_),zipfile.ZipFile(stream) as archive,tempfile.TemporaryDirectory(prefix='.silicolab-restore-',dir=target.parent) as directory:
            entries=archive.infolist();names=[i.filename for i in entries]
            if len(names)!=len(set(names)) or len(names)>MAX_FILES+1 or sum(i.file_size for i in entries)>MAX_TOTAL or any(i.file_size>MAX_FILE or i.flag_bits&1 or i.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) or stat.S_ISLNK(i.external_attr>>16) for i in entries):raise ValueError('项目备份条目/大小/链接不兼容')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>4*1024*1024:raise ValueError('项目备份清单缺失或超限')
            manifest=json.loads(archive.read('manifest.json'))
            if not isinstance(manifest,dict) or manifest.get('format')!='silicolab-backup' or type(manifest.get('version')) is not int or manifest['version']!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('项目备份清单格式不兼容')
            try:uuid.UUID(manifest['projectId'])
            except (KeyError,ValueError,TypeError,AttributeError):raise ValueError('项目备份身份缺失或不合法') from None
            if set(names)!={'manifest.json',*manifest['files']} or '.silicolab/session.sqlite' not in manifest['files']:raise ValueError('项目备份清单与条目不匹配')
            stage=Path(directory)
            for name,record in manifest['files'].items():
                if not name.startswith('.silicolab/') or not managed_name(name[len('.silicolab/'):]) or not isinstance(record,dict) or set(record)!={'size','sha256'}:raise ValueError('项目备份路径或清单记录不兼容')
                data=archive.read(name)
                if type(record['size']) is not int or len(data)!=record['size'] or hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('项目备份内容哈希/大小不符')
                output=stage/name;output.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
                with output.open('xb') as handle:handle.write(data)
                output.chmod(0o600)
            check_format(stage/'.silicolab')
            for name in manifest['files']:
                if not internal_database(name[len('.silicolab/'):]):continue
                file=stage/name
                with closing(sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)) as db:
                    if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('恢复状态库完整性不符')
            yield stage,manifest
    except (zipfile.BadZipFile,sqlite3.DatabaseError,KeyError,TypeError) as error:raise ValueError('项目备份损坏或清单不兼容；原件保留') from error
