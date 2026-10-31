"""Trusted app supervisor operation for generated code, never executes outside Seatbelt."""
import ast
import base64
import csv
import hashlib
import io
import json
import math
import posixpath
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from silicolab.restricted_python import PythonProbe


def runtime_app():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'analysis/PythonBoundaryProbe.app'
    return Path(__file__).resolve().parents[3] / 'release/PythonBoundaryProbe.app'


def verify_runtime(app):
    manifest = app.parent / (app.stem + '-manifest.json')
    if not manifest.is_file() or not app.is_dir():
        raise ValueError('受限Python独立运行时未预装；请按文档构建，禁止无沙箱回退')
    inventory = json.loads(manifest.read_text())
    if inventory['runtime_lock']['python']['version'] != '3.13.18':
        raise ValueError('独立Python版本未经验证，执行被阻断')
    for name, expected in inventory['files'].items():
        path = app / name
        if '..' in Path(name).parts or Path(name).is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('运行时来源路径不符')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('独立运行时内容完整性不符，执行被阻断')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True, capture_output=True, timeout=10)
    return app / 'Contents/Resources/python'


def numeric_inputs(inputs):
    if len(inputs) != 1:
        raise ValueError('首版临时分析仅支持一个value数值列CSV固定输入')
    raw = base64.b64decode(inputs[0]['contentBase64'], validate=True)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != ['value']:
        raise ValueError('当前核验方法要求仅含value列的CSV，不猜测任意表格字段')
    values = [float(row['value']) for row in reader]
    if not values or len(values) > 10000 or any(not math.isfinite(v) for v in values):
        raise ValueError('value列须为1–10000个有限数值')
    return raw, values


def bounded_workbook(content):
    """Validate and extract a narrow six-cell OOXML format with one parser only."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(entries) > 100 or sum(item.file_size for item in entries) > 8 * 1024 * 1024:
            raise ValueError('Excel条目或解压大小超过核验上限')
        expected_parts = {
            '[Content_Types].xml', '_rels/.rels', 'docProps/app.xml', 'docProps/core.xml',
            'xl/theme/theme1.xml', 'xl/styles.xml', 'xl/workbook.xml',
            'xl/_rels/workbook.xml.rels', 'xl/worksheets/sheet1.xml',
        }
        if set(names) != expected_parts:
            raise ValueError('Excel部件集合不属于受支持的单工作表格式')
        worksheets = ['xl/worksheets/sheet1.xml']
        xml_parts = {}
        elements = 0
        for name in names:
            if not name.endswith(('.xml', '.rels')): continue
            raw = archive.read(name)
            # Only UTF-8 XML; disallow declarations capable of entity expansion.
            text = raw.decode('utf-8-sig')
            if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper() or '\x00' in text:
                raise ValueError('Excel XML不支持DTD或实体声明')
            xml_parts[name] = text
            worksheet = name in worksheets
            row_ids, cell_ids = set(), set()
            for _, node in ET.iterparse(io.StringIO(text), events=('start',)):
                elements += 1
                if elements > 10000: raise ValueError('Excel XML元素超过核验上限')
                tag = node.tag.rsplit('}', 1)[-1]
                if tag == 'Relationship' and node.get('TargetMode') == 'External':
                    raise ValueError('Excel不支持外部关系')
                if worksheet:
                    if tag == 'dimension' and node.get('ref') not in ('A1:C2', 'A1', None):
                        raise ValueError('Excel行列范围超过2行3列')
                    if tag == 'row':
                        row_id = node.get('r')
                        if row_id not in ('1', '2') or row_id in row_ids or len(row_ids) >= 2:
                            raise ValueError('Excel行列范围含越界/重复行')
                        row_ids.add(row_id)
                    if tag == 'c':
                        cell_id = node.get('r')
                        if cell_id not in ('A1','B1','C1','A2','B2','C2') or cell_id in cell_ids:
                            raise ValueError('Excel行列范围含越界/重复单元格')
                        cell_ids.add(cell_id)
                    if tag in ('f', 'mergeCell', 'externalLink', 'hyperlink'):
                        raise ValueError('Excel分析产物不支持公式、合并或外部内容')
                node.clear()
        # Bind the only permitted worksheet to the same XML that is validated/extracted.
        package_ns = 'http://schemas.openxmlformats.org/package/2006/'
        office_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        sheet_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        content_types = ET.fromstring(xml_parts['[Content_Types].xml'])
        expected_types = {
            '/xl/styles.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml',
            '/xl/theme/theme1.xml': 'application/vnd.openxmlformats-officedocument.theme+xml',
            '/docProps/core.xml': 'application/vnd.openxmlformats-package.core-properties+xml',
            '/docProps/app.xml': 'application/vnd.openxmlformats-officedocument.extended-properties+xml',
            '/xl/worksheets/sheet1.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml',
            '/xl/workbook.xml': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
        }
        overrides, defaults = {}, {}
        if content_types.tag != '{' + package_ns + 'content-types}Types':
            raise ValueError('Excel部件内容类型不受支持')
        for node in content_types:
            if node.tag == '{' + package_ns + 'content-types}Override':
                key = node.get('PartName')
                if key in overrides: raise ValueError('Excel部件类型重复')
                overrides[key] = node.get('ContentType')
            elif node.tag == '{' + package_ns + 'content-types}Default':
                key = node.get('Extension')
                if key in defaults: raise ValueError('Excel默认部件类型重复')
                defaults[key] = node.get('ContentType')
            else: raise ValueError('Excel部件类型声明不受支持')
        if overrides != expected_types or defaults != {'rels':'application/vnd.openxmlformats-package.relationships+xml','xml':'application/xml'}:
            raise ValueError('Excel部件类型与已预检对象不符')
        relationship_targets = {}
        expected_relationships = {
            '_rels/.rels': {
                office_ns + 'officeDocument': 'xl/workbook.xml',
                package_ns + 'relationships/metadata/core-properties': 'docProps/core.xml',
                office_ns + 'extended-properties': 'docProps/app.xml',
            },
            'xl/_rels/workbook.xml.rels': {
                office_ns + 'worksheet': 'xl/worksheets/sheet1.xml',
                office_ns + 'styles': 'xl/styles.xml',
                office_ns + 'theme': 'xl/theme/theme1.xml',
            },
        }
        for part, expected in expected_relationships.items():
            relationships = ET.fromstring(xml_parts[part])
            actual, ids = {}, set()
            if relationships.tag != '{' + package_ns + 'relationships}Relationships':
                raise ValueError('Excel关系声明不受支持')
            for node in relationships:
                target = node.get('Target', '')
                identity = node.get('Id')
                kind = node.get('Type')
                if node.tag != '{' + package_ns + 'relationships}Relationship' or node.get('TargetMode') or not identity or identity in ids or kind in actual or '\\' in target or ':' in target or '?' in target or '#' in target or '..' in target.split('/'):
                    raise ValueError('Excel关系Target无效或重复')
                resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl' if part.startswith('xl/') else '', target))
                if expected.get(kind) != resolved or resolved not in xml_parts:
                    raise ValueError('Excel关系Target未绑定已预检部件')
                ids.add(identity); actual[kind] = resolved
                if part.startswith('xl/'): relationship_targets[identity] = resolved
            if actual != expected: raise ValueError('Excel关系集合缺失或不受支持')
        # A deliberately narrow, trusted General-only profile: compare parsed XML,
        # never execute a general workbook reader on the script's stylesheet.
        from openpyxl import Workbook
        from openpyxl.styles.stylesheet import write_stylesheet
        from openpyxl.xml.functions import tostring
        def structure(node):
            return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(), tuple(structure(child) for child in node))
        default_book = Workbook()
        try:
            trusted_styles = ET.fromstring(tostring(write_stylesheet(default_book)))
        finally:
            default_book.close()
        if structure(ET.fromstring(xml_parts['xl/styles.xml'])) != structure(trusted_styles):
            raise ValueError('Excel样式只支持可信默认General模板（包括隐式样式0）')
        workbook = ET.fromstring(xml_parts['xl/workbook.xml'])
        qualified = lambda tag: '{' + sheet_ns + '}' + tag
        containers = [node for node in workbook.iter() if node.tag.rsplit('}', 1)[-1] == 'sheets']
        if workbook.tag != qualified('workbook') or len(containers) != 1 or containers[0].tag != qualified('sheets') or containers[0] not in list(workbook):
            raise ValueError('Excel工作表命名空间或容器结构不受支持')
        sheets = list(containers[0])
        local_sheets = [node for node in workbook.iter() if node.tag.rsplit('}', 1)[-1] == 'sheet']
        if len(sheets) != 1 or local_sheets != sheets or sheets[0].tag != qualified('sheet') or relationship_targets.get(sheets[0].get('{' + office_ns.rstrip('/') + '}id')) != worksheets[0]:
            raise ValueError('Excel工作表关系未绑定已预检部件')
        # Never hand the original untrusted ZIP to openpyxl: its permissive namespace
        # and relationship semantics must not disagree with this strict validator.
        sheet = ET.fromstring(xml_parts[worksheets[0]])
        if sheet.tag != qualified('worksheet') or any(not node.tag.startswith('{' + sheet_ns + '}') for node in sheet.iter()):
            raise ValueError('Excel工作表命名空间或根结构不受支持')
        allowed_top = {'sheetPr','dimension','sheetViews','sheetFormatPr','sheetData','pageMargins'}
        if any(node.tag.rsplit('}',1)[-1] not in allowed_top for node in sheet):
            raise ValueError('Excel工作表结构超出摘要格式')
        containers = [node for node in sheet.iter() if node.tag == qualified('sheetData')]
        if len(containers) != 1 or containers[0] not in list(sheet):
            raise ValueError('Excel工作表数据容器结构不受支持')
        rows = list(containers[0])
        if [node.tag for node in rows] != [qualified('row'), qualified('row')] or [node.get('r') for node in rows] != ['1','2']:
            raise ValueError('Excel行列范围要求两条有序数据行')
        extracted = []
        for row_index, row in enumerate(rows, 1):
            if set(row.attrib) != {'r'}:
                raise ValueError('Excel行样式或隐藏属性不受支持')
            cells = list(row)
            expected_ids = [f'{column}{row_index}' for column in 'ABC']
            if len(cells) != 3 or [node.tag for node in cells] != [qualified('c')]*3 or [node.get('r') for node in cells] != expected_ids:
                raise ValueError('Excel行列范围要求每行三个有序单元格')
            result = []
            for cell in cells:
                if not set(cell.attrib) <= {'r','t','s'} or cell.get('s') not in (None,'0'):
                    raise ValueError('Excel单元格样式只接受默认General格式')
                children = list(cell)
                if row_index == 1:
                    if cell.get('t') != 'inlineStr' or len(children) != 1 or children[0].tag != qualified('is') or len(children[0]) != 1 or children[0][0].tag != qualified('t') or len(children[0][0]):
                        raise ValueError('Excel摘要标题结构不受支持')
                    result.append(children[0][0].text or '')
                else:
                    if cell.get('t') not in (None,'n') or len(children) != 1 or children[0].tag != qualified('v') or len(children[0]):
                        raise ValueError('Excel摘要数值结构不受支持')
                    number = float(children[0].text or '')
                    if not math.isfinite(number): raise ValueError('Excel摘要数值不是有限值')
                    result.append(number)
            extracted.append(tuple(result))
        # Reject data hidden outside sheetData as well as duplicate/ambiguous containers.
        if sum(node.tag == qualified('row') for node in sheet.iter()) != 2 or sum(node.tag == qualified('c') for node in sheet.iter()) != 6:
            raise ValueError('Excel工作表含摘要外行列结构')
        return extracted


def run_analysis(request, on_start, cancelled):
    if request.get('workflow') != 'python_analysis' or not isinstance(request.get('code'), str) or len(request['code']) > 100000:
        raise ValueError('受限分析参数/脚本格式不合法')
    ast.parse(request['code'])
    raw, values = numeric_inputs(request['inputs'])
    runtime = verify_runtime(runtime_app())
    response_files = []
    def exported(name, kind, content):
        return {'name': name, 'mediaType': kind, 'contentBase64': base64.b64encode(content).decode()}
    with tempfile.TemporaryDirectory(prefix='silicolab-analysis-source-') as directory:
        input_path = Path(directory) / 'input-001.csv'
        input_path.write_bytes(raw)
        with PythonProbe(runtime=runtime) as owner:
            if cancelled.is_set(): raise ValueError('临时分析在启动前已停止')
            run = owner.start(request['code'], inputs=[input_path])
            on_start(run)
            if cancelled.is_set(): run.stop()
            state = run.wait(timeout=25)
            report = {'status': 'failed', 'inputVersionId': request['inputVersionId'], 'records': [],
                      'engine_info': {'id': 'restricted_python', 'label': '受限独立Python', 'version': '3.13.18', 'network_used': False},
                      'network_attempts': None, 'network_policy': 'deny-default; denied syscall attempts are not fully counted', 'scope': 'temporary numeric CSV summary; Seatbelt single process; no arbitrary shell',
                      'script_sha256': hashlib.sha256(request['code'].encode()).hexdigest(), 'environment': state['environment'],
                      'parameters': {'validation': 'numeric_summary', 'inputName': 'input-001.csv', 'timeoutSeconds': 25},
                      'returncode': state['returncode'], 'inputs_unchanged': state['inputs_unchanged'], 'checks': {}, 'attempt': request['attempt']}
            logs = {name + '.txt': run.log(name) for name in ('stdout', 'stderr')}
            names = sorted(set(run.artifacts()) | set(logs))
            if len(names) > 20: raise ValueError('分析产物超过20个应用上限')
            if any(name in ('record.json', 'analysis.py') for name in names):
                raise ValueError('脚本产物使用了可信来源记录保留文件名')
            total_bytes = 0
            for name in names:
                if name in ('stdout.txt', 'stderr.txt'):
                    content = logs[name]
                else:
                    content = run.artifact(name)
                total_bytes += len(content)
                if len(content) > 1024 * 1024 or total_bytes > 4 * 1024 * 1024:
                    raise ValueError('分析产物超过单个1MiB或总计4MiB应用上限')
                kind = 'application/json' if name.endswith('.json') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if name.endswith('.xlsx') else 'text/plain; charset=utf-8'
                if '/' in name or name.startswith('.') or not name.endswith(('.json', '.xlsx', '.txt', '.csv')):
                    raise ValueError('分析返回未声明格式产物')
                response_files.append(exported(name, kind, content))
            try:
                if state['status'] != 'completed' or not state['inputs_unchanged']:
                    raise ValueError('脚本未实际完成或输入完整性改变')
                summary = json.loads(run.artifact('summary.json'))
                expected = {'count': len(values), 'sum': math.fsum(values), 'mean': statistics.mean(values)}
                if not all(math.isfinite(value) for value in expected.values()):
                    raise ValueError('数值摘要超出有限浮点范围，无法核验')
                if set(summary) != set(expected) or any(isinstance(summary[k], bool) or not isinstance(summary[k], (int, float)) or not math.isclose(summary[k], v, rel_tol=1e-12, abs_tol=1e-12) for k, v in expected.items()):
                    raise ValueError('summary.json与固定输入独立核验不符')
                workbook_bytes = run.artifact('summary.xlsx')
                rows = bounded_workbook(workbook_bytes)
                wanted = (expected['count'], expected['sum'], expected['mean'])
                if rows[0] != ('count','sum','mean') or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isclose(value, target, rel_tol=1e-12, abs_tol=1e-12) for value, target in zip(rows[1], wanted)):
                    raise ValueError('Excel实际结果与独立核验不符')
                report.update(status='completed', summary=expected, checks={'independent_numeric_summary': True, 'json_and_workbook_match': True})
            except (OSError, ValueError, KeyError, OverflowError, zipfile.BadZipFile, ET.ParseError) as error:
                report['error'] = str(error)
            response_files.append(exported('record.json', 'application/json', json.dumps(report, ensure_ascii=False).encode()))
            return {'ok': True, 'result': report, 'files': response_files}
