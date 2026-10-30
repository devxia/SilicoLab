"""Selected uploads and immutable version evidence in the actual workbench UI."""
import base64
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/workbench-inputs')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-input-ui-') as directory, sync_playwright() as playwright:
    root = Path(directory)
    project = root / 'project'
    project.mkdir()
    source = root / 'protein.fasta'
    source.write_text('>first\nMK*\n')
    (root / 'never-select.txt').write_text('NEVER_IMPORT')
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1450, 'height': 950})
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(URL) else None)
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='创建项目', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('版本可追溯')
    dialog.get_by_label('项目目录', exact=True).fill(str(project))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='新建对话', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('对话名称').fill('输入核对')
    dialog.get_by_role('button', name='确认', exact=True).click()
    page.get_by_role('button', name='查看文件', exact=True).click()
    upload = page.get_by_label('导入项目文件')
    upload.set_input_files(str(source))
    file_button = page.locator('.wb-files li button').first
    expect(file_button).to_contain_text('protein.fasta')
    file_button.click()
    expect(page.locator('.wb-file-preview pre')).to_contain_text('MK*')
    page.locator('.wb-files input[type=checkbox]').first.check()
    page.get_by_role('button', name='固定任务输入', exact=True).click()
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('v1')
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('MK*')
    index = page.request.get(URL + '/api/workbench/projects').json()
    url = URL + '/api/workbench/projects/' + next(item for item in index if item['name'] == '版本可追溯')['id']
    state = page.request.get(url).json()
    imported = state['files'][0]
    first = state['inputVersions'][0]
    (project / imported['path']).write_text('>updated\nMEF*\n')
    source.write_text('SOURCE_IS_NOW_DIFFERENT')
    page.get_by_role('button', name='固定任务输入', exact=True).click()
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('v2')
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('MEF*')
    page.locator('.wb-version').first.click()
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('v1')
    expect(page.get_by_role('region', name='固定输入详情')).to_contain_text('MK*')
    expect(page.get_by_role('region', name='固定输入详情')).not_to_contain_text('MEF*')
    old = page.request.get(url + '/input-versions/' + first['id']).json()
    assert base64.b64decode(old['inputs'][0]['contentBase64']) == b'>first\nMK*\n'
    upload.set_input_files({'name': 'protein.fasta', 'mimeType': 'text/plain', 'buffer': b'>another\nMKK*\n'})
    expect(page.locator('.wb-files li')).to_have_count(2)
    assert not any('never-select' in str(path) for path in project.rglob('*'))
    page.screenshot(path=str(OUT / 'versions.png'), full_page=True)
    (project / imported['path']).unlink()
    page.get_by_role('button', name='固定任务输入', exact=True).click()
    expect(page.locator('.wb-files [role=alert]')).to_be_visible()
    assert len(page.request.get(url).json()['inputVersions']) == 2
    # A successful first upload remains visible when a later selected file is rejected.
    upload.set_input_files([
        {'name': 'partial-success.txt', 'mimeType': 'text/plain', 'buffer': b'saved before next failure'},
        {'name': 'too-large.bin', 'mimeType': 'application/octet-stream', 'buffer': b'x' * (5 * 1024 * 1024 + 1)},
    ])
    expect(page.locator('.wb-files li')).to_have_count(3)
    expect(page.locator('.wb-files [role=alert]')).to_contain_text('too-large.bin')
    page.locator('.wb-files li button').filter(has_text='partial-success.txt').click()
    expect(page.locator('.wb-file-preview pre')).to_contain_text('saved before next failure')
    # Delay A's refresh, navigate to B, then release the stale response: it must not reselect A.
    other = root / 'other-project'
    other.mkdir()
    page.get_by_role('button', name='展开导航', exact=True).click()
    page.get_by_role('button', name='创建项目', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('另一个项目')
    dialog.get_by_label('项目目录', exact=True).fill(str(other))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='打开项目 版本可追溯', exact=True).click()
    expect(page.locator('.wb-header')).to_contain_text('版本可追溯')
    expect(page.get_by_label('导入项目文件')).to_be_enabled()
    delayed = []
    def hold_refresh(route):
        delayed.append((route, route.fetch()))
    page.route(url, hold_refresh)
    upload = page.get_by_label('导入项目文件')
    upload.set_input_files({'name': 'delayed.txt', 'mimeType': 'text/plain', 'buffer': b'belongs to A'})
    for _ in range(100):
        if delayed:
            break
        page.wait_for_timeout(20)
    assert delayed, 'A refresh did not reach controlled delay'
    page.get_by_role('button', name='打开项目 另一个项目', exact=True).click()
    expect(page.locator('.wb-header')).to_contain_text('另一个项目')
    for route, response in delayed:
        route.fulfill(response=response)
    page.unroute(url, hold_refresh)
    page.wait_for_timeout(100)
    expect(page.locator('.wb-header')).to_contain_text('另一个项目')
    assert not errors, errors
    assert not external, external
    (OUT / 'result.json').write_text(json.dumps({'result': 'passed', 'fixed_versions': 2, 'same_name_imports': 2, 'errors': errors, 'external': external}, indent=2))
    browser.close()
