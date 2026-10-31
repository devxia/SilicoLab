"""Resource catalog → description only → real read_skill tool → source persisted."""
from pathlib import Path
import json
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/skills')
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1480, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: external.append(r.url) if not r.url.startswith(URL) else None)
    path = page.request.get(URL + '/__test/skill-project').json()['path']
    project = page.request.post(URL + '/api/workbench/projects', data={'path': path, 'name': '人工技能目录'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    page.request.post(url + '/conversations', data={'title': '渐进读取与来源'})
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 人工技能目录', exact=True).click()
    page.get_by_role('button', name='技能资源', exact=True).click()
    catalog = page.get_by_role('region', name='技能资源目录')
    expect(catalog).to_contain_text('已发现，可按需加载')
    expect(catalog).to_contain_text('同名冲突，优先来源覆盖')
    expect(catalog).to_contain_text('格式或来源不兼容')
    expect(catalog).to_contain_text('project:.agents/skills')
    expect(catalog).not_to_contain_text('ARTIFICIAL_UI_PROJECT_BODY')
    page.screenshot(path=str(OUT / 'catalog.png'), full_page=True)
    page.get_by_role('button', name='技能资源', exact=True).click()
    page.get_by_label('研究目标草稿').fill('/skill artificial')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('技能已加载：artificial', timeout=15000)
    expect(transcript).to_contain_text('ARTIFICIAL_UI_PROJECT_BODY')
    expect(transcript).to_contain_text('知识内容不增加当前任务权限')
    expect(transcript).to_contain_text('project:.agents/skills')
    expect(transcript).to_contain_text('模型已答复')
    tasks = page.request.get(url).json()['tasks']
    assert [e['tool'] for e in tasks[0]['toolExecutions']] == ['read_skill']
    assert tasks[0]['authorizedTools'] == ['synthetic_count']
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 人工技能目录', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('技能已加载：artificial')
    page.get_by_role('button', name='技能资源', exact=True).click()
    expect(page.get_by_role('region', name='技能资源目录')).to_contain_text('已发现，可按需加载')
    assert page.request.get(URL + '/api/jobs').json() == []
    # Out-of-order source response must never replace the currently selected project's catalog.
    with tempfile.TemporaryDirectory(prefix='silicolab-skills-second-') as second:
        source = Path(second) / '.agents/skills/bravo'
        source.mkdir(parents=True)
        (source / 'SKILL.md').write_text('---\nname: bravo\ndescription: CURRENT_PROJECT_B_SOURCE\n---\nB_BODY')
        other = page.request.post(URL + '/api/workbench/projects', data={'path': second, 'name': '技能项目B'}).json()
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='打开项目 人工技能目录', exact=True).click()
        pending = []
        page.route(f'**/projects/{project["id"]}/resources/skills', lambda route: pending.append(route))
        page.get_by_role('button', name='技能资源', exact=True).click()
        page.wait_for_function("document.querySelector('.wb-skill-resources button')?.textContent.includes('正在检查')")
        page.get_by_role('button', name='打开项目 技能项目B', exact=True).click()
        expect(page.get_by_role('region', name='技能资源目录')).to_contain_text('CURRENT_PROJECT_B_SOURCE')
        assert len(pending) == 1
        pending[0].fulfill(status=200, content_type='application/json', body=json.dumps({'skills': [{'id': 'old-a', 'name': 'OLD_PROJECT_A_LATE_RESPONSE', 'source': 'late-a', 'path': '/artificial/a', 'status': 'available'}]}))
        expect(page.get_by_role('region', name='技能资源目录')).not_to_contain_text('OLD_PROJECT_A_LATE_RESPONSE')
        expect(page.get_by_role('region', name='技能资源目录')).to_contain_text('CURRENT_PROJECT_B_SOURCE')
    assert not errors, errors
    assert not external, external
    browser.close()
