"""Actual temporary directory move, visible offline state, explicit relocation and unlink."""
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
OUT = Path('outputs/ui/project-availability')
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-offline-ui-') as directory, sync_playwright() as playwright:
    root = Path(directory)
    source, moved, empty, other = root / 'original', root / 'moved', root / 'empty', root / 'other'
    source.mkdir(); empty.mkdir(); other.mkdir()
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1480, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    project = page.request.post(URL + '/api/workbench/projects', data={'path': str(source), 'name': '目录离线验证'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    chat = page.request.post(url + '/conversations', data={'title': '迁移保持身份'}) .json()['id']
    second = page.request.post(URL + '/api/workbench/projects', data={'path': str(other), 'name': '其他项目'}).json()
    page.request.post(URL + '/api/workbench/projects/' + second['id'] + '/conversations', data={'title': 'other'})
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    page.get_by_label('研究目标草稿').fill('saved-artificial-draft')
    page.get_by_role('button', name='保存草稿', exact=True).click()
    expect(page.locator('.wb-composer')).to_contain_text('草稿已保存')
    page.get_by_role('button', name='运行本机验证', exact=True).click()
    expect(page.locator('.wb-transcript')).to_contain_text('模型已答复', timeout=15000)
    before = page.request.get(url).json()
    task = before['tasks'][0]
    artifact = task['toolExecutions'][0]['artifact']
    original_bytes = (source / artifact['path']).read_bytes()
    page.get_by_label('研究目标草稿').fill('online-draft-before-switch')
    page.get_by_role('button', name='打开项目 其他项目', exact=True).click()
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    expect(page.get_by_label('研究目标草稿')).to_have_value('online-draft-before-switch')
    expect(page.locator('.wb-composer')).to_contain_text('草稿已保存')
    page.get_by_label('研究目标草稿').fill('saved-artificial-draft')
    page.get_by_role('button', name='保存草稿', exact=True).click()
    expect(page.locator('.wb-composer')).to_contain_text('草稿已保存')
    source.rename(moved)
    expect(page.get_by_role('alert').filter(has_text='项目目录离线')).to_be_visible(timeout=10000)
    expect(page.get_by_role('alert').filter(has_text='项目目录离线')).to_contain_text('最新进度未确认保存')
    assert not source.exists()
    page.reload(wait_until='domcontentloaded')
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    expect(page.get_by_role('alert').filter(has_text='项目目录离线')).to_be_visible()
    page.get_by_label('研究目标草稿').fill('UNSAVED_OFFLINE_ARTIFICIAL_DRAFT')
    page.get_by_role('button', name='打开项目 其他项目', exact=True).click()
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    expect(page.get_by_label('研究目标草稿')).to_have_value('UNSAVED_OFFLINE_ARTIFICIAL_DRAFT')
    expect(page.locator('.wb-composer')).to_contain_text('有未保存修改')
    page.get_by_role('button', name='打开项目目录', exact=True).first.click()
    opening = page.get_by_role('dialog')
    opening.get_by_label('项目目录', exact=True).fill(str(other))
    opening.get_by_role('button', name='确认', exact=True).click()
    expect(opening).not_to_be_visible()
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    expect(page.get_by_label('研究目标草稿')).to_have_value('UNSAVED_OFFLINE_ARTIFICIAL_DRAFT')
    third = root / 'third'; third.mkdir()
    page.get_by_role('button', name='创建项目', exact=True).first.click()
    creating = page.get_by_role('dialog')
    creating.get_by_label('项目名称', exact=True).fill('从离线创建新项目')
    creating.get_by_label('项目目录', exact=True).fill(str(third))
    creating.get_by_role('button', name='确认', exact=True).click()
    expect(creating).not_to_be_visible()
    page.get_by_role('button', name='打开项目 目录离线验证', exact=True).click()
    expect(page.get_by_label('研究目标草稿')).to_have_value('UNSAVED_OFFLINE_ARTIFICIAL_DRAFT')
    page.get_by_label('研究目标草稿').fill('')
    page.screenshot(path=str(OUT / 'offline.png'), full_page=True)
    page.get_by_role('button', name='重新定位原项目', exact=True).click()
    dialog = page.get_by_role('dialog', name='重新定位原项目')
    dialog.get_by_label('项目目录', exact=True).fill(str(empty))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).to_be_visible()
    assert not (empty / '.silicolab').exists()
    dialog.get_by_label('项目目录', exact=True).fill(str(moved))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role('alert').filter(has_text='项目目录离线')).not_to_be_visible()
    expect(page.get_by_label('研究目标草稿')).to_have_value('')
    expect(page.locator('.wb-composer')).to_contain_text('有未保存修改')
    page.get_by_role('button', name='保存草稿', exact=True).click()
    expect(page.locator('.wb-composer')).to_contain_text('草稿已保存')
    restored = page.request.get(url).json()
    assert restored['id'] == project['id']
    assert restored['tasks'][0]['id'] == task['id']
    assert restored['tasks'][0]['toolExecutions'] == task['toolExecutions']
    assert (moved / artifact['path']).read_bytes() == original_bytes
    page.get_by_role('button', name='移除项目关联', exact=True).click()
    expect(page.get_by_role('button', name='打开项目 目录离线验证', exact=True)).not_to_be_visible()
    assert (moved / '.silicolab/session.sqlite').is_file()
    assert (moved / artifact['path']).read_bytes() == original_bytes
    page.get_by_role('button', name='打开项目目录', exact=True).first.click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目目录', exact=True).fill(str(moved))
    dialog.get_by_role('button', name='确认', exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.locator('.wb-transcript')).to_contain_text(task['id'][:8])
    assert page.request.get(url).json()['conversations'][0]['id'] == chat
    page.screenshot(path=str(OUT / 'reopened.png'), full_page=True)
    assert not errors, errors
    browser.close()
