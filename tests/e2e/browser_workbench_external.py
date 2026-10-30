"""Simulated job UI: independent identity/state, reconcile, pause versus explicit cancellation."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/simulated-external')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-external-ui-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1480, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '独立模拟作业'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '对账与独立取消'}).json()['id']
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 独立模拟作业', exact=True).click()
    page.get_by_role('button', name='查看任务', exact=True).click()
    form = page.get_by_role('region', name='模拟外部作业表单')
    expect(form).to_contain_text('不连接真实集群')
    form.get_by_label('模拟输入文本').fill('ABC')
    form.get_by_role('button', name='提交人工模拟作业', exact=True).click()
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('等待独立外部作业')
    expect(transcript.get_by_label('独立模拟作业状态')).to_contain_text('作业 ID：')
    service = page.request.get(URL + '/api/workbench/simulated-executor').json()
    assert service['createdJobs'] == 1
    job_id = service['jobs'][0]['id']
    transcript.get_by_role('button', name='暂停本机任务', exact=True).click()
    expect(transcript).to_contain_text('已暂停，等待选择恢复')
    assert page.request.get(URL + '/api/workbench/simulated-executor').json()['jobs'][0]['state'] == 'running'
    expect(transcript).to_contain_text(job_id)
    page.screenshot(path=str(OUT / 'paused-tracking.png'), full_page=True)
    transcript.get_by_role('button', name='核对模拟作业', exact=True).click()
    page.wait_for_timeout(3600)
    transcript.get_by_role('button', name='核对模拟作业', exact=True).click()
    expect(transcript).to_contain_text('独立作业已完成')
    expect(transcript).to_contain_text('实际字符数：3')
    with page.expect_download() as download:
        transcript.get_by_role('link', name='下载模拟结果', exact=True).click()
    result = OUT / 'simulated-result.json'
    download.value.save_as(str(result))
    assert json.loads(result.read_text())['jobId'] == job_id
    assert json.loads(result.read_text())['payload'] == 'ABC'
    assert page.request.get(url + '/conversations/' + chat).json()['modelRequests'] == 0
    form.get_by_label('模拟响应').select_option('lost')
    form.get_by_label('假服务支持按稳定身份查询').uncheck()
    form.get_by_role('button', name='提交人工模拟作业', exact=True).click()
    expect(transcript).to_contain_text('结果未知，等待核对')
    unknown = transcript.locator('.wb-task-card').last
    unknown.get_by_role('button', name='核对模拟作业', exact=True).click()
    expect(unknown).to_contain_text('需要用户决定')
    expect(unknown).to_contain_text('独立作业可能已接受，但无法查询核对')
    before = page.request.get(URL + '/api/workbench/simulated-executor').json()
    assert before['createdJobs'] == 2 and before['jobs'][1]['submit_attempts'] == 1
    unknown.get_by_role('button', name='明确按同一身份重试模拟回执', exact=True).click()
    expect(unknown).to_contain_text('等待独立外部作业')
    after = page.request.get(URL + '/api/workbench/simulated-executor').json()
    assert after['createdJobs'] == 2 and after['jobs'][1]['submit_attempts'] == 2
    unknown.get_by_role('button', name='独立取消模拟作业', exact=True).click()
    expect(unknown).to_contain_text('独立作业已取消')
    assert page.request.get(URL + '/api/workbench/simulated-executor').json()['jobs'][1]['state'] == 'cancelled'
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 独立模拟作业', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text(job_id)
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'job_identity_preserved': True, 'tracking_pause_not_job_cancel': True, 'queryless_retry_single_job': True, 'independent_cancel_confirmed': True, 'model_calls': 0, 'external': external, 'errors': errors}, indent=2))
    browser.close()
