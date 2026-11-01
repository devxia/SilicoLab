"""Explicit shipped resources and fixed internal worker commands."""
import os
from pathlib import Path
import shutil
import sys


def node_runtime():
    if getattr(sys,'frozen',False):
        root=(Path(sys._MEIPASS)/'runtime').resolve()
        return root,str(root/'bin/node')
    root=Path(os.environ.get('SILICOLAB_RUNTIME',Path(__file__).resolve().parents[3]/'runtime'))
    return root,os.environ.get('SILICOLAB_NODE') or shutil.which('node')


def backend_sources():
    return (Path(sys._MEIPASS)/'backend-src/silicolab').resolve() if getattr(sys,'frozen',False) else Path(__file__).resolve().parent


def worker_command(module,channel_fd=None):
    if module not in ('science_supervisor','science_worker','remote_science_worker'):raise ValueError('Unsupported internal scientific worker')
    if module=='science_supervisor' and (type(channel_fd) is not int or channel_fd<3):raise ValueError('Invalid supervisor descriptor')
    if getattr(sys,'frozen',False):
        return [sys.executable,'--science-supervisor',str(channel_fd)] if module=='science_supervisor' else [sys.executable,'--science-worker','remote' if module=='remote_science_worker' else 'local']
    script=f'import sys;sys.path.insert(0,sys.argv[1]);from silicolab.{module} import main;main('+('int(sys.argv[2])' if module=='science_supervisor' else '')+')'
    return [sys.executable,'-I','-B','-c',script,str(Path(__file__).resolve().parent.parent)]+([str(channel_fd)] if module=='science_supervisor' else [])
