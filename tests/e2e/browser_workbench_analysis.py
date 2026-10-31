"""Generated analysis script, real sandbox, independently verified JSON/Excel and source UI."""
import base64
import io
from pathlib import Path
import tempfile
from playwright.sync_api import expect, sync_playwright
from openpyxl import load_workbook

URL='http://127.0.0.1:8767'
OUT=Path('outputs/ui/restricted-analysis');OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='silicolab-analysis-ui-') as directory,sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1480,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    project=page.request.post(URL+'/api/workbench/projects',data={'path':directory,'name':'受限临时分析验证'}).json()
    url=URL+'/api/workbench/projects/'+project['id']
    chat=page.request.post(url+'/conversations',data={'title':'脚本与实际产物'}).json()['id']
    source=page.request.post(url+'/files',data={'name':'artificial.csv','contentBase64':base64.b64encode(b'value\n1\n2\n6\n').decode()}).json()
    fixed=page.request.post(url+'/input-versions',data={'conversationId':chat,'fileIds':[source['id']]}).json()
    page.goto(URL,wait_until='networkidle')
    page.get_by_role('button',name='打开项目 受限临时分析验证',exact=True).click()
    page.get_by_role('button',name='查看任务',exact=True).click()
    form=page.get_by_role('region',name='受限Python临时分析')
    expect(form).to_contain_text('不是任意宿主shell')
    form.get_by_label('固定CSV输入',exact=True).select_option(fixed['id'])
    form.get_by_label('仅授权本任务生成并受限运行临时分析脚本，不调用科学远端').check()
    form.get_by_role('button',name='运行受限临时分析',exact=True).click()
    transcript=page.locator('.wb-transcript')
    expect(transcript).to_contain_text('分析产物已独立核验',timeout=20000)
    expect(transcript).to_contain_text('count 3 / sum 9 / mean 3')
    transcript.get_by_role('button',name='检视实际脚本',exact=True).click()
    expect(transcript.get_by_label('实际分析脚本')).to_contain_text('statistics')
    expect(transcript).to_contain_text('3.13.18')
    with page.expect_download() as d:transcript.get_by_role('link',name='下载分析 Excel',exact=True).click()
    destination=OUT/'summary.xlsx';d.value.save_as(str(destination))
    book=load_workbook(io.BytesIO(destination.read_bytes()))
    assert list(book.active.values)==[('count','sum','mean'),(3,9,3)];book.close()
    task=page.request.get(url).json()['tasks'][0]
    assert len(task['toolExecutions'])==1
    assert task['toolExecutions'][0]['result']['checks']['independent_numeric_summary']
    assert page.request.get(URL+'/api/jobs').json()==[]
    page.screenshot(path=str(OUT/'script-and-results.png'),full_page=True)
    assert not errors,errors
    browser.close()
