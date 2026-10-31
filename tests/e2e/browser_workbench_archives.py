"""Project recovery UI operates through the same consistent archive application contract."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect,sync_playwright
URL='http://127.0.0.1:8767'
with tempfile.TemporaryDirectory(prefix='silicolab-archive-ui-') as directory,sync_playwright() as p:
    root=Path(directory);project=root/'project';project.mkdir();target=root/'restored';target.mkdir();archive=root/'archive.zip'
    browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1480,'height':1000})
    item=page.request.post(URL+'/api/workbench/projects',data={'path':str(project),'name':'人工恢复项目'}).json();url=URL+'/api/workbench/projects/'+item['id']
    chat=page.request.post(url+'/conversations',data={'title':'原必要决定'}).json()['id']
    task=page.request.post(url+'/tasks',data={'conversationId':chat,'requestId':'waiting','goal':'必须保留的待决定项','authorizedTools':[]}).json()
    page.goto(URL,wait_until='networkidle');page.get_by_role('button',name='打开项目 人工恢复项目',exact=True).click()
    page.get_by_role('button',name='项目恢复',exact=True).click()
    panel=page.get_by_role('region',name='项目备份与恢复')
    panel.get_by_label('新备份 ZIP 路径',exact=True).fill(str(archive));panel.get_by_role('button',name='创建一致备份',exact=True).click()
    expect(panel).to_contain_text('一致备份已保存',timeout=15000)
    assert archive.is_file()
    # Association removal is explicit and never deletes the original project.
    page.get_by_role('button',name='移除项目关联',exact=True).click()
    expect(page.get_by_role('button',name='打开项目 人工恢复项目',exact=True)).not_to_be_visible()
    panel.get_by_label('备份 ZIP 路径',exact=True).fill(str(archive));panel.get_by_label('现有空恢复目录',exact=True).fill(str(target))
    panel.get_by_role('button',name='核验并恢复原项目',exact=True).click()
    expect(page.get_by_role('main')).to_contain_text('原项目已恢复；未自动执行',timeout=15000)
    expect(page.locator('.wb-header')).to_contain_text('人工恢复项目')
    recovery=page.get_by_role('region',name='项目待处理与恢复项');expect(recovery).to_contain_text('1 项待处理或待选择恢复')
    state=page.request.get(url).json();assert state['id']==item['id'];assert state['modelRequests']==0
    assert state['tasks'][0]['id']==task['id'];assert state['tasks'][0]['status']=='needs_decision'
    assert (project/'.silicolab/session.sqlite').is_file()
    out=Path('outputs/ui/project-archives');out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/'restored-original.png'),full_page=True)
    # A restore can complete after the user leaves its view: it must not steal B/draft.
    page.get_by_role('button',name='移除项目关联',exact=True).click()
    bpath=root/'project-b';bpath.mkdir();b=page.request.post(URL+'/api/workbench/projects',data={'path':str(bpath),'name':'后来选择B'}).json()
    page.request.post(URL+'/api/workbench/projects/'+b['id']+'/conversations',data={'title':'B的草稿'})
    page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='项目恢复',exact=True).click()
    panel=page.get_by_role('region',name='项目备份与恢复');other=root/'restored-again';other.mkdir()
    panel.get_by_label('备份 ZIP 路径',exact=True).fill(str(archive));panel.get_by_label('现有空恢复目录',exact=True).fill(str(other))
    pending=[]
    def hold_response(route):
        response=route.fetch();pending.append((route,response));page.evaluate('window.__archiveResponseReady=true')
    page.route('**/projects/restore',hold_response)
    panel.get_by_role('button',name='核验并恢复原项目',exact=True).click()
    page.wait_for_function('window.__archiveResponseReady===true')
    page.get_by_role('button',name='项目恢复',exact=True).click()
    page.get_by_role('button',name='打开项目 后来选择B',exact=True).click()
    draft=page.get_by_label('研究目标草稿',exact=True);draft.fill('B未保存草稿，迟到恢复不能覆盖')
    pending[0][0].fulfill(response=pending[0][1])
    expect(page.locator('.wb-header')).to_contain_text('后来选择B')
    expect(draft).to_have_value('B未保存草稿，迟到恢复不能覆盖')
    # Let React process the released completion before asserting selection again.
    page.get_by_role('button',name='查看任务',exact=True).click()
    expect(page.locator('.wb-header')).to_contain_text('后来选择B')
    expect(draft).to_have_value('B未保存草稿，迟到恢复不能覆盖')
    browser.close()
