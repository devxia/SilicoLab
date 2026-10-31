"""Test-only WKWebView observer; never shipped as a product bridge or HTTP route."""
import json
import os
from pathlib import Path
import threading
import time
import webview
from silicolab import desktop

create_window = webview.create_window
output = Path(os.environ['SILICOLAB_NATIVE_EVIDENCE'])


def instrumented(*args, **kwargs):
    window = create_window(*args, **kwargs)
    closed = threading.Event()
    window.events.closed += lambda: closed.set()
    def loaded():
        while not closed.is_set():
            try:
                state = window.evaluate_js("""(() => {
                  const heading=document.querySelector('.wb-header')?.textContent || '';
                  const transcript=document.querySelector('.wb-transcript')?.textContent || '';
                  const backend=document.querySelector('.wb-desktop-state')?.textContent || '';
                  const button=[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='打开项目 native close evidence');
                  return {heading,transcript,backend,projectVisible:!!button};
                })()""")
                if state and state.get('projectVisible'):
                    state['expected'] = kwargs['js_api'].bootstrap()['selection']
                    if os.environ.get('SILICOLAB_NATIVE_PREPARE_SELECTION') == '1':
                        if not state['expected']:
                            window.evaluate_js("[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='打开项目 native close evidence').click()")
                            time.sleep(0.05); continue
                        if state['expected']['conversationId'] != os.environ['SILICOLAB_NATIVE_TARGET_CHAT']:
                            window.evaluate_js("[...document.querySelectorAll('.wb-conversations button')].find(b=>b.textContent==='same background task')?.click()")
                            time.sleep(0.05); continue
                    if 'native close evidence' in state['heading'] and state['backend'] and state['transcript']:
                        temporary = output.with_suffix('.tmp')
                        temporary.write_text(json.dumps(state, ensure_ascii=False))
                        temporary.replace(output)
            except Exception:
                pass
            time.sleep(0.05)
    # Cocoa may stop while a read-only JS/URL observation awaits its callback.
    # The test observer must not become a non-daemon owner of the GUI process.
    window.events.loaded += lambda: threading.Thread(target=loaded,name='silicolab-native-evidence',daemon=True).start()
    return window


webview.create_window = instrumented
raise SystemExit(desktop.main(['--isolated-resources']))
