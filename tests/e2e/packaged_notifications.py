"""Previously authorized artificial macOS notifications through the installed app."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from silicolab.decision_notifications import NativeNotifications
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).with_name('fixtures')))
from packaged_app import PackagedApp,wait,windows


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='silicolab-packaged-notifications-') as directory:
        root=Path(directory);owner=PackagedApp(args.app,root/'app-data')
        try:
            with patch('silicolab.decision_notifications.helper_app',return_value=owner.app/'Contents/Resources/notifications/SilicoLabNotifications.app'):
                center=NativeNotifications(lambda _:None)
                try:assert center.call('status')['authorization']==2,'Permission must already be granted; no enable/requestAuthorization was sent'
                finally:center.close()
            gui=owner.launch();project=root/'project';project.mkdir();p=owner.api('/projects',{'path':str(project),'name':'人工安装通知'});url='/projects/'+p['id'];chat=owner.api(url+'/conversations',{'title':'人工待决定'})['id']
            enabled=owner.api('/notifications',{'enabled':True});assert enabled['authorization']=='authorized','Requires previously granted user permission; do not modify system settings'
            assert owner.command('--close-window').returncode==0;gui.wait(timeout=15);assert not windows(gui.pid)
            from AppKit import NSWorkspace
            foreground=NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
            task=owner.api(url+'/tasks',{'conversationId':chat,'requestId':'packaged-notification','goal':'PRIVATE_ARTIFICIAL_SEQUENCE_NOT_IN_NOTICE','authorizedTools':[]})
            wait(lambda:owner.api('/notifications').get('delivered')==1)
            assert not (owner.directory/'gui-session.json').exists()
            assert NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()==foreground
            before=owner.api(url);assert before['modelRequests']==0 and before['tasks'][0]['decisions']==task['decisions']
            owner.api('/notifications',{'enabled':False});wait(lambda:owner.api('/notifications').get('delivered')==0)
            owner.launch();after=owner.api(url);assert after['tasks'][0]['decisions']==task['decisions'] and after['modelRequests']==0
            result={'status':'passed','installedNativeHelper':True,'actualDelivered':True,'noAutoWindowOrFocus':True,'disabledClears':True,'sameDecisionAfterReopen':True,'noModelRequest':True,'artificialOnly':True}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
        finally:
            try:
                if owner.info:owner.api('/notifications',{'enabled':False})
            finally:owner.close()


if __name__=='__main__':main()
