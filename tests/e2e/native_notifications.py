"""Real native helper delivery/disable/close with artificial pending tasks.

Requires explicit user-granted SilicoLab notification permission. Does not grant
permission or automate system settings. Notification clicking is a separate
manual/native evidence step; this script never fabricates delegate selection.
"""
import json
import os
import signal
from pathlib import Path
import tempfile
import time
from urllib.request import Request,urlopen
from AppKit import NSWorkspace
from silicolab.desktop_lifecycle import ensure_service,stop_service


def wait(predicate,seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Native notification condition not observed')


OUT=Path('outputs/native/notifications');OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-native-notifications-') as directory:
    root=Path(directory);service=ensure_service(root,isolated_resources=True);origin=service['origin']
    def api(path,body=None):
        req=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=15) as response:return json.load(response)
    try:
        project=root/'project';project.mkdir();item=api('/projects',{'path':str(project),'name':'artificial native notification'});url='/projects/'+item['id']
        chat=api(url+'/conversations',{'title':'sensitive artificial title excluded'})['id']
        enabled=api('/notifications',{'enabled':True});assert enabled['authorization']=='authorized','Permission must be granted by the user before this test'
        foreground=NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
        task=api(url+'/tasks',{'conversationId':chat,'requestId':'native-notify','goal':'PRIVATE_ARTIFICIAL_SEQUENCE_NEVER_NOTIFY','authorizedTools':[]})
        first=wait(lambda:state if (state:=api('/notifications')).get('delivered')==1 else None)
        assert first['pending']==1
        helper_pid=first['nativePid'];assert helper_pid
        assert not (root/'gui-session.json').exists(),'Delivery opened a window without user selection'
        assert NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()==foreground,'Notification delivery stole foreground focus'
        before=api(url);assert before['tasks'][0]['decisions']==task['decisions'];assert before['modelRequests']==0
        # Bounded observation verifies stable delivery admission, not another call.
        time.sleep(1.3)
        state=json.loads((root/'notification-state.json').read_text());assert list(state['sent'].values())==['submitted']
        assert 'PRIVATE_ARTIFICIAL_SEQUENCE' not in (root/'notification-state.json').read_text()
        # Terminate only this test service's owned helper, then observe real reconnection.
        os.kill(helper_pid,signal.SIGTERM)
        recovered=wait(lambda:status if (status:=api('/notifications')).get('nativePid') not in (None,helper_pid) else None)
        assert recovered['authorization']=='authorized' and recovered['delivered']==1
        try:os.kill(helper_pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('Failed helper PID was not reaped')
        helper_pid=recovered['nativePid']
        assert json.loads((root/'notification-state.json').read_text())['sent']==state['sent']
        api('/notifications',{'enabled':False})
        wait(lambda:api('/notifications').get('delivered')==0)
        second=api(url+'/tasks',{'conversationId':chat,'requestId':'disabled-notify','goal':'artificial second','authorizedTools':[]})
        time.sleep(1.3)
        assert api('/notifications')['delivered']==0
        api('/notifications',{'enabled':True})
        wait(lambda:api('/notifications').get('delivered')==1)
        after=api(url);assert after['modelRequests']==0
        assert [t['decisions'] for t in after['tasks']]==[task['decisions'],second['decisions']]
        api('/notifications',{'enabled':False})
        wait(lambda:api('/notifications').get('delivered')==0)
        result={'result':'passed','nativeBundle':'com.silicolab.notifications','realMacOSDelivery':True,'noWindowWithoutClick':True,'noFocusSteal':True,'helperCrashReconnectedWithoutRepeat':True,'noModelRequestWhileWaiting':True,'durableDecisionUnchanged':True,'disableClearsDelivered':True,'disabledNewDecisionNoDelivery':True,'reenableDoesNotRepeatOldDecision':True,'artificialDataOnly':True,'clickScope':'separate manual click + real Cocoa focused task evidence'}
        (OUT/'automated-delivery.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        try:api('/notifications',{'enabled':False})
        finally:stop_service(root)
        try:os.kill(helper_pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('Native notification helper survived service stop')
