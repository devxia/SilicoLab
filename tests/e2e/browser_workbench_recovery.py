"""Pause/resume is confirmed by real execution, with reload remaining passive."""
import base64
import json
from pathlib import Path
import tempfile
import time
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/task-recovery')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-recovery-ui-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1470, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '暂停与选择恢复'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '保留完成项'}).json()['id']
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 暂停与选择恢复', exact=True).click()
    page.get_by_label('研究目标草稿').fill('ABC')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('工具已完成', timeout=10000)
    transcript.get_by_role('button', name='暂停本机任务', exact=True).click()
    expect(transcript).to_contain_text('已暂停，等待选择恢复', timeout=10000)
    state = page.request.get(url + '/conversations/' + chat).json()
    paused = state['tasks'][0]
    assert paused['status'] == 'paused'
    assert paused['toolExecutions'][0]['status'] == 'completed'
    attempts = paused['toolExecutions']
    calls = state['modelRequests']
    time.sleep(0.15)
    assert page.request.get(url + '/conversations/' + chat).json()['modelRequests'] == calls
    page.screenshot(path=str(OUT / 'paused.png'), full_page=True)
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 暂停与选择恢复', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('已暂停，等待选择恢复')
    assert page.request.get(url + '/conversations/' + chat).json()['modelRequests'] == calls
    page.get_by_role('button', name='查看任务', exact=True).click()
    panel = page.get_by_role('tabpanel')
    expect(panel).to_contain_text('暂停原因')
    panel.get_by_role('button', name='恢复此任务', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('模型已答复', timeout=10000)
    restored = page.request.get(url + '/conversations/' + chat).json()
    assert restored['tasks'][0]['id'] == paused['id']
    assert restored['tasks'][0]['toolExecutions'] == attempts
    assert page.request.post(url + '/tasks/' + paused['id'] + '/resume').json()['toolExecutions'] == attempts
    page.screenshot(path=str(OUT / 'resumed.png'), full_page=True)
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'same_task': True, 'completed_attempt_reused': True, 'reload_did_not_resume': True, 'external': external, 'errors': errors}, indent=2))
    browser.close()
