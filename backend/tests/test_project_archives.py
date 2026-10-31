"""Public project lifecycle tests with artificial state, no real provider or credentials."""
import base64
import hashlib
import json
import time
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app_fixture import create_app
import zipfile
from test_workbench_science import wait_task
from test_workbench_recovery import wait_state
from test_model_configuration import MemorySecrets,FakeModelEndpoint


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_archive(source,destination,transform):
    with zipfile.ZipFile(source) as archive:parts={n:archive.read(n) for n in archive.namelist() if n!='manifest.json'};manifest=json.loads(archive.read('manifest.json'))
    transform(parts)
    manifest['files']={n:{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for n,data in parts.items()}
    with zipfile.ZipFile(destination,'w') as archive:
        for name,data in parts.items():archive.writestr(name,data)
        archive.writestr('manifest.json',json.dumps(manifest))


def mutate_ledger(parts,update,database_key='.silicolab/session.sqlite',kind='silicolab.tasks'):
    # Deliberately corrupt only a copied artificial archive via the real durable API.
    import subprocess
    with tempfile.TemporaryDirectory() as directory:
        database=Path(directory)/'session.sqlite';database.write_bytes(parts[database_key])
        script="""import {BACKGROUND_CONTEXT as ctx} from '@earendil-works/chord/context';
import {Harness,defineDoc,createRegistry} from '@earendil-works/pi-durable';
import {createModels} from '@earendil-works/pi-ai/models';
import {openNodeSqliteStorage} from '@earendil-works/pi-durable/storage/sqlite/node';
const kind=process.argv[3];
const ledger=defineDoc({kind,version:1,scope:'session',initial:()=>({tasks:[],modelRequests:0}),checkpointWhen:()=>true});
const host=await Harness.open(await openNodeSqliteStorage(process.argv[1]),{models:createModels(),registry:createRegistry()},ctx);
try{await host.commit(async tx=>{const doc=await tx.doc(ledger);Object.assign(kind==='silicolab.tasks'?doc.tasks[0]:doc,JSON.parse(process.argv[2]));},ctx);}finally{await host.close(ctx);}
"""
        subprocess.run(['node','--input-type=module','-e',script,str(database),json.dumps(update),kind],cwd='runtime',check=True,capture_output=True,text=True,timeout=15)
        parts[database_key]=database.read_bytes()


class ProjectArchiveTests(unittest.TestCase):
    def test_quiescent_backup_restore_preserves_committed_inputs_tasks_and_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();destination=root/'restored';destination.mkdir();archive=root/'project-backup.zip'
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0,credential_store=MemorySecrets())) as client:
                opened=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+opened['id']
                chat=client.post(url+'/conversations',json={'title':'archive artificial chat'}).json()['id']
                client.put(url+f'/conversations/{chat}/draft',json={'text':'keep this committed draft','revision':0})
                imported=client.post(url+'/files',json={'name':'artificial.fasta','contentBase64':base64.b64encode(b'>one\nK*\n').decode()}).json()
                fixed=client.post(url+'/input-versions',json={'conversationId':chat,'fileIds':[imported['id']]}).json()
                body={'conversationId':chat,'requestId':'scientific','goal':'explicit artificial D2P local','workflow':'d2p_local','specialtyAcknowledged':True,'inputVersionId':fixed['id'],'parameters':{'stopPolicy':'preserve','avoid':''},'authorizedTools':['d2p_local']}
                task=client.post(url+'/tasks',json=body).json();done=wait_task(client,url,chat,task['id'])
                waiting=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'waiting','goal':'keep this necessary decision','authorizedTools':[]}).json()
                before=client.get(url).json()
                response=client.post(url+'/backup',json={'path':str(archive)})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(archive.is_file());self.assertEqual(response.json()['projectId'],opened['id'])
                with zipfile.ZipFile(archive) as bundle:
                    names=bundle.namelist();self.assertNotIn('.silicolab/owner.lock',names)
                    self.assertFalse(any(n.endswith(('-wal','-shm')) or 'model-configs' in n or 'mcp-trust' in n for n in names))
                    manifest=json.loads(bundle.read('manifest.json'))
                    for name,record in manifest['files'].items():
                        content=bundle.read(name);self.assertEqual(hashlib.sha256(content).hexdigest(),record['sha256']);self.assertEqual(len(content),record['size'])
                removed=client.delete(url);self.assertEqual(removed.status_code,200,removed.text)
                restored=client.post('/api/workbench/projects/restore',json={'archivePath':str(archive),'path':str(destination)})
                self.assertEqual(restored.status_code,201,restored.text);state=restored.json()
                self.assertEqual(state['id'],before['id']);self.assertEqual(state['conversations'],before['conversations'])
                self.assertEqual(state['inputVersions'],before['inputVersions']);self.assertEqual(state['tasks'],before['tasks'])
                self.assertEqual(state['modelRequests'],before['modelRequests'])
                self.assertEqual(client.get(url+'/input-versions/'+fixed['id']).json(),fixed)
                actual=client.get(url+f'/conversations/{chat}').json()['tasks']
                self.assertEqual(next(t for t in actual if t['id']==waiting['id'])['status'],'needs_decision')
                execution=done['toolExecutions'][0]
                for artifact in execution['artifacts']:
                    content=client.get(url+f'/tasks/{done["id"]}/artifacts/{execution["id"]}/{artifact["name"]}').content
                    self.assertEqual(hashlib.sha256(content).hexdigest(),artifact['sha256'])
                self.assertTrue((project/'.silicolab/session.sqlite').is_file())

    def test_explicit_legacy_upgrade_keeps_full_rollback_archive_and_no_automatic_work(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir()
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'legacy pending'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'legacy-wait','goal':'needs decision','authorizedTools':[]}).json()
            (project/'.silicolab/project-format.json').unlink()
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                legacy=client.post('/api/workbench/projects/open',json={'path':str(project)}).json()
                self.assertEqual(legacy['stateFormat'],1)
                failed_archive=root/'before-failed-upgrade.zip'
                with patch('silicolab.project_archives.atomic_json',side_effect=OSError('artificial marker disk full')):
                    failed=client.post(url+'/upgrade',json={'path':str(failed_archive)})
                self.assertEqual(failed.status_code,409,failed.text);self.assertTrue(failed_archive.is_file())
                self.assertFalse((project/'.silicolab/project-format.json').exists())
                after_failure=client.get(url).json();self.assertEqual(after_failure['tasks'],legacy['tasks'])
                self.assertEqual(after_failure['modelRequests'],legacy['modelRequests'])
                archive=root/'before-upgrade.zip'
                result=client.post(url+'/upgrade',json={'path':str(archive)})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['upgradedFrom'],1);self.assertEqual(result.json()['stateFormat'],2)
                current=client.get(url).json();self.assertEqual(current['stateFormat'],2)
                self.assertEqual(current['tasks'],legacy['tasks']);self.assertEqual(current['conversations'],legacy['conversations'])
                self.assertEqual(current['modelRequests'],legacy['modelRequests'])
                with zipfile.ZipFile(archive) as bundle:self.assertNotIn('.silicolab/project-format.json',bundle.namelist())
                self.assertEqual(next(t for t in current['tasks'] if t['id']==task['id'])['status'],'needs_decision')

    def test_changed_execution_contract_blocks_explicit_resume_without_new_model_or_tool(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir()
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'versioned execution'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'pause-contract','goal':'ABC','authorizedTools':['synthetic_count']}).json()
                wait_state(client,url+f'/conversations/{chat}',lambda s:any(t['id']==task['id'] and t['toolExecutions'] for t in s['tasks']))
                paused=client.post(url+f'/tasks/{task["id"]}/pause');self.assertEqual(paused.status_code,200,paused.text)
            with patch('silicolab.project_archives.execution_contract',return_value='b'*64,create=True),TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                client.post('/api/workbench/projects/open',json={'path':str(project)})
                before=client.get(url).json();result=client.post(url+f'/tasks/{task["id"]}/resume')
                self.assertEqual(result.status_code,409,result.text);self.assertIn('版本',result.json()['detail'])
                after=client.get(url).json()
                self.assertEqual(after['modelRequests'],before['modelRequests']);self.assertEqual(after['tasks'],before['tasks'])

    def test_active_backup_refused_and_restored_paused_tasks_remain_individually_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();target=root/'restored';target.mkdir();archive=root/'paused.zip'
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'selective restore'}).json()['id']
                first=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'one','goal':'A'*3000,'authorizedTools':['synthetic_count']}).json()
                second=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'two','goal':'DEF','authorizedTools':['synthetic_count']}).json()
                denied=client.post(url+'/backup',json={'path':str(archive)})
                self.assertEqual(denied.status_code,409,denied.text);self.assertFalse(archive.exists())
                for task in (second,first):self.assertEqual(client.post(url+f'/tasks/{task["id"]}/pause').status_code,200)
                self.assertEqual(client.post(url+'/backup',json={'path':str(archive)}).status_code,200)
                original=client.get(url).json()
                duplicate=client.post('/api/workbench/projects/restore',json={'archivePath':str(archive),'path':str(target)})
                self.assertEqual(duplicate.status_code,409,duplicate.text);self.assertEqual(list(target.iterdir()),[])
                self.assertEqual(client.delete(url).status_code,200)
                restored=client.post('/api/workbench/projects/restore',json={'archivePath':str(archive),'path':str(target)})
                self.assertEqual(restored.status_code,201,restored.text)
                time.sleep(.25)
                self.assertEqual(client.get(url).json()['modelRequests'],original['modelRequests'])
                self.assertEqual(client.post(url+f'/tasks/{second["id"]}/resume').status_code,200)
                done=wait_task(client,url,chat,second['id']);self.assertEqual(done['status'],'answered')
                state=client.get(url).json();self.assertEqual(next(t for t in state['tasks'] if t['id']==first['id'])['status'],'paused')

    def test_corrupt_archive_and_path_traversal_leave_empty_target_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();target=root/'target';target.mkdir();archive=root/'good.zip'
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0),raise_server_exceptions=False) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                self.assertEqual(client.post(url+'/backup',json={'path':str(archive)}).status_code,200)
                before=digest(archive)
                with zipfile.ZipFile(archive) as good:parts={n:good.read(n) for n in good.namelist()}
                for mode in ('hash','traversal','symlink','brokenzip'):
                    bad=root/(mode+'.zip')
                    if mode=='brokenzip':bad.write_bytes(b'not a zip file')
                    else:
                        contents=dict(parts);manifest=json.loads(contents['manifest.json'])
                        if mode=='hash':contents['.silicolab/session.sqlite']=b'changed'
                        if mode=='traversal':
                            contents['../escaped']=b'bad';manifest['files']['../escaped']={'size':3,'sha256':hashlib.sha256(b'bad').hexdigest()}
                            contents['manifest.json']=json.dumps(manifest).encode()
                        with zipfile.ZipFile(bad,'w') as bundle:
                            for name,data in contents.items():
                                if mode=='symlink' and name=='.silicolab/session.sqlite':
                                    info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=0o120777<<16;bundle.writestr(info,data)
                                else:bundle.writestr(name,data)
                    result=client.post('/api/workbench/projects/restore',json={'archivePath':str(bad),'path':str(target)})
                    self.assertEqual(result.status_code,409,(mode,result.text));self.assertEqual(list(target.iterdir()),[])
                    self.assertFalse((root/'escaped').exists());self.assertEqual(digest(archive),before)

    def test_real_previous_release_upgrade_and_restore_keeps_models_scripts_and_attempt_associations(self):
        import sys
        sys.path.insert(0,str(Path('tests/e2e/fixtures').resolve()))
        from project_archive_previous import create_previous_project
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'previous';before=create_previous_project(project)
            item=before['project'];url='/api/workbench/projects/'+item['id'];archive=root/'pre-upgrade.zip';target=root/'restored';target.mkdir()
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                opened=client.post('/api/workbench/projects/open',json={'path':str(project)})
                self.assertEqual(opened.status_code,200,opened.text);self.assertEqual(opened.json()['stateFormat'],1)
                self.assertEqual(opened.json()['tasks'],item['tasks']);self.assertEqual(opened.json()['conversations'],item['conversations'])
                upgrade=client.post(url+'/upgrade',json={'path':str(archive)});self.assertEqual(upgrade.status_code,200,upgrade.text)
                self.assertEqual(client.delete(url).status_code,200)
                restored=client.post('/api/workbench/projects/restore',json={'archivePath':str(archive),'path':str(target)})
                self.assertEqual(restored.status_code,201,restored.text)
                state=restored.json();self.assertEqual(state['id'],item['id']);self.assertEqual(state['modelRequests'],item['modelRequests'])
                self.assertEqual(state['tasks'],item['tasks']);self.assertEqual(state['conversations'],item['conversations'])
                for chat,old in before['chats'].items():
                    actual=client.get(url+'/conversations/'+chat).json()
                    self.assertEqual(actual['entries'],old['entries']);self.assertEqual(actual['tasks'],old['tasks'])
                resumed=client.post(url+'/tasks/'+before['pausedTaskId']+'/resume')
                self.assertEqual(resumed.status_code,409,resumed.text);self.assertIn('版本',resumed.json()['detail'])
                self.assertEqual(client.get(url).json()['modelRequests'],item['modelRequests'])
                with zipfile.ZipFile(archive) as bundle:
                    self.assertFalse(any(b'artificial-archive-key' in bundle.read(n) for n in bundle.namelist()))

    def test_backup_retains_cross_process_owner_lease_until_archive_publication(self):
        import threading
        from unittest.mock import patch
        from silicolab.project_archives import create_archive
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();entered=threading.Event();release=threading.Event();answer=[]
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as first,TestClient(create_app(root/'other'/'app.sqlite3',delay=0)) as second:
                item=first.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                def held(*args):entered.set();self.assertTrue(release.wait(10));return create_archive(*args)
                with patch('silicolab.project_archives.create_archive',held):
                    thread=threading.Thread(target=lambda:answer.append(first.post(url+'/backup',json={'path':str(root/'held.zip')})));thread.start()
                    try:
                        self.assertTrue(entered.wait(5))
                        blocked=second.post('/api/workbench/projects/open',json={'path':str(project)})
                        self.assertEqual(blocked.status_code,409,blocked.text)
                    finally:release.set();thread.join(10)
                self.assertFalse(thread.is_alive());self.assertEqual(answer[0].status_code,200,answer[0].text)

    def test_sqlite_named_user_inputs_roundtrip_as_original_bytes_not_internal_databases(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();target=root/'restored';target.mkdir();archive=root/'inputs.zip'
            original=root/'actual.sqlite'
            with closing(sqlite3.connect(original)) as db:db.execute('create table artificial (value)');db.commit()
            contents={'sample.sqlite':b'not a SQLite database\n','actual.sqlite':original.read_bytes()}
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                for name,data in contents.items():
                    result=client.post(url+'/files',json={'name':name,'contentBase64':base64.b64encode(data).decode()});self.assertEqual(result.status_code,201,result.text)
                response=client.post(url+'/backup',json={'path':str(archive)});self.assertEqual(response.status_code,200,response.text)
                with zipfile.ZipFile(archive) as bundle:
                    for name,data in contents.items():
                        entry=next(n for n in bundle.namelist() if n.endswith('-'+name))
                        self.assertEqual(bundle.read(entry),data)
                self.assertEqual(client.delete(url).status_code,200)
                result=client.post('/api/workbench/projects/restore',json={'archivePath':str(archive),'path':str(target)})
                self.assertEqual(result.status_code,201,result.text)
                for imported in result.json()['files']:self.assertEqual((target/imported['path']).read_bytes(),contents[imported['name']])

    def test_actual_backend_dependency_change_blocks_resume_with_same_source_and_locks(self):
        from unittest.mock import patch
        import importlib.metadata
        version=importlib.metadata.version
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir()
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'backend environment'}).json()['id']
                held=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'held-env','goal':'ABC'*1000,'authorizedTools':['synthetic_count']}).json()
                self.assertEqual(client.post(url+f'/tasks/{held["id"]}/pause').status_code,200)
            def changed(name):return '999.0-artificial' if name=='openpyxl' else version(name)
            with patch('importlib.metadata.version',changed),TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                state=client.post('/api/workbench/projects/open',json={'path':str(project)}).json()
                result=client.post(url+f'/tasks/{held["id"]}/resume')
                self.assertEqual(result.status_code,409,result.text)
                self.assertIn('版本',result.json()['detail'])
                self.assertEqual(client.get(url).json()['modelRequests'],state['modelRequests'])
                self.assertEqual(client.get(url).json()['tasks'],state['tasks'])

    def test_missing_checkpoint_or_wrong_submission_archive_is_not_restored_as_empty_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();target=root/'restored';target.mkdir();good=root/'good.zip'
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'checkpoint association'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'complete','goal':'ABC','authorizedTools':['synthetic_count']}).json();wait_task(client,url,chat,task['id'])
                self.assertEqual(client.post(url+'/backup',json={'path':str(good)}).status_code,200);self.assertEqual(client.delete(url).status_code,200)
                for mode in ('missing','submission','owner'):
                    with self.subTest(mode=mode):
                        bad=root/(mode+'.zip');target=root/('restore-'+mode);target.mkdir()
                        def change(parts):
                            if mode=='missing':
                                for name in list(parts):
                                    if name.startswith('.silicolab/runs/'):del parts[name]
                            elif mode=='owner':
                                key=next(n for n in parts if n.startswith('.silicolab/runs/') and n.endswith('/session.sqlite'))
                                mutate_ledger(parts,{'taskId':'00000000-0000-0000-0000-000000000001'},key,'silicolab.execution-owner')
                            else:mutate_ledger(parts,{'submissionId':999999})
                        rewrite_archive(good,bad,change)
                        result=client.post('/api/workbench/projects/restore',json={'archivePath':str(bad),'path':str(target)})
                        if result.status_code==201:client.delete(url)
                        self.assertEqual(result.status_code,409,result.text);self.assertEqual(list(target.iterdir()),[])

    def test_archive_database_task_id_cannot_write_outside_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir();target=root/'restored';target.mkdir();good=root/'good.zip';bad=root/'bad.zip'
            with TestClient(create_app(root/'app'/'app.sqlite3',delay=0)) as client:
                item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                chat=client.post(url+'/conversations',json={'title':'database path guard'}).json()['id']
                task=client.post(url+'/tasks',json={'conversationId':chat,'requestId':'complete','goal':'ABC','authorizedTools':['synthetic_count']}).json();wait_task(client,url,chat,task['id'])
                self.assertEqual(client.post(url+'/backup',json={'path':str(good)}).status_code,200);self.assertEqual(client.delete(url).status_code,200)
                rewrite_archive(good,bad,lambda parts:mutate_ledger(parts,{'id':'../../../escaped','status':'running','isolatedExecution':True}))
                result=client.post('/api/workbench/projects/restore',json={'archivePath':str(bad),'path':str(target)})
                self.assertFalse((root/'escaped').exists(),'untrusted database wrote outside restore staging')
                self.assertEqual(result.status_code,409,result.text)
                self.assertEqual(list(target.iterdir()),[])

    def test_pending_recovery_request_keeps_original_checkpoint_identity_through_queue_and_reopen(self):
        for action in ('reopen','paused-backup'):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as directory,FakeModelEndpoint('openai-responses','artificial-original-failure',['invalid_key','normal']) as failed,FakeModelEndpoint('anthropic-messages','artificial-blocking-model','hold') as held:
                root=Path(directory);project=root/'project';project.mkdir();secrets=MemorySecrets();database=root/'app'/'app.sqlite3'
                with TestClient(create_app(database,delay=0,credential_store=secrets)) as client:
                    item=client.post('/api/workbench/projects',json={'path':str(project)}).json();url='/api/workbench/projects/'+item['id']
                    chats=[client.post(url+'/conversations',json={'title':title}).json()['id'] for title in ('failed A','holding B')]
                    for chat,endpoint in zip(chats,(failed,held)):
                        config=client.post('/api/workbench/model-configs',json={'name':chat,'protocol':endpoint.protocol,'baseUrl':endpoint.url,'modelId':'artificial','apiKey':endpoint.key}).json()
                        self.assertEqual(client.put(url+f'/conversations/{chat}/model',json={'configurationId':config['id']}).status_code,200)
                    a=client.post(url+'/tasks',json={'conversationId':chats[0],'requestId':'A','goal':'ABC','authorizedTools':['synthetic_count']}).json()
                    paused=wait_state(client,url+f'/conversations/{chats[0]}',lambda s:s['tasks'][0]['status']=='paused')['tasks'][0]
                    b=client.post(url+'/tasks',json={'conversationId':chats[1],'requestId':'B','goal':'DEF','authorizedTools':['synthetic_count']}).json()
                    self.assertTrue(held.entered.wait(5))
                    queued=client.post(url+f'/tasks/{a["id"]}/resume');self.assertEqual(queued.status_code,200,queued.text)
                    self.assertEqual(queued.json()['status'],'queued');self.assertEqual(queued.json()['submissionId'],paused['submissionId'])
                    if action=='paused-backup':
                        self.assertEqual(client.post(url+f'/tasks/{a["id"]}/pause').status_code,200)
                        self.assertEqual(client.post(url+f'/tasks/{b["id"]}/pause').status_code,200)
                        backup=client.post(url+'/backup',json={'path':str(root/'queued-recovery.zip')})
                        self.assertEqual(backup.status_code,200,backup.text)
                with TestClient(create_app(database,delay=0,credential_store=secrets)) as client:
                    reopened=client.post('/api/workbench/projects/open',json={'path':str(project)})
                    self.assertEqual(reopened.status_code,200,reopened.text)
                    actual=next(t for t in reopened.json()['tasks'] if t['id']==a['id'])
                    self.assertEqual(actual['status'],'paused');self.assertEqual(actual['submissionId'],paused['submissionId'])
                    self.assertEqual(len(failed.requests),1)
                    held.release.set()
                    self.assertEqual(client.post(url+f'/tasks/{a["id"]}/resume').status_code,200)
                    finished=wait_task(client,url,chats[0],a['id'])
                    self.assertNotEqual(finished['submissionId'],paused['submissionId'])
                    self.assertEqual(finished['submissionRequestId'],finished['recoveryRequestId'])
                    self.assertEqual(finished['status'],'answered')

    def test_unknown_future_format_is_rejected_before_open_and_original_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir()
            with TestClient(create_app(root/'app.sqlite3',delay=0)) as client:
                opened=client.post('/api/workbench/projects',json={'path':str(project)}).json()
            state=project/'.silicolab';database=state/'session.sqlite'
            marker=state/'project-format.json';marker.write_text(json.dumps({'format':'silicolab-project','version':999,'projectId':opened['id']}))
            before={p.name:digest(p) for p in state.iterdir() if p.is_file()}
            with TestClient(create_app(root/'fresh'/'app.sqlite3',delay=0)) as client:
                response=client.post('/api/workbench/projects/open',json={'path':str(project)})
                self.assertEqual(response.status_code,409,response.text)
                self.assertIn('版本',response.json()['detail'])
                self.assertEqual(client.get('/api/workbench/projects').json(),[])
            self.assertEqual({p.name:digest(p) for p in state.iterdir() if p.is_file()},before)
            self.assertTrue(database.is_file())


if __name__=='__main__':unittest.main()
