"""Settings→credentials→conversation model selection→pi-ai→real controlled tool."""
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/model-settings')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-model-ui-project-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1480, 'height': 1000})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': '模型隔离验证'}).json()
    project_url = URL + '/api/workbench/projects/' + project['id']
    page.request.post(project_url + '/conversations', data={'title': '人工协议对话'})
    endpoints = page.request.get(URL + '/__test/model-endpoints').json()
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 模型隔离验证', exact=True).click()
    for protocol in ('openai-responses', 'anthropic-messages'):
        page.get_by_role('button', name='模型设置', exact=True).click()
        settings = page.get_by_role('region', name='应用模型设置')
        expect(settings).to_contain_text('API key 存入本机 Keychain')
        settings.get_by_label('配置名称', exact=True).fill('人工 ' + protocol)
        settings.get_by_label('请求协议', exact=True).select_option(protocol)
        settings.get_by_label('模型基础地址', exact=True).fill(endpoints[protocol]['url'])
        settings.get_by_label('模型 ID', exact=True).fill('artificial-model')
        settings.get_by_label('API key', exact=True).fill('artificial-ui-key-' + protocol)
        settings.get_by_role('button', name='保存到 SilicoLab', exact=True).click()
        expect(settings.get_by_label('API key', exact=True)).to_have_value('')
        item = settings.locator('li').last
        expect(item).to_contain_text('端点未验证')
        item.get_by_role('button', name='检查连接（发送人工文本）', exact=True).click()
        expect(item).to_contain_text('连接与协议已检查', timeout=15000)
        expect(settings).not_to_contain_text('artificial-ui-key-')
        page.screenshot(path=str(OUT / (protocol + '-settings.png')), full_page=True)
        config = page.request.get(URL + '/api/workbench/model-configs').json()[-1]
        page.get_by_role('button', name='模型设置', exact=True).click()
        page.get_by_label('当前对话模型', exact=True).select_option(config['id'])
        page.get_by_label('研究目标草稿').fill('用受控工具核对人工文本 ABC')
        page.get_by_role('button', name='发送到所选模型', exact=True).click()
        transcript = page.locator('.wb-transcript')
        expect(transcript.locator('.wb-task-card')).to_have_count(1 if protocol == 'openai-responses' else 2, timeout=15000)
        expect(transcript).to_contain_text('人工模型已核对工具结果', timeout=15000)
        expect(transcript.locator('.wb-task-card').last).to_contain_text('实际字符数：3')
        expect(transcript.locator('.wb-task-card').last).to_contain_text('模型已答复', timeout=15000)
        count = page.request.get(URL + '/__test/model-endpoints').json()[protocol]['requests']
        assert count == 3, {'protocol': protocol, 'requests': count, 'tasks': [(t['requestId'], t['status'], t.get('modelConfigurationId')) for t in page.request.get(project_url).json()['tasks']]}
        expect(page.get_by_label('当前对话模型', exact=True)).to_have_value(config['id'])
        expect(page.locator('body')).not_to_contain_text('artificial-ui-key-')
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 模型隔离验证', exact=True).click()
    expect(page.get_by_label('当前对话模型', exact=True)).to_have_value(config['id'])
    page.screenshot(path=str(OUT / 'conversation-models.png'), full_page=True)
    page.get_by_role('button', name='模型设置', exact=True).click()
    settings = page.get_by_role('region', name='应用模型设置')
    settings.locator('li').last.get_by_role('button', name='移除模型与凭据', exact=True).click()
    expect(settings.locator('li')).to_have_count(1)
    page.get_by_role('button', name='模型设置', exact=True).click()
    selector = page.get_by_label('当前对话模型', exact=True)
    expect(selector).to_have_value(config['id'])
    expect(selector.locator('option:checked')).to_contain_text('已移除或不可用')
    expect(page.get_by_role('button', name='发送到所选模型', exact=True)).to_be_disabled()
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 模型隔离验证', exact=True).click()
    expect(page.get_by_label('当前对话模型', exact=True).locator('option:checked')).to_contain_text('已移除或不可用')
    for file in Path(directory).rglob('*'):
        if file.is_file():
            assert b'artificial-ui-key-' not in file.read_bytes(), file
    assert not errors, errors
    assert not external, external
    browser.close()
