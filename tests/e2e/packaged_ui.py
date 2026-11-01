"""Actual packaged HTTP/UI resources and native owner, no development server."""
import argparse
import json
from pathlib import Path
from openpyxl import Workbook
import sys
import tempfile
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).with_name('fixtures')))
from packaged_app import PackagedApp


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='silicolab-bundle-ui-') as directory,sync_playwright() as playwright:
        root=Path(directory);owner=PackagedApp(args.app,root/'app-data');browser=None
        try:
            owner.launch();origin=owner.info['origin'];browser=playwright.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':980})
            errors=[];outside=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:outside.append(r.url) if not r.url.startswith(origin) else None)
            project_path=root/'project';project_path.mkdir();project=owner.api('/projects',{'path':str(project_path),'name':'安装UI人工项目'});url='/projects/'+project['id']
            owner.api(url+'/conversations',{'title':'键盘与布局'})
            page.goto(origin,wait_until='domcontentloaded');page.get_by_role('button',name='打开项目 安装UI人工项目',exact=True).click()
            draft=page.get_by_label('研究目标草稿',exact=True);expect(draft).to_be_enabled();draft.fill('layout must retain artificial draft')
            page.get_by_role('button',name='查看结果',exact=True).click();expect(page.get_by_role('button',name='展开导航',exact=True)).to_be_visible()
            page.get_by_role('button',name='展开导航',exact=True).click();page.get_by_role('tab',name='文件',exact=True).click();expect(page.get_by_role('button',name='收起导航',exact=True)).to_be_visible()
            page.get_by_role('button',name='关闭分析区',exact=True).click();expect(draft).to_have_value('layout must retain artificial draft')
            page.get_by_role('button',name='保存草稿',exact=True).click();expect(page.get_by_text('草稿已保存',exact=True)).to_be_visible()
            page.get_by_role('button',name='新建对话',exact=True).click();dialog=page.get_by_role('dialog');expect(dialog.get_by_label('对话名称')).to_be_focused();page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
            page.evaluate("document.body.style.zoom='1.5'")
            draft.scroll_into_view_if_needed();expect(draft).to_be_visible();draft.click();expect(draft).to_be_focused()
            draft.fill('layout must retain artificial draft at 150%')
            save=page.get_by_role('button',name='保存草稿',exact=True);save.scroll_into_view_if_needed();expect(save).to_be_visible();save.click()
            expect(page.get_by_text('草稿已保存',exact=True)).to_be_visible()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),'150% zoom overflows viewport'
            expect(draft).to_have_value('layout must retain artificial draft at 150%');page.evaluate("document.body.style.zoom='1'")
            page.set_viewport_size({'width':620,'height':850})
            if page.get_by_role('button',name='收起导航',exact=True).is_visible():page.get_by_role('button',name='收起导航',exact=True).click()
            page.get_by_role('button',name='展开导航',exact=True).click();expect(page.get_by_role('button',name='键盘与布局',exact=True)).to_be_visible()
            page.set_viewport_size({'width':1440,'height':980});page.get_by_role('link',name='ProteinFactory D2P 专项工作台',exact=True).click();expect(page.get_by_label('任务名称')).to_be_visible()
            page.get_by_role('tab',name='导入表格',exact=True).click()
            table=root/'artificial-wide.xlsx';book=Workbook();book.active.append(['序号','合成名','长度','序列'])
            for index in range(1,81):book.active.append([index,'artificial-'+str(index),135,'M'+'K'*134+'*'])
            book.save(table);book.close();page.get_by_label('选择表格文件').set_input_files(str(table))
            table_dialog=page.get_by_role('dialog',name='导入表格 · 选择数据列');expect(table_dialog.get_by_text('80 条有效序列',exact=True)).to_be_visible()
            page.set_viewport_size({'width':620,'height':850});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert owner.raw('/api/jobs').json()==[],'Table inspection must not submit sequences'
            expect(table_dialog.get_by_role('button',name='导入 80 条序列',exact=True)).to_be_enabled()
            assert page.request.get(origin+'/fonts/DM-Sans.ttf').ok and page.request.get(origin+'/fonts/OFL.txt').ok
            assert not outside,outside;assert not errors,errors
            assert owner.api(url)['modelRequests']==0
            args.output.parent.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(args.output.with_suffix('.png')),full_page=True)
            report={'status':'passed','packagedOrigin':True,'realCocoaOwner':True,'navigationAPlusC':True,'draftPreserved':True,'keyboardDialogFocusEscape':True,'zoom150Percent':True,'narrowNavigation620':True,'localFontAndLicense':True,'manualWorkbenchRetained':True,'wideSequenceTableNoViewportOverflow':True,'externalResources':0,'modelRequests':0}
            args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
        finally:
            if browser:browser.close()
            owner.close()


if __name__=='__main__':main()
