"""Durable task questions, UI replies and no execution while awaiting a decision."""
import base64
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/task-decisions')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-decisions-ui-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1460, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '等待必要决定'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '终止符由我决定'}).json()['id']
    source = b'>one\nMK\n'
    imported = page.request.post(url + '/files', data={'name': 'no-stop.fa', 'contentBase64': base64.b64encode(source).decode()}).json()
    fixed = page.request.post(url + '/input-versions', data={'conversationId': chat, 'fileIds': [imported['id']]}).json()
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 等待必要决定', exact=True).click()
    page.get_by_role('button', name='D2P 专项本地实验', exact=True).click()
    form = page.get_by_role('region', name='D2P 专项本地实验任务')
    form.get_by_label('固定输入版本').select_option(fixed['id'])
    expect(form.get_by_label('终止符策略')).to_have_value('ask')
    form.get_by_label('我明确使用 D2P 专项的本地实验，不使用远端').check()
    form.get_by_role('button', name='运行 D2P 专项本地实验', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('需要用户决定')
    expect(transcript.get_by_label('任务待决定事项')).to_contain_text('没有末尾终止符')
    waiting = page.request.get(url + '/conversations/' + chat).json()
    assert waiting['modelRequests'] == 0
    assert waiting['tasks'][0]['toolExecutions'] == []
    question_id = waiting['tasks'][0]['decisions'][0]['id']
    page.screenshot(path=str(OUT / 'waiting.png'), full_page=True)
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 等待必要决定', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('没有末尾终止符')
    saved = page.request.get(url + '/conversations/' + chat).json()
    assert saved['tasks'][0]['decisions'][0]['id'] == question_id
    assert saved['modelRequests'] == 0
    task_id = waiting['tasks'][0]['id']
    continue_url = url + '/tasks/' + task_id + '/continue'
    def fail_admission(route):
        route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '人工模拟：答复已保存，提交暂不可用'}))
    page.route(continue_url, fail_admission)
    transcript.get_by_role('button', name='为本任务补充末尾 *', exact=True).click()
    expect(transcript).to_contain_text('答复已保存，等待明确继续')
    expect(transcript.get_by_role('button', name='继续已答复任务', exact=True)).to_be_visible()
    expect(transcript).to_contain_text('提交暂不可用')
    page.unroute(continue_url, fail_admission)
    saved_answer = page.request.get(url + '/conversations/' + chat).json()
    assert saved_answer['modelRequests'] == 0
    assert saved_answer['tasks'][0]['decisions'][0]['answer'] == 'add'
    assert 'submissionId' not in saved_answer['tasks'][0]
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 等待必要决定', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript.get_by_role('button', name='继续已答复任务', exact=True)).to_be_visible()
    assert page.request.get(url + '/conversations/' + chat).json()['modelRequests'] == 0
    transcript.get_by_role('button', name='继续已答复任务', exact=True).click()
    expect(transcript).to_contain_text('one · 已校验', timeout=15000)
    expect(transcript).to_contain_text('已答复：为本任务补充末尾 *')
    expect(transcript).to_contain_text('模型已答复', timeout=10000)
    finished = page.request.get(url + '/conversations/' + chat).json()
    task = finished['tasks'][0]
    assert task['id'] == waiting['tasks'][0]['id']
    assert len(task['toolExecutions']) == 1
    assert task['toolExecutions'][0]['result']['records'][0]['protein'] == 'MK*'
    assert (Path(directory) / imported['path']).read_bytes() == source
    answer_url = url + '/tasks/' + task['id'] + '/decisions/' + question_id
    assert page.request.post(answer_url, data={'answer': 'add'}).ok
    assert page.request.get(url + '/conversations/' + chat).json()['tasks'][0]['toolExecutions'] == task['toolExecutions']
    page.get_by_role('button', name='查看任务', exact=True).click()
    expect(page.get_by_role('tabpanel').get_by_label('任务待决定事项')).to_contain_text('已答复')
    # Create a tool-authority question and answer from the task panel itself.
    pending = page.request.post(url + '/tasks', data={'conversationId': chat, 'requestId': 'panel-decline', 'goal': 'ABC', 'authorizedTools': []}).json()
    panel = page.get_by_role('tabpanel')
    expect(panel).to_contain_text('当前任务未授权 synthetic_count')
    panel.get_by_role('button', name='不授权，取消此任务', exact=True).click()
    expect(panel.get_by_role('region', name='任务 ' + pending['id'], exact=True)).to_contain_text('任务已取消')
    final = page.request.get(url + '/conversations/' + chat).json()
    assert final['modelRequests'] == finished['modelRequests']
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'question_id_preserved': True, 'single_execution': True, 'declined_without_model_call': True, 'durable_answer_admission_retry': True, 'external': external, 'errors': errors}, indent=2))
    browser.close()
