"""Real streamed loop, persisted output, and reload/reconnect without resubmission."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/agent-loop')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-agent-ui-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1450, 'height': 1000})
    errors, external, submissions = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else submissions.append(request.url) if request.method == 'POST' and request.url.endswith('/tasks') else None)
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='创建项目', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('真实工具循环')
    dialog.get_by_label('项目目录', exact=True).fill(directory)
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='新建对话', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('对话名称', exact=True).fill('人工文本验证')
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_label('研究目标草稿').fill('ABC')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-task-card').first).to_contain_text('synthetic_count')
    # Reattach while the tool/run is live; this must only open another observer.
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 真实工具循环', exact=True).click()
    expect(page.locator('.wb-task-card').first).to_contain_text('实际字符数：3', timeout=10000)
    expect(page.locator('.wb-task-card').first).to_contain_text('模型已答复', timeout=10000)
    expect(page.locator('.wb-transcript')).to_contain_text('本机人工文本计数已生成可检查结果')
    page.locator('.wb-tool-execution summary').first.click()
    page.screenshot(path=str(OUT / 'completed.png'), full_page=True)
    identity = page.request.get(URL + '/api/workbench/projects').json()[0]['id']
    url = f'{URL}/api/workbench/projects/{identity}'
    state = page.request.get(url).json()
    task = state['tasks'][0]
    attempts = task['toolExecutions']
    chat = state['conversations'][0]['id']
    assert len(attempts) == 1
    assert json.loads((Path(directory) / attempts[0]['artifact']['path']).read_text())['result'] == {'characters': 3}
    assert len(submissions) == 1
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 真实工具循环', exact=True).click()
    expect(page.locator('.wb-task-card').first).to_contain_text('实际字符数：3')
    expect(page.locator('.wb-transcript')).to_contain_text('本机人工文本计数已生成可检查结果')
    assert len(submissions) == 1
    saved = page.request.get(url + '/conversations/' + chat).json()
    assert saved['tasks'][0]['toolExecutions'] == attempts
    assert saved['modelRequests'] == 2
    page.get_by_role('button', name='查看任务', exact=True).click()
    expect(page.get_by_role('tabpanel')).to_contain_text('synthetic_count')
    failure_project = Path(directory) / 'failure-project'
    failure_project.mkdir()
    page.get_by_role('button', name='展开导航', exact=True).click()
    page.get_by_role('button', name='创建项目', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('产物失败验证')
    dialog.get_by_label('项目目录', exact=True).fill(str(failure_project))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='新建对话', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('对话名称', exact=True).fill('不伪装完成')
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    (failure_project / '.silicolab/outputs').write_text('artificial obstacle')
    page.get_by_label('研究目标草稿').fill('ABC')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('工具执行失败', timeout=10000)
    expect(page.locator('.wb-transcript')).to_contain_text('模型已答复', timeout=10000)
    expect(page.locator('.wb-transcript .wb-tool-execution [role=alert]')).to_be_visible()
    expect(page.locator('.wb-transcript')).not_to_contain_text('工具执行中')
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 产物失败验证', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('工具执行失败')
    expect(page.locator('.wb-transcript')).not_to_contain_text('工具执行中')
    assert len(submissions) == 2
    assert (failure_project / '.silicolab/outputs').read_text() == 'artificial obstacle'
    assert not external, external
    assert not errors, errors
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'successful_task_submissions': 1, 'total_submissions_including_failure_case': len(submissions), 'executions': len(attempts), 'model_requests': saved['modelRequests'], 'external': external, 'errors': errors}, indent=2))
    browser.close()
