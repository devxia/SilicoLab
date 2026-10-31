"""Real project/conversation persistence and accepted A+C navigation behavior."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/workbench')
OUT.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix='silicolab-ui-project-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1512, 'height': 940})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    page.goto(URL + '/#projects', wait_until='networkidle')
    page.get_by_role('button', name='创建项目', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('人工研究')
    dialog.get_by_label('项目目录', exact=True).fill(directory)
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='新建对话', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('对话名称').fill('第一条思路')
    dialog.get_by_role('button', name='确认', exact=True).click()
    draft = page.get_by_label('研究目标草稿')
    expect(draft).to_be_enabled()
    draft.fill('打开分析区也要保留这个草稿')
    page.get_by_role('button', name='查看结果', exact=True).click()
    expect(page.get_by_role('button', name='展开导航', exact=True)).to_be_visible()
    expect(draft).to_have_value('打开分析区也要保留这个草稿')
    page.get_by_role('button', name='展开导航', exact=True).click()
    page.get_by_role('tab', name='任务', exact=True).click()
    expect(page.get_by_role('button', name='收起导航', exact=True)).to_be_visible()
    page.get_by_role('button', name='关闭分析区', exact=True).click()
    expect(page.get_by_role('button', name='收起导航', exact=True)).to_be_visible()
    page.get_by_role('button', name='保存草稿', exact=True).click()
    expect(page.get_by_text('草稿已保存', exact=True)).to_be_visible()
    page.get_by_role('button', name='新建对话', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('对话名称').fill('另一条思路')
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(draft).to_have_value('')
    page.get_by_role('button', name='第一条思路', exact=True).click()
    expect(draft).to_have_value('打开分析区也要保留这个草稿')
    expect(page.locator('.wb-caption')).to_contain_text(directory)
    page.get_by_role('button', name='查看结果', exact=True).click()
    expect(page.get_by_role('tabpanel').locator('dd').first).to_contain_text(directory)
    page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
    # Restored conversations keep SSE open; readiness is the persisted UI below.
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 人工研究', exact=True).click()
    expect(draft).to_have_value('打开分析区也要保留这个草稿')
    response = page.request.get(URL + '/api/workbench/projects')
    identity = response.json()[0]['id']
    state = page.request.get(f'{URL}/api/workbench/projects/{identity}').json()
    assert len(state['conversations']) == 2 and not state['tasks'] and state['modelRequests'] == 0
    page.set_viewport_size({'width': 620, 'height': 850})
    if page.get_by_role('button', name='收起导航', exact=True).is_visible():
        page.get_by_role('button', name='收起导航', exact=True).click()
    page.get_by_role('button', name='展开导航', exact=True).click()
    expect(page.get_by_role('button', name='第一条思路', exact=True)).to_be_visible()
    page.screenshot(path=str(OUT / 'narrow-navigation.png'), full_page=True)
    page.get_by_role('link', name='ProteinFactory D2P 专项工作台', exact=True).click()
    expect(page.get_by_label('任务名称')).to_be_visible()
    page.get_by_role('link', name='返回项目与对话', exact=True).click()
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'projects': 1, 'conversations': 2, 'tasks': 0, 'external_requests': external, 'errors': errors, 'result': 'passed'}, ensure_ascii=False, indent=2))
    browser.close()
