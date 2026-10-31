"""Actual in-flight source, pending next receiver, real usage and bounded retry UI."""
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/model-requests')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-request-ui-project-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1480, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: external.append(r.url) if not r.url.startswith(URL) else None)
    endpoints = page.request.get(URL + '/__test/model-requests').json()
    configurations = []
    for name, protocol, key in [('first', 'openai-responses', 'artificial-a'), ('second', 'anthropic-messages', 'artificial-b')]:
        configurations.append(page.request.post(URL + '/api/workbench/model-configs', data={'name': name, 'protocol': protocol, 'baseUrl': endpoints[name]['url'], 'modelId': 'artificial-model', 'apiKey': key}).json())
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '请求边界验证'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '在途切换与用量'}).json()['id']
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 请求边界验证', exact=True).click()
    page.get_by_label('当前对话模型', exact=True).select_option(configurations[0]['id'])
    page.get_by_label('研究目标草稿').fill('人工 ABC 字符数')
    page.get_by_role('button', name='发送到所选模型', exact=True).click()
    in_flight = page.get_by_label('在途模型与待生效选择', exact=True)
    expect(in_flight).to_contain_text('openai-responses')
    page.get_by_label('当前对话模型', exact=True).select_option(configurations[1]['id'])
    expect(in_flight).to_contain_text('新选择从下一次请求生效')
    expect(in_flight).to_contain_text(endpoints['first']['url'])
    assert page.request.get(URL + '/__test/model-requests').json()['second']['requests'] == 0
    page.screenshot(path=str(OUT / 'pending-switch.png'), full_page=True)
    page.request.post(URL + '/__test/release-first')
    transcript = page.locator('.wb-transcript')
    expect(transcript).to_contain_text('模型已答复', timeout=15000)
    expect(transcript).to_contain_text('实际字符数：3')
    traces = transcript.get_by_label('模型请求来源与用量')
    expect(traces.locator('details')).to_have_count(3)
    for detail in traces.locator('details').all():
        if detail.get_attribute('open') is None:
            detail.locator('summary').click()
    expect(traces).to_contain_text('输入 / 输出 token')
    expect(traces).to_contain_text('4 / 3')
    expect(traces).to_contain_text('未知（未配置价格，不以零估算）')
    expect(traces).to_contain_text('有限退避重试')
    actual = page.request.get(url + '/conversations/' + chat).json()['tasks'][0]
    assert len(actual['toolExecutions']) == 1
    assert [r['configurationId'] for r in actual['modelRequests']] == [configurations[0]['id'], configurations[1]['id'], configurations[1]['id']]
    assert [r['status'] for r in actual['modelRequests']] == ['completed', 'error', 'completed']
    counts = page.request.get(URL + '/__test/model-requests').json()
    assert counts['first']['requests'] == 1 and counts['second']['requests'] == 2
    page.screenshot(path=str(OUT / 'usage-and-retry.png'), full_page=True)
    assert not errors, errors
    assert not external, external
    browser.close()
