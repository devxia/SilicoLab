"""Artificial notification transport tests; never requests real OS permission."""
import json
import uuid
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app_fixture import create_app
from silicolab.decision_notifications import DecisionNotifications,TITLE,BODY


class ArtificialCenter:
    def __init__(self,selected,granted=True):self.selected=selected;self.granted=granted;self.calls=[];self.authorization=0
    def call(self,op,**values):
        self.calls.append((op,values))
        if op=='enable':self.authorization=2 if self.granted else 1;return {'granted':self.granted}
        if op=='status':return {'authorization':self.authorization,'delivered':[]}
        return {'submitted':True,'removed':True}
    def close(self):pass


class DecisionNotificationTests(unittest.TestCase):
    def test_pending_identity_survives_disable_denial_reconnect_and_repeat_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();app=create_app(root/'app.sqlite3',delay=0);activations=[];centers=[]
            def factory(selected):
                center=ArtificialCenter(selected);center.authorization=2;centers.append(center);return center
            with TestClient(app) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'sensitive artificial sequence chat'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'notify','goal':'PRIVATE_ARTIFICIAL_SEQUENCE_DO_NOT_NOTIFY','authorizedTools':[]}).json()
                original=client.get(url).json();decision=task['decisions'][0]
                notices=DecisionNotifications(app.state.workbench,root,factory,activations.append)
                notices.scan();self.assertEqual(centers,[])
                notices.configure(True);notices.scan();notices.scan()
                calls=[c for c in centers[0].calls if c[0]=='notify'];self.assertEqual(len(calls),1)
                target=calls[0][1]['target'];self.assertEqual(set(target),{'projectId','conversationId','taskId','decisionId'})
                self.assertEqual(target['decisionId'],decision['id']);self.assertNotIn('PRIVATE_ARTIFICIAL',str(calls)+TITLE+BODY)
                self.assertEqual(activations,[])
                notices.close()
                reopened=DecisionNotifications(app.state.workbench,root,factory,activations.append)
                reopened.scan();self.assertEqual(len([c for center in centers for c in center.calls if c[0]=='notify']),1)
                self.assertTrue(reopened.selected(target));self.assertEqual(activations,[target]);self.assertEqual(reopened.consume(),target);self.assertEqual(reopened.consume(),target)
                # Selection survives reader/background replacement; an older ack cannot delete a newer click.
                reattached=DecisionNotifications(app.state.workbench,root,factory,activations.append)
                self.assertEqual(reattached.consume(),target)
                task2=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'new-click','goal':'artificial','authorizedTools':[]}).json()
                target2={**target,'taskId':task2['id'],'decisionId':task2['decisions'][0]['id']}
                self.assertTrue(reopened.selected(target2))
                self.assertFalse(reopened.acknowledge(target)['acknowledged']);self.assertEqual(reopened.consume(),target2)
                self.assertTrue(reopened.acknowledge(target2)['acknowledged']);self.assertIsNone(reopened.consume())
                reopened.configure(False);reopened.scan();self.assertFalse(reopened.status()['enabled'])
                body={'answer':'grant'};answer=url+f'/tasks/{task["id"]}/decisions/{decision["id"]}'
                response=client.post(answer,json=body);self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(client.post(answer,json=body).json(),response.json())
                self.assertEqual(client.get(url).json()['modelRequests'],original['modelRequests'])
                self.assertFalse(reopened.selected(target));reopened.close()

    def test_notification_observation_does_not_open_inactive_projects_or_take_host_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);database=root/'app.sqlite3'
            for index in range(5):
                project=root/str(index);project.mkdir()
                with TestClient(create_app(database,delay=0)) as client:
                    item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                    chat=client.post(url+'/conversations',json={'title':str(index)}).json()['id']
                    client.post(url+'/tasks',json={'conversationId':chat,'requestId':'pending','goal':'artificial','authorizedTools':[]})
            app=create_app(database,delay=0)
            with TestClient(app) as client:
                from unittest.mock import patch
                with patch.object(app.state.workbench,'open',side_effect=AssertionError('notification must not silently open indexed projects')):
                    notices=DecisionNotifications(app.state.workbench,root,lambda selected:ArtificialCenter(selected))
                    self.assertEqual(notices.status()['pending'],0)
                    notices.configure(True);notices.scan();notices.close()
                # Normal explicit opening still has the full bounded capacity available.
                for index in range(4):
                    response=client.post('/api/workbench/projects/open',json={'path':str(root/str(index))})
                    self.assertEqual(response.status_code,200,response.text)

    def test_notification_routes_preserve_origin_boundary_and_reject_untrusted_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=create_app(root/'app.sqlite3',delay=0);created=[];activated=[]
            def factory(selected):
                created.append(True);return ArtificialCenter(selected,False)
            notices=DecisionNotifications(app.state.workbench,root,factory,activated.append);app.state.workbench.notifications=notices
            with TestClient(app) as client:
                response=client.post('/api/workbench/notifications',json={'enabled':True},headers={'Origin':'https://untrusted.invalid'})
                self.assertEqual(response.status_code,403);self.assertEqual(created,[])
                self.assertEqual(client.post('/api/workbench/notifications',json={'enabled':'true'}).status_code,409)
                self.assertFalse(notices.selected({'projectId':'not-uuid','conversationId':'1','taskId':'x','decisionId':'x'}));self.assertEqual(activated,[])
                result=client.post('/api/workbench/notifications',json={'enabled':True})
                self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['authorization'],'denied')
                self.assertIsNone(client.post('/api/workbench/notifications/selection',json={}).json())
                self.assertEqual(client.post('/api/workbench/notifications',json={'enabled':False}).status_code,200)
            notices.close()

    def test_obsolete_cleanup_is_batched_and_each_success_persisted_before_retry(self):
        class BoundedCenter(ArtificialCenter):
            def __init__(self,selected):super().__init__(selected);self.authorization=2;self.removals=0
            def call(self,op,**values):
                if op=='remove':
                    self.removals+=1
                    if len(values['identifiers'])>200:raise ValueError('helper rejects more than 200 IDs')
                    if self.removals==2:raise ValueError('artificial second batch failure')
                return super().call(op,**values)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();app=create_app(root/'app.sqlite3',delay=0)
            old={str(uuid.uuid4()):'submitted' for _ in range(201)}
            (root/'notification-state.json').write_text(json.dumps({'enabled':True,'sent':old}))
            with TestClient(app) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id'];chat=client.post(url+'/conversations',json={'title':'batch retry'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'new','goal':'artificial','authorizedTools':[]}).json()
                notices=DecisionNotifications(app.state.workbench,root,BoundedCenter);notices.scan()
                saved=json.loads((root/'notification-state.json').read_text())
                self.assertEqual(list(saved['sent'].values()).count('cleared'),200)
                notices.scan();saved=json.loads((root/'notification-state.json').read_text())
                self.assertEqual(list(saved['sent'].values()).count('cleared'),201)
                self.assertEqual(saved['sent'][task['decisions'][0]['id']],'submitted')
                self.assertEqual(len([c for c in notices.center.calls if c[0]=='notify']),1)
                notices.close()

    def test_failed_native_transport_reconnects_without_new_permission_or_repeat_admitted_notice(self):
        class FailingCenter(ArtificialCenter):
            def __init__(self,selected):super().__init__(selected);self.authorization=2;self.failed=False;self.closed=False
            def call(self,op,**values):
                if self.failed:raise BrokenPipeError('artificial EOF')
                return super().call(op,**values)
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();app=create_app(root/'app.sqlite3',delay=0);centers=[]
            def factory(selected):
                center=FailingCenter(selected);centers.append(center);return center
            with TestClient(app) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id'];chat=client.post(url+'/conversations',json={'title':'transport recovery'}).json()['id']
                one=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'one','goal':'artificial','authorizedTools':[]}).json()
                notices=DecisionNotifications(app.state.workbench,root,factory);notices.configure(True)
                centers[0].failed=True
                two=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'two','goal':'artificial','authorizedTools':[]}).json()
                notices.scan();notices.scan()
                self.assertEqual(len(centers),2)
                self.assertTrue(centers[0].closed)
                self.assertFalse(any(op=='enable' for op,_ in centers[1].calls))
                calls=[v['target']['decisionId'] for center in centers for op,v in center.calls if op=='notify']
                self.assertEqual(calls,[one['decisions'][0]['id'],two['decisions'][0]['id']])
                # A disable after EOF must also clear already delivered OS notices.
                centers[1].failed=True
                self.assertEqual(notices.status()['authorization'],'unavailable')
                self.assertIsNone(notices.center)
                notices.configure(False)
                self.assertEqual(len(centers),3)
                self.assertIn('disable',[op for op,_ in centers[2].calls])
                self.assertFalse(any(op=='enable' for op,_ in centers[2].calls))
                self.assertFalse(notices.status()['enabled'])
                notices.close()

    def test_denied_notifications_leave_exact_durable_problem_visible_without_send_or_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();app=create_app(root/'app.sqlite3',delay=0);centers=[];activations=[]
            def factory(selected):
                center=ArtificialCenter(selected,False);centers.append(center);return center
            with TestClient(app) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id'];chat=client.post(url+'/conversations',json={'title':'denied'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'denied','goal':'artificial','authorizedTools':[]}).json()
                notices=DecisionNotifications(app.state.workbench,root,factory,activations.append);result=notices.configure(True);notices.scan()
                self.assertEqual(result['authorization'],'denied');self.assertFalse(any(c[0]=='notify' for c in centers[0].calls));self.assertEqual(activations,[])
                actual=client.get(url+'/conversations/'+chat).json()['tasks'][0]
                self.assertEqual(actual['decisions'],task['decisions']);self.assertEqual(actual['status'],'needs_decision');self.assertEqual(actual.get('modelRequests',[]),[])
                notices.close()


if __name__=='__main__':unittest.main()
