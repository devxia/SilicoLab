"""Deletion workflow against a temporary SQLite + controlled worker; no production data."""
import json
from pathlib import Path
import re
import time

from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8766'
OUT = Path(__file__).resolve().parents[2] / 'outputs/ui'
OUT.mkdir(parents=True, exist_ok=True)


def wait_status(page, job_id, statuses):
    for _ in range(150):
        response = page.request.get(f'{URL}/api/jobs/{job_id}')
        assert response.status == 200, response.text()
        detail = response.json()
        if detail['status'] in statuses:
            return detail
        time.sleep(.03)
    raise AssertionError(f'Task failed to reach {statuses}: {detail["status"]}')


def make_job(page, name):
    response = page.request.post(URL + '/api/jobs', data={
        'name': name, 'engine': 'local', 'records': [{'name': name, 'sequence': 'MK*'}]})
    assert response.status == 201, response.text()
    job_id = response.json()['id']
    wait_status(page, job_id, {'completed'})
    return job_id


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    jobs = {name: make_job(page, name) for name in ['保留任务', '单条删除', '分组甲', '分组乙', '当前结果', '状态冲突']}
    row = lambda name: page.locator(f'.history-row[data-job-id="{jobs[name]}"]')
    page.goto(URL, wait_until='networkidle')
    page.get_by_role('button', name='历史记录', exact=True).click()
    expect(page.locator('.history-row[data-job-id]')).to_have_count(6)
    # Single delete cancellation, then confirmed removal; already exported file stays.
    exported = page.request.get(f'{URL}/api/jobs/{jobs["单条删除"]}/export').body()
    exported_path = OUT / 'history-delete-preserved.fasta'
    exported_path.write_bytes(exported)
    row('单条删除').get_by_role('button', name='删除任务 单条删除', exact=True).click()
    dialog = page.get_by_role('dialog', name='删除历史任务')
    expect(dialog).to_contain_text('共 1 个任务，1 条序列')
    dialog.get_by_role('button', name='取消', exact=True).click()
    assert page.request.get(f'{URL}/api/jobs/{jobs["单条删除"]}').status == 200
    row('单条删除').get_by_role('button', name='删除任务 单条删除', exact=True).click()
    dialog.get_by_role('button', name='删除任务', exact=True).click()
    expect(page.locator('.history-row[data-job-id]')).to_have_count(5)
    assert exported_path.read_bytes() == exported
    # Deleting the selected result clears selection, not the unsubmitted editor.
    row('当前结果').get_by_role('button', name='打开任务 当前结果', exact=True).click()
    expect(page.locator('.results-panel')).to_contain_text('当前结果')
    page.locator('#task-name').fill('未提交草稿不要删除')
    page.locator('#sequence-input').fill('MKT*')
    page.get_by_role('button', name='历史记录', exact=True).click()
    row('当前结果').get_by_role('button', name='删除任务 当前结果', exact=True).click()
    dialog.get_by_role('button', name='删除任务', exact=True).click()
    expect(page.locator('.history-row[data-job-id]')).to_have_count(4)
    page.wait_for_function("sessionStorage.getItem('silicolab-active-job') === null")
    page.get_by_role('button', name='新建优化', exact=True).first.click()
    expect(page.locator('.results-empty')).to_be_visible()
    expect(page.locator('#task-name')).to_have_value('未提交草稿不要删除')
    expect(page.locator('#sequence-input')).to_have_value('MKT*')
    # Filtered selection: no hidden task included; changing filters clears selection.
    page.get_by_role('button', name='历史记录', exact=True).click()
    page.get_by_role('button', name='管理记录', exact=True).click()
    page.get_by_label('搜索历史任务', exact=True).fill('分组')
    expect(page.locator('.history-row[data-job-id]')).to_have_count(2)
    page.get_by_role('checkbox', name='全选当前筛选结果中的可删除任务', exact=True).check()
    expect(page.locator('.history-selection-bar')).to_contain_text('已选 2 项')
    page.get_by_role('button', name='已完成', exact=True).click()
    expect(page.locator('.history-selection-bar')).to_contain_text('已选 0 项')
    page.get_by_role('checkbox', name='全选当前筛选结果中的可删除任务', exact=True).check()
    page.screenshot(path=str(OUT / 'history-delete-management.png'), full_page=True)
    page.get_by_role('button', name='删除已选', exact=True).click()
    expect(dialog).to_contain_text('共 2 个任务，2 条序列')
    page.screenshot(path=str(OUT / 'history-delete-confirmation.png'), full_page=True)
    dialog.get_by_role('button', name='删除 2 个任务', exact=True).click()
    expect(page.get_by_text('没有匹配的任务', exact=True)).to_be_visible()
    assert {job['id'] for job in page.request.get(URL + '/api/jobs').json()} == {jobs['保留任务'], jobs['状态冲突']}
    page.get_by_label('搜索历史任务', exact=True).fill('')
    page.get_by_role('button', name='全部任务', exact=True).click()
    # A real controlled worker reactivates after opening a deletion confirmation.
    row('状态冲突').get_by_role('button', name='删除任务 状态冲突', exact=True).click()
    assert page.request.get(f'{URL}/test/requeue?id={jobs["状态冲突"]}').status == 200
    wait_status(page, jobs['状态冲突'], {'running'})
    dialog.get_by_role('button', name='删除任务', exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.locator('.toast')).to_contain_text(re.compile('请先停止'))
    assert page.request.get(f'{URL}/api/jobs/{jobs["状态冲突"]}').status == 200
    expect(row('状态冲突').get_by_role('checkbox', name='选择任务 状态冲突', exact=True)).to_be_disabled()
    expect(row('状态冲突').get_by_role('button', name='删除任务 状态冲突', exact=True)).to_be_disabled()
    page.set_viewport_size({'width': 390, 'height': 844})
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Mobile history overflow'
    page.screenshot(path=str(OUT / 'history-delete-mobile.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    # Stop + release actual in-flight work, then delete normally.
    assert page.request.post(f'{URL}/api/jobs/{jobs["状态冲突"]}/stop').status == 200
    assert page.request.get(URL + '/test/release').status == 200
    wait_status(page, jobs['状态冲突'], {'stopped'})
    expect(row('状态冲突').get_by_role('button', name='删除任务 状态冲突', exact=True)).to_be_enabled()
    row('状态冲突').get_by_role('button', name='删除任务 状态冲突', exact=True).click()
    dialog.get_by_role('button', name='删除任务', exact=True).click()
    expect(page.locator('.history-row[data-job-id]')).to_have_count(1)
    # Another view deletes an open task; SSE must clear it without marking service offline.
    row('保留任务').get_by_role('button', name='打开任务 保留任务', exact=True).click()
    expect(page.locator('.results-panel')).to_contain_text('保留任务')
    assert page.request.delete(f'{URL}/api/jobs/{jobs["保留任务"]}').status == 200
    expect(page.locator('.results-empty')).to_be_visible(timeout=6000)
    page.wait_for_function("sessionStorage.getItem('silicolab-active-job') === null")
    expect(page.locator('#task-name')).to_have_value('未提交草稿不要删除')
    expect(page.locator('#sequence-input')).to_have_value('MKT*')
    expect(page.locator('.connection')).not_to_contain_text('本地服务连接中')
    page.get_by_role('button', name='历史记录', exact=True).click()
    expect(page.get_by_text('还没有优化任务', exact=True)).to_be_visible()
    assert page.request.get(URL + '/api/jobs').json() == []
    page.reload(wait_until='networkidle')
    page.get_by_role('button', name='历史记录', exact=True).click()
    expect(page.get_by_text('还没有优化任务', exact=True)).to_be_visible()
    assert not errors, errors
    report = {'status': 'passed', 'upstream': 'isolated controlled worker only', 'production_deletions': 0,
              'checks': ['single delete and cancel', 'current result cleared with draft preserved', 'filtered select-all',
                         'filter change clears invisible selection', 'batch confirmation', 'whole request active-state rejection',
                         'running and stopping protection', 'other-view deletion via SSE', 'export file preserved',
                         'reload does not resurrect tasks', 'responsive management layout']}
    (OUT / 'history-delete-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: single/bulk deletion, active race, stale detail cleanup, preserved draft/export, filtering, reload, mobile')
    browser.close()
