"""Trusted remote worker; same transport/validator as codon, never a local fallback."""
import asyncio
import base64
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
import zipfile


def main():
    network_attempts = 0
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Scientific input exceeds worker limit')
        data = json.loads(raw)
        if data.get('workflow') != 'protein_factory_remote' or data.get('specialtyAcknowledged') is not True:
            raise ValueError('Explicit ProteinFactory specialty request required')
        import httpx
        from silicolab.features.codon import client as codon
        from silicolab.features.codon.engines import engine_metadata
        from silicolab.features.codon.spreadsheets import synthesis_workbook
        from silicolab.features.codon.transport import optimize_remote
        url = os.environ.get('SILICOLAB_SCIENCE_REMOTE') or codon.BASE_URL + '/toDnaAjaxCodon'
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError('Remote endpoint is not an allowed HTTP(S) address')
        timeout = float(os.environ.get('SILICOLAB_SCIENCE_REMOTE_TIMEOUT') or '120')
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError('Remote timeout must be in (0, 120] seconds')
        parameters = data['parameters']
        if parameters.get('stopPolicy') not in {'preserve', 'add'}:
            raise ValueError('Terminal stop policy must be explicit before remote call')
        avoid = codon.normalize_avoid(parameters.get('avoid', ''))
        metadata = engine_metadata('remote')
        metadata['endpoint'] = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
        sources = []
        with tempfile.TemporaryDirectory(prefix='silicolab-remote-inputs-') as directory:
            for index, item in enumerate(data['inputs']):
                path = Path(directory) / f'{index}.fa'
                path.write_bytes(base64.b64decode(item['contentBase64'], validate=True))
                sources.extend((item, name, protein) for name, protein in codon.read_fasta(path))
        if len(sources) > 200 or sum(len(protein) for _, _, protein in sources) > 200000:
            raise ValueError('Remote task exceeds admission limits')
        records, network_attempts, uncertain = [], 0, False
        previous = data.get('previousRecords', [])
        for index, (item, name, protein) in enumerate(sources):
            record = {'name': name, 'protein': protein, 'original_protein': protein,
                      'source_file_id': item['fileId'], 'source_sha256': item['sha256'],
                      'parameters': {'stopPolicy': parameters['stopPolicy'], 'avoid': avoid}, 'status': 'failed'}
            try:
                if len(name) > 300 or any(ord(char) < 32 for char in name):
                    raise ValueError('序列名称过长或包含控制字符')
                if parameters['stopPolicy'] == 'add' and not protein.endswith('*'):
                    protein = codon.normalize_sequence(protein + '*')
                record['protein'] = protein
                prior = previous[index] if index < len(previous) else None
                if prior and prior.get('status') == 'completed':
                    for key in ('name', 'protein', 'original_protein', 'source_file_id', 'source_sha256', 'parameters'):
                        if prior.get(key) != record[key]:
                            raise ValueError('Prior result does not match fixed input and parameters')
                    dna = codon.validate_result(prior['raw_response'], protein, avoid)
                    record.update(prior, dna=dna, reused=True)
                elif uncertain:
                    record.update(status='not_attempted', error='前一请求效果未知；未发送此条')
                else:
                    payload = {'fileName': name, 'jumpName': 'pep', 'sequence': protein,
                               'ignoreCodonQueue': avoid, 'speciesName': codon.DEFAULT_SPECIES}
                    network_attempts += 1
                    response = asyncio.run(optimize_remote(payload, endpoint=url, timeout=timeout, max_response_bytes=16 * 1024 * 1024))
                    record['raw_response'] = response
                    dna = codon.validate_result(response, protein, avoid)
                    record.update(status='completed', dna=dna, terminal_stop_present=protein.endswith('*'),
                                  checks={'characters': True, 'length': True, 'translation': True,
                                          'stop_policy': True, 'avoid_both_strands': True})
            except codon.OptimizationError as error:
                record['error'] = str(error)
                if isinstance(error.__cause__, httpx.RequestError):
                    uncertain = True
                    record['status'] = 'unknown'
                    record['error'] = '远端连接中断或超时，请求可能已执行；结果未知'
            except ValueError as error:
                record['error'] = str(error)
            records.append(record)
        succeeded = [r for r in records if r['status'] == 'completed']
        status = 'unknown' if uncertain else 'completed' if len(succeeded) == len(records) and records else 'partial' if succeeded else 'failed'
        fasta = ''.join(f'>{record["name"]}\n{record["dna"]}\n' for record in succeeded).encode()
        report = {'status': status, 'inputVersionId': data['inputVersionId'], 'engine_info': metadata,
                  'records': records, 'network_attempts': network_attempts, 'attempt': data['attempt'],
                  'scope': 'ProteinFactory D2P/pD2P_1.08t/predefined insertion; independent validation; no vector validation'}
        files = []
        def exported(name, kind, content):
            return {'name': name, 'mediaType': kind, 'contentBase64': base64.b64encode(content).decode()}
        if succeeded:
            excel = synthesis_workbook(records)
            files = [exported('synthesis.fasta', 'text/plain; charset=utf-8', fasta),
                     exported('synthesis.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', excel)]
            files += [exported(f'sequence-{i:03d}.fasta', 'text/plain; charset=utf-8', f'>{record["name"]}\n{record["dna"]}\n'.encode()) for i, record in enumerate(records, 1) if record['status'] == 'completed']
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('record.json', json.dumps(report, ensure_ascii=False))
            archive.writestr('task.json', json.dumps(data['task'], ensure_ascii=False))
            archive.writestr('input-version.json', json.dumps({k: v for k, v in data['inputVersion'].items() if k != 'inputs'} | {'inputs': [{k: v for k, v in item.items() if k != 'contentBase64'} for item in data['inputs']]}, ensure_ascii=False))
            for index, item in enumerate(data['inputs'], 1):
                archive.writestr(f'inputs/{index:03d}.fasta', base64.b64decode(item['contentBase64'], validate=True))
            if succeeded:
                archive.writestr('synthesis.fasta', fasta)
                archive.writestr('synthesis.xlsx', excel)
        files.append(exported('records.zip', 'application/zip', bundle.getvalue()))
        print(json.dumps({'ok': True, 'result': report, 'files': files}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'requestMayHaveExecuted': network_attempts > 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
