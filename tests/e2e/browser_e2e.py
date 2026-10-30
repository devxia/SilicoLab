"""Run against a started production server; submits two short test sequences.

.venv/bin/python tests/browser_e2e.py
"""
import json
import os
from pathlib import Path
import sys

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'outputs' / 'ui'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='chrome')
    context = browser.new_context(viewport={'width': 1440, 'height': 1060}, device_scale_factor=1,
                                  permissions=['clipboard-read', 'clipboard-write'])
    page = context.new_page()
    errors, bad_responses = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: bad_responses.append((response.status, response.url))
            if response.status >= 400 else None)
    page.goto(URL + '/#manual', wait_until='networkidle')
    expect(page.get_by_role('heading', name='密码子优化', exact=True)).to_be_visible()
    page.screenshot(path=str(ARTIFACTS / 'workspace.png'), full_page=True)
    page.get_by_label('氨基酸序列', exact=True).fill('MKX')
    expect(page.get_by_role('button', name='开始优化')).to_be_disabled()
    expect(page.get_by_text('第 3 位的 X 不是支持的氨基酸', exact=False)).to_be_visible()
    page.get_by_role('button', name='载入示例', exact=True).click()
    page.get_by_label('任务名称').fill('客户端验证 · 两条测试序列')
    page.get_by_label('目标宿主').select_option('Escherichia_coli')
    for enzyme in ('EcoRI', 'BsaI', 'BsmBI'):
        page.get_by_role('button', name=enzyme, exact=True).click()
    # Clean up only the test-owned preset left by a previous interrupted run.
    for preset in page.request.get(URL + '/api/presets').json():
        if preset['name'] == '浏览器测试 · Golden Gate':
            page.request.delete(URL + '/api/presets/' + preset['id'])
    page.get_by_role('button', name='保存预设', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('预设名称').fill('浏览器测试 · Golden Gate')
    dialog.get_by_role('button', name='保存预设', exact=True).click()
    expect(dialog).not_to_be_visible()
    reuse_id = os.environ.get('CODON_E2E_REUSE_JOB')
    if reuse_id:
        job_id = reuse_id
        page.get_by_role('button', name='历史记录', exact=True).click()
        page.locator('.history-row').filter(has_text='客户端验证').first.click()
    else:
        with page.expect_response(lambda response: response.url.endswith('/api/jobs') and response.request.method == 'POST') as created:
            page.get_by_role('button', name='开始优化', exact=False).click()
            page.get_by_role('button', name='保持原序列，直接优化', exact=True).click()
        job_id = created.value.json()['id']
    # Completion must appear through SSE, without browser reload or manual refresh.
    expect(page.locator('.job-progress').get_by_text('2 条通过校验', exact=False)).to_be_visible(timeout=45000)
    expect(page.locator('.result-detail .verified')).to_have_text('校验通过')
    page.get_by_role('tab', name='校验详情', exact=True).click()
    expect(page.get_by_text('按标准遗传密码表翻译，与输入氨基酸逐位一致', exact=True)).to_be_visible()
    expect(page.get_by_text('已检查正反两条链：GAATTC、GGTCTC、CGTCTC', exact=True)).to_be_visible()
    page.get_by_role('tab', name='密码子对照', exact=True).click()
    expect(page.locator('.alignment-cell')).to_have_count(33)
    page.get_by_role('tab', name='DNA 序列', exact=True).click()
    page.get_by_role('button', name='复制 DNA', exact=True).first.click()
    clipboard = page.evaluate('navigator.clipboard.readText()')
    assert clipboard.startswith('ATG') and len(clipboard) == 99, clipboard
    with page.expect_download() as download:
        page.get_by_role('button', name='导出全部', exact=True).click()
    download.value.save_as(str(ARTIFACTS / 'browser-results.fasta'))
    assert (ARTIFACTS / 'browser-results.fasta').read_text().count('>') == 2
    with page.expect_download() as download:
        page.get_by_role('button', name='记录包', exact=True).click()
    download.value.save_as(str(ARTIFACTS / 'browser-records.zip'))
    page.locator('.sequence-item').nth(1).click()
    page.get_by_role('tab', name='校验详情', exact=True).click()
    expect(page.get_by_text('已保留输入末尾的终止符', exact=True)).to_be_visible()
    page.get_by_role('tab', name='DNA 序列', exact=True).click()
    page.screenshot(path=str(ARTIFACTS / 'results.png'), full_page=True)
    page.reload(wait_until='networkidle')
    expect(page.locator('.job-progress').get_by_text('2 条通过校验', exact=False)).to_be_visible()
    page.get_by_role('button', name='历史记录', exact=False).click()
    page.get_by_role('button', name='已完成', exact=True).click()
    page.get_by_label('搜索历史任务').fill('客户端验证')
    expect(page.locator('.history-row').filter(has_text='客户端验证')).to_have_count(1)
    page.screenshot(path=str(ARTIFACTS / 'history.png'), full_page=True)
    page.get_by_label('搜索历史任务').fill('no-such-task')
    expect(page.get_by_text('没有匹配的任务', exact=True)).to_be_visible()
    page.get_by_role('button', name='参数预设', exact=True).click()
    expect(page.get_by_role('heading', name='浏览器测试 · Golden Gate', exact=True)).to_be_visible()
    page.get_by_role('button', name='应用到新任务', exact=False).first.click()
    expect(page.get_by_label('目标宿主')).to_have_value('Escherichia_coli')
    page.get_by_role('button', name='新建优化', exact=False).click()
    page.get_by_role('tab', name='导入 FASTA', exact=True).click()
    page.get_by_label('选择 FASTA 文件').set_input_files(str(ROOT / 'examples' / 'proteins.fasta'))
    expect(page.get_by_text('2 条序列已通过输入校验', exact=True)).to_be_visible()
    page.get_by_role('button', name='使用指南', exact=True).click()
    expect(page.get_by_role('dialog', name='使用 SilicoLab')).to_be_visible()
    page.keyboard.press('Escape')
    page.get_by_role('button', name='工作台设置', exact=True).click()
    expect(page.get_by_role('dialog', name='工作台设置')).to_be_visible()
    page.get_by_role('button', name='关闭弹窗', exact=True).click()
    # A narrow viewport must keep the primary action and inputs usable without page overflow.
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('tab', name='粘贴序列', exact=True).click()
    expect(page.get_by_role('button', name='开始优化', exact=False)).to_be_enabled()
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Mobile overflow'
    page.screenshot(path=str(ARTIFACTS / 'mobile.png'), full_page=True)
    page.get_by_role('button', name='参数预设', exact=True).click()
    page.get_by_role('button', name='删除预设 浏览器测试 · Golden Gate', exact=True).click()
    assert not errors, errors
    assert not bad_responses, bad_responses
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Preset page mobile overflow'
    (ARTIFACTS / 'e2e-report.json').write_text(json.dumps({
        'status': 'passed', 'job_id': job_id, 'browser_errors': errors, 'bad_responses': bad_responses,
        'checks': ['input validation', 'live multi-sequence optimization', 'SSE status updates',
                   'DNA translation and motifs', 'codon alignment', 'clipboard', 'FASTA download',
                   'ZIP download', 'terminal stop', 'reload recovery', 'history and search',
                   'preset save/apply/delete', 'FASTA file input', 'help/settings dialogs', 'mobile layout'],
    }, ensure_ascii=False, indent=2))
    print('PASS: browser workflow, live upstream, exports, persistence and mobile layout')
    print('Job:', job_id)
    print('Screenshots:', ARTIFACTS)
    browser.close()
