"""Quit the independent service, fresh-process reopen, task-only recovery UI."""
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import Request,urlopen
from playwright.sync_api import expect,sync_playwright
from silicolab.desktop_lifecycle import ensure_service,stop_service

OUT=Path('outputs/ui/full-quit');OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-quit-browser-') as directory,sync_playwright() as p:
    root=Path(directory);origin=ensure_service(root,isolated_resources=True)['origin']
    def api(path,body=None):
        req=Request(origin+'/api/workbench'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=12) as r:return json.load(r)
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1480,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        path=root/'project';path.mkdir();project=api('/projects',{'path':str(path),'name':'完全退出恢复验证'});url='/projects/'+project['id']
        first=api(url+'/conversations',{'title':'original paused chat'})['id'];second=api(url+'/conversations',{'title':'waiting other chat'})['id']
        waiting=api(url+'/tasks',{'conversationId':second,'requestId':'wait','goal':'need permission','authorizedTools':[]})
        running=api(url+'/tasks',{'conversationId':first,'requestId':'run','goal':'ABC','authorizedTools':['synthetic_count']})
        queued=api(url+'/tasks',{'conversationId':first,'requestId':'queued','goal':'DEF','authorizedTools':['synthetic_count']})
        stop_service(root)
        origin=ensure_service(root,isolated_resources=True)['origin']
        api('/projects/open',{'path':str(path)})
        page.goto(origin,wait_until='networkidle')
        page.get_by_role('button',name='打开项目 完全退出恢复验证',exact=True).click()
        recovery=page.get_by_role('region',name='项目待处理与恢复项')
        expect(recovery).to_contain_text('3 项待处理或待选择恢复')
        recovery.locator('summary').click()
        expect(recovery).to_contain_text('不发起模型')
        page.get_by_role('button',name='模型设置',exact=True).click()
        expect(page.get_by_role('region',name='应用模型设置')).to_be_visible()
        recovery.get_by_role('button',name='查看原任务 '+waiting['id'][:8],exact=True).click()
        expect(page.get_by_role('region',name='应用模型设置')).not_to_be_visible()
        waitcard=page.locator('.wb-transcript').get_by_role('region',name='任务 '+waiting['id'],exact=True)
        expect(waitcard).to_be_visible()
        expect(waitcard).to_be_focused()
        expect(page.locator('.wb-header')).to_contain_text('waiting other chat')
        expect(page.locator('.wb-transcript')).to_contain_text('需要用户决定')
        saved=api(url);before=saved['modelRequests']
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('.wb-header')).to_contain_text('waiting other chat')
        assert api(url)['modelRequests']==before
        page.get_by_role('region',name='项目待处理与恢复项').locator('summary').click()
        page.get_by_role('button',name='技能资源',exact=True).click()
        expect(page.get_by_role('region',name='技能资源目录')).to_be_visible()
        page.get_by_role('button',name='查看原任务 '+queued['id'][:8],exact=True).click()
        expect(page.get_by_role('region',name='技能资源目录')).not_to_be_visible()
        expect(page.locator('.wb-header')).to_contain_text('original paused chat')
        card=page.locator('.wb-transcript').get_by_role('region',name='任务 '+queued['id'],exact=True)
        expect(card).to_be_focused()
        page.get_by_role('button',name='查看原任务 '+running['id'][:8],exact=True).click()
        expect(page.locator('.wb-transcript').get_by_role('region',name='任务 '+running['id'],exact=True)).to_be_focused()
        page.get_by_role('button',name='查看原任务 '+queued['id'][:8],exact=True).click()
        expect(card).to_be_focused()
        assert api(url)['modelRequests']==before
        card.get_by_role('button',name='恢复此任务',exact=True).click()
        expect(card).to_contain_text('模型已答复',timeout=15000)
        selfstate=api(url)
        assert next(t for t in selfstate['tasks'] if t['id']==running['id'])['status']=='paused'
        assert next(t for t in selfstate['tasks'] if t['id']==waiting['id'])['decisions']==waiting['decisions']
        page.screenshot(path=str(OUT/'selected-recovery.png'),full_page=True)
        assert not errors,errors
    finally:
        browser.close();stop_service(root)
