"""Queue states and ordinary UI submissions do not bypass project serial execution."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/project-queue')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-queue-ui-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1470, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '项目串行队列'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '三个明确目标'}).json()['id']
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 项目串行队列', exact=True).click()
    page.get_by_label('研究目标草稿').fill('AAA')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('正在执行')
    page.get_by_label('研究目标草稿').fill('BBBB')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('已排队，等待项目执行位置')
    page.get_by_label('研究目标草稿').fill('CCCCC')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-transcript .wb-task-card')).to_have_count(3)
    page.screenshot(path=str(OUT / 'queue.png'), full_page=True)
    expect(page.locator('.wb-transcript .wb-task-card').filter(has_text='模型已答复')).to_have_count(3, timeout=15000)
    state = page.request.get(url + '/conversations/' + chat).json()
    tasks = state['tasks']
    assert [task['goal'] for task in tasks] == ['AAA', 'BBBB', 'CCCCC']
    assert [task['toolExecutions'][0]['result']['characters'] for task in tasks] == [3, 4, 5]
    assert all(task['finishedAt'] <= tasks[index + 1]['startedAt'] for index, task in enumerate(tasks[:-1]))
    before = state['modelRequests']
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 项目串行队列', exact=True).click()
    expect(page.locator('.wb-transcript .wb-task-card').filter(has_text='模型已答复')).to_have_count(3)
    assert page.request.get(url + '/conversations/' + chat).json()['modelRequests'] == before
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'fifo_tasks': 3, 'single_execution_each': True, 'reconnect_no_resubmit': True, 'external': external, 'errors': errors}, indent=2))
    browser.close()
