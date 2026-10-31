"""Actual resource trust, connection/schema, controlled MCP tool result and refresh trust."""
from pathlib import Path
from playwright.sync_api import expect,sync_playwright
URL='http://127.0.0.1:8767';OUT=Path('outputs/ui/mcp');OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1480,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    fixture=page.request.get(URL+'/__test/mcp-fixture').json()
    project=page.request.post(URL+'/api/workbench/projects',data={'path':fixture['path'],'name':'MCP人工资源'}).json();url=URL+'/api/workbench/projects/'+project['id']
    page.request.post(url+'/conversations',data={'title':'信任不等于授权'})
    page.goto(URL,wait_until='networkidle');page.get_by_role('button',name='打开项目 MCP人工资源',exact=True).click();page.get_by_role('button',name='MCP资源',exact=True).click()
    resources=page.get_by_role('region',name='MCP资源目录')
    expect(resources).to_contain_text('不兼容，未启动');expect(resources).to_contain_text('已发现，待信任')
    assert page.request.get(URL+'/__test/mcp-fixture').json()['requests']==0
    local=resources.locator('li').filter(has=page.get_by_text('local',exact=True))
    local.get_by_role('button',name='确认此来源与权限边界',exact=True).click()
    expect(local).to_contain_text('来源已确认，尚未连接')
    pending=[]
    page.route('**/resources/mcp/*/connect',lambda route:pending.append(route))
    local.get_by_role('button',name='连接并核对 MCP schema',exact=True).click()
    expect(local).to_contain_text('正在连接')
    assert len(pending)==1
    pending[0].continue_()
    expect(local).to_contain_text('已连接，可显式调用',timeout=15000)
    expect(local).to_contain_text('"type": "object"')
    expect(local.get_by_role('button',name='调用已授权工具 echo',exact=True)).to_be_disabled()
    resources.get_by_label('明确授权所选工具及参数用于本任务，不授权科学提交或其他工具').check()
    local.get_by_role('button',name='调用已授权工具 echo',exact=True).click()
    page.get_by_role('button',name='MCP资源',exact=True).click()
    transcript=page.locator('.wb-transcript');expect(transcript).to_contain_text('MCP实际来源：project:.mcp.json',timeout=15000);expect(transcript).to_contain_text('ABC')
    task=page.request.get(url).json()['tasks'][0];assert task['toolExecutions'][0]['tool']=='mcp_call';assert task['toolExecutions'][0]['status']=='completed'
    assert page.request.get(URL+'/api/jobs').json()==[]
    page.screenshot(path=str(OUT/'trusted-tool-result.png'),full_page=True)
    page.reload(wait_until='domcontentloaded');page.get_by_role('button',name='MCP资源',exact=True).click()
    actual=page.request.get(url+'/resources/mcp').json()['resources'];assert next(r for r in actual if r['name']=='local')['status'] in ('trusted','callable')
    assert not errors,errors
    browser.close()
