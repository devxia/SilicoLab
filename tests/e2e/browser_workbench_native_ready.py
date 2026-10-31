"""Native startup must wait for its bridge, never prefer stale browser-origin storage."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright

URL = 'http://127.0.0.1:8767'
with tempfile.TemporaryDirectory(prefix='silicolab-native-ready-') as directory, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page()
    project = page.request.post(URL + '/api/workbench/projects', data={'path': directory, 'name': 'native ready identity'}).json()
    url = URL + '/api/workbench/projects/' + project['id']
    first = page.request.post(url + '/conversations', data={'title': 'STALE_BROWSER_CONVERSATION_A'}).json()['id']
    second = page.request.post(url + '/conversations', data={'title': 'ACTUAL_NATIVE_CONVERSATION_B'}).json()['id']
    stale = {'projectId': project['id'], 'conversationId': first}
    actual = {'projectId': project['id'], 'conversationId': second}
    page.add_init_script('localStorage.setItem("silicolab-workbench-selection", ' + json.dumps(json.dumps(stale)) + ');')
    page.goto(URL + '/?silicolabDesktop=1', wait_until='networkidle')
    expect(page.locator('body')).not_to_contain_text('STALE_BROWSER_CONVERSATION_A')
    expect(page.get_by_role('button', name='打开项目 native ready identity', exact=True)).not_to_be_visible()
    expect(page.get_by_role('status')).to_contain_text('正在连接本机功能')
    page.evaluate("""selection => {
      window.__nativeSaved = [];
      window.pywebview = {api: {
        bootstrap: async () => ({desktop:true,draft:null,selection}),
        save_selection: async value => {window.__nativeSaved.push(value);return true;}
      }};
      window.dispatchEvent(new Event('pywebviewready'));
    }""", actual)
    expect(page.locator('.wb-header')).to_contain_text('ACTUAL_NATIVE_CONVERSATION_B')
    expect(page.locator('.wb-header')).not_to_contain_text('STALE_BROWSER_CONVERSATION_A')
    assert page.evaluate('window.__nativeSaved') == [actual]
    assert json.loads(page.evaluate('localStorage.getItem("silicolab-workbench-selection")')) == stale
    assert page.request.get(url).json()['tasks'] == []
    browser.close()
