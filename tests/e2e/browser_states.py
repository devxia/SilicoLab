"""Exercise retry and stop controls against tests/ui_fixture.py, without network submissions."""
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='chrome')
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8766', wait_until='networkidle')
    page.get_by_label('任务名称').fill('Retry test')
    page.get_by_label('氨基酸序列', exact=True).fill('>fail-once\nMK\n>success\nMK*')
    page.get_by_role('button', name='开始优化', exact=False).click()
    page.get_by_role('button', name='保持原序列，直接优化', exact=True).click()
    expect(page.locator('.results-panel > .panel-heading .status-badge')).to_have_text('部分完成', timeout=15000)
    expect(page.locator('.failure-state')).to_contain_text('Test constraint warning')
    page.get_by_role('button', name='重试未完成项', exact=True).first.click()
    expect(page.locator('.job-progress')).to_contain_text('2 条通过校验', timeout=15000)
    page.get_by_role('button', name='复制此任务参数与序列', exact=True).click()
    page.get_by_label('任务名称').fill('Stop test')
    page.get_by_label('蛋白序列 · FASTA', exact=True).fill('>slow-1\nMK\n>slow-2\nMK\n>slow-3\nMK')
    page.get_by_role('button', name='开始优化', exact=False).click()
    page.get_by_role('button', name='保持原序列，直接优化', exact=True).click()
    expect(page.locator('.sequence-item').first).to_contain_text('优化中', timeout=10000)
    page.get_by_role('button', name='停止后续提交', exact=True).click()
    expect(page.locator('.results-panel > .panel-heading .status-badge')).to_have_text('已停止', timeout=10000)
    expect(page.locator('.job-progress')).to_contain_text('1 条通过校验')
    expect(page.locator('.sequence-item').nth(1)).to_contain_text('已停止')
    page.get_by_role('button', name='重试未完成项', exact=True).click()
    expect(page.locator('.job-progress')).to_contain_text('3 条通过校验', timeout=15000)
    assert not errors, errors
    Path('outputs/ui').mkdir(parents=True, exist_ok=True)
    page.screenshot(path='outputs/ui/retry-and-stop.png', full_page=True)
    print('PASS: partial failure, retry-only-failed, stop pending, resume stopped, no browser errors')
    browser.close()
