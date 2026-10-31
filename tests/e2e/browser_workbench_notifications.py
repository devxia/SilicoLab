"""Notification UI/selection uses an independent service; OS permission stays disabled."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect,sync_playwright
from silicolab.desktop_lifecycle import ensure_service,stop_service

with tempfile.TemporaryDirectory(prefix='silicolab-notifications-ui-') as directory,sync_playwright() as p:
    root=Path(directory);service=ensure_service(root,isolated_resources=True);origin=service['origin']
    browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1480,'height':1000})
    try:
        def api(path,data=None):
            response=page.request.post(origin+'/api/workbench'+path,data=data) if data is not None else page.request.get(origin+'/api/workbench'+path)
            assert response.ok,response.text();return response.json()
        project=root/'project';project.mkdir();item=api('/projects',{'path':str(project),'name':'通知原项目'});url='/projects/'+item['id']
        decoy=api(url+'/conversations',{'title':'不是原问题'})['id'];chat=api(url+'/conversations',{'title':'原问题对话'})['id']
        task=api(url+'/tasks',{'conversationId':chat,'requestId':'ui-notify','goal':'artificial awaiting decision','authorizedTools':[]})
        # Native bridge presence is UI-only; this test does NOT claim native delivery/click.
        selection={'projectId':item['id'],'conversationId':decoy}
        page.add_init_script('window.pywebview={api:{bootstrap:async()=>({desktop:true,draft:null,selection:'+json.dumps(selection)+'}),desktop_status:async()=>({connected:true,backgroundPid:1}),save_selection:async()=>true}};')
        page.goto(origin+'/?silicolabDesktop=1',wait_until='domcontentloaded')
        expect(page.get_by_role('complementary',name='系统提醒设置')).to_contain_text('已关闭')
        expect(page.locator('.wb-header')).to_contain_text('不是原问题')
        # Return a source-validated target only at the public selection boundary.
        target={'projectId':item['id'],'conversationId':chat,'taskId':task['id'],'decisionId':task['decisions'][0]['id']};remaining=[target]
        # A one-shot target polled during a real busy draft save must not be lost.
        draft=page.get_by_label('研究目标草稿',exact=True);draft.fill('artificial busy notification draft')
        held=[];page.route('**/draft',lambda route:held.append(route))
        page.get_by_role('button',name='保存草稿',exact=True).click()
        page.wait_for_function("[...document.querySelectorAll('button')].some(b=>b.textContent==='保存草稿'&&b.disabled)")
        polled=[];acknowledgments=[]
        def choose(route):
            polled.append(True);route.fulfill(json=remaining[-1] if remaining else None)
        def acknowledge(route):
            received=route.request.post_data_json;acknowledgments.append(received)
            matched=bool(remaining and remaining[-1]==received)
            if matched:remaining.clear()
            route.fulfill(json={'acknowledged':matched})
        page.route('**/notifications/selection',choose)
        page.route('**/notifications/selection/ack',acknowledge)
        # Observe that a notification poll actually occurred while saving.
        page.wait_for_timeout(1700);assert polled and len(held)==1
        held[0].continue_()
        expect(page.locator('.wb-header')).to_contain_text('原问题对话',timeout=10000)
        card=page.locator('.wb-transcript').get_by_role('region',name='任务 '+task['id'],exact=True)
        expect(card).to_be_focused();expect(card).to_contain_text('需要用户决定')
        assert api(url)['modelRequests']==0
        # A transient save failure retains the new target until navigation succeeds.
        task2=api(url+'/tasks',{'conversationId':decoy,'requestId':'ui-transient','goal':'artificial second decision','authorizedTools':[]})
        target2={**target,'conversationId':decoy,'taskId':task2['id'],'decisionId':task2['decisions'][0]['id']}
        acknowledgments.clear()
        draft.fill('artificial draft retained after transient error')
        page.unroute('**/draft');attempts=[]
        def transient(route):
            attempts.append(True)
            if len(attempts)==1:route.fulfill(status=409,json={'detail':'artificial transient save failure'})
            else:route.continue_()
        page.route('**/draft',transient);remaining.append(target2)
        expect(page.get_by_role('alert')).to_contain_text('artificial transient save failure',timeout=10000)
        assert acknowledgments==[]
        expect(page.locator('.wb-header')).to_contain_text('不是原问题',timeout=10000)
        expect(page.locator('.wb-transcript').get_by_role('region',name='任务 '+task2['id'],exact=True)).to_be_focused()
        assert len(attempts)==2 and acknowledgments==[target2]
        assert next(c for c in api(url)['conversations'] if c['id']==chat)['draft']=='artificial draft retained after transient error'
        assert api(url)['modelRequests']==0
        # A cached click becomes invalid while busy; the newer durable click must replace it.
        old=api(url+'/tasks',{'conversationId':chat,'requestId':'superseded-click','goal':'artificial old click','authorizedTools':[]})
        new=api(url+'/tasks',{'conversationId':chat,'requestId':'replacement-click','goal':'artificial replacement','authorizedTools':[]})
        old_target={**target,'taskId':old['id'],'decisionId':old['decisions'][0]['id']}
        new_target={**target,'taskId':new['id'],'decisionId':new['decisions'][0]['id']}
        page.unroute('**/draft');held.clear();polled.clear();acknowledgments.clear()
        page.route('**/draft',lambda route:held.append(route))
        draft.fill('artificial superseded click draft');page.get_by_role('button',name='保存草稿',exact=True).click()
        remaining.append(old_target)
        page.wait_for_timeout(1700);assert polled and len(held)==1
        api(url+'/tasks/'+old['id']+'/decisions/'+old['decisions'][0]['id'],{'answer':'decline'})
        remaining[:]=[new_target];held[0].continue_()
        expect(page.locator('.wb-transcript').get_by_role('region',name='任务 '+new['id'],exact=True)).to_be_focused(timeout=10000)
        assert new_target in acknowledgments and remaining==[]
        remaining.append(old_target)
        expect(page.get_by_role('alert')).to_contain_text('原决定已处理，已清除这次过期通知定位',timeout=10000)
        assert old_target in acknowledgments and remaining==[]
        assert api(url)['modelRequests']==0
        out=Path('outputs/ui/notifications');out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/'original-decision.png'),full_page=True)
    finally:browser.close();stop_service(root)
