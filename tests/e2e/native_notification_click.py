"""Opt-in real notification click exercise; user clicks macOS, never a fake delegate.

Run only after explicit authorization for artificial notification testing. On the
first run macOS may ask the user to allow SilicoLab notifications. The script
waits up to 180 seconds for an actual notification selection and native window.
It does not grant permission, automate settings, or answer the task question.
"""
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import Request,urlopen
from silicolab.desktop_lifecycle import ensure_service,gui_command,stop_service

with tempfile.TemporaryDirectory(prefix='silicolab-notification-click-') as directory:
    root=Path(directory);service=ensure_service(root,isolated_resources=True);origin=service['origin']
    def api(path,body=None):
        request=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=15) as response:return json.load(response)
    try:
        project=root/'project';project.mkdir();item=api('/projects',{'path':str(project),'name':'人工通知定位项目'});url='/projects/'+item['id']
        api(url+'/conversations',{'title':'不应定位的首个对话'})
        chat=api(url+'/conversations',{'title':'系统通知原待决定任务'})['id']
        status=api('/notifications',{'enabled':True})
        if status['authorization']!='authorized':raise AssertionError('macOS notification permission not granted; do not count click as passed')
        task=api(url+'/tasks',{'conversationId':chat,'requestId':'actual-click','goal':'PRIVATE_ARTIFICIAL_CONTENT_NOT_IN_NOTIFICATION','authorizedTools':[]})
        print('请打开macOS通知中心，点击“SilicoLab 需要你的决定”人工通知。不要答复问题；脚本只核对原项目与非首个对话定位。',flush=True)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            selection=root/'workbench-selection.json'
            if (root/'gui-session.json').exists() and selection.exists():
                selected=json.loads(selection.read_text())
                if selected=={'projectId':item['id'],'conversationId':chat}:break
            time.sleep(.1)
        else:raise AssertionError('Actual notification click/native selection was not observed')
        state=api(url);actual=state['tasks'][0]
        assert actual['id']==task['id'] and actual['decisions']==task['decisions']
        assert state['modelRequests']==0,'Notification selection must never answer/execute the task'
        report={'result':'passed','actualMacOSClickRequired':True,'nativeGuiOpenedOnlyAfterSelection':True,'sameProjectUUID':True,'sameNonfirstConversation':True,'sameTaskAndDecision':True,'noAutomaticAnswerOrModelRequest':True,'taskCardFocus':'inspect actual native UI separately; not inferred from selection file'}
        out=Path('outputs/native/notifications');out.mkdir(parents=True,exist_ok=True);(out/'click.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    finally:
        try:api('/notifications',{'enabled':False})
        finally:
            stop_service(root);gui_command(root,'close')
