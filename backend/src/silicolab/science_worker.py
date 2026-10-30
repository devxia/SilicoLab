"""Trusted structured science worker. Never executes model-generated code."""
import base64
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import zipfile


def main():
    network_attempts = 0
    def deny_network(event, _args):
        nonlocal network_attempts
        if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo', 'urllib.Request', 'http.client.connect'}:
            network_attempts += 1
            raise PermissionError('Scientific local worker forbids network operations')
    sys.addaudithook(deny_network)
    try:
        socket.socket()
        raise RuntimeError('network guard self-test failed')
    except PermissionError:
        pass
    baseline = network_attempts
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('scientific input exceeds worker limit')
        request = json.loads(raw)
        if request.get('workflow') != 'd2p_local' or request.get('specialtyAcknowledged') is not True:
            raise ValueError('Requires explicit D2P/pD2P_1.08t local-experiment request')
        from silicolab.features.codon import client as codon
        from silicolab.features.codon.engines import LOCAL, engine_metadata, run_local
        from silicolab.features.codon.spreadsheets import synthesis_workbook
        parameters = request['parameters']
        preflight = request.get('operation') == 'preflight'
        if parameters.get('stopPolicy') not in ({'preserve', 'add', 'ask'} if preflight else {'preserve', 'add'}):
            raise ValueError('Select terminal-stop handling before execution')
        avoid = codon.normalize_avoid(parameters.get('avoid', ''))
        metadata = engine_metadata(LOCAL)
        sources = []
        with tempfile.TemporaryDirectory(prefix='silicolab-local-science-') as directory:
            for index, item in enumerate(request['inputs']):
                source = Path(directory) / f'input-{index}.fasta'
                source.write_bytes(base64.b64decode(item['contentBase64'], validate=True))
                sources.extend((item, name, protein) for name, protein in codon.read_fasta(source))
        # Admission limits are checked before computing any sequence, not after successes.
        if len(sources) > 200:
            raise ValueError('A task supports at most 200 sequences')
        if sum(len(protein) for _, _, protein in sources) > 200000:
            raise ValueError('A task supports at most 200,000 total amino-acid characters')
        if preflight:
            missing = [name for _, name, protein in sources if not protein.endswith('*')]
            report = {'status': 'preflight', 'inputVersionId': request['inputVersionId'], 'engine_info': metadata,
                      'records': [], 'missingStopNames': missing, 'network_attempts': network_attempts - baseline,
                      'network_guard_self_test': 'blocked', 'scope': 'D2P local input inspection; no algorithm executed'}
            print(json.dumps({'ok': True, 'result': report, 'files': []}, ensure_ascii=False))
            return
        records = []
        for item, name, protein in sources:
            original = protein
            record = {'name': name, 'protein': protein, 'original_protein': original,
                      'source_file_id': item['fileId'], 'source_sha256': item['sha256'],
                      'parameters': {'stopPolicy': parameters['stopPolicy'], 'avoid': avoid},
                      'status': 'failed'}
            try:
                if len(name) > 300 or any(ord(char) < 32 for char in name):
                    raise ValueError('序列名称过长或包含控制字符')
                if parameters['stopPolicy'] == 'add' and not protein.endswith('*'):
                    protein = codon.normalize_sequence(protein + '*')
                record['protein'] = protein
                payload = {'fileName': name, 'jumpName': 'pep', 'sequence': protein,
                           'ignoreCodonQueue': avoid, 'speciesName': codon.DEFAULT_SPECIES}
                response = run_local(payload, metadata)
                record['raw_response'] = response
                dna = codon.validate_result(response, protein, avoid)
                record.update(status='completed', dna=dna, terminal_stop_present=protein.endswith('*'),
                              checks={'characters': True, 'length': True, 'translation': True,
                                      'stop_policy': True, 'avoid_both_strands': True})
            except (ValueError, codon.OptimizationError) as error:
                record['error'] = str(error)
            records.append(record)
        succeeded = [record for record in records if record['status'] == 'completed']
        status = 'completed' if len(succeeded) == len(records) and records else 'partial' if succeeded else 'failed'
        fasta = ''.join(f'>{record["name"]}\n{record["dna"]}\n' for record in succeeded).encode()
        report = {'status': status, 'inputVersionId': request['inputVersionId'], 'engine_info': metadata,
                  'records': records, 'network_attempts': network_attempts - baseline,
                  'network_guard_self_test': 'blocked', 'scope': 'D2P/pD2P_1.08t/predefined insertion; no vector validation implemented',
                  'attempt': request['attempt']}
        files = []
        def exported(name, media_type, content):
            return {'name': name, 'mediaType': media_type, 'contentBase64': base64.b64encode(content).decode()}
        excel = synthesis_workbook(records) if succeeded else None
        if succeeded:
            files = [exported('synthesis.fasta', 'text/plain; charset=utf-8', fasta),
                     exported('synthesis.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', excel)]
            files += [exported(f'sequence-{index:03d}.fasta', 'text/plain; charset=utf-8',
                               f'>{record["name"]}\n{record["dna"]}\n'.encode())
                      for index, record in enumerate(records, 1) if record['status'] == 'completed']
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('record.json', json.dumps(report, ensure_ascii=False))
            archive.writestr('task.json', json.dumps(request['task'], ensure_ascii=False))
            fixed = {key: value for key, value in request['inputVersion'].items() if key != 'inputs'}
            fixed['inputs'] = [{key: value for key, value in item.items() if key != 'contentBase64'} for item in request['inputs']]
            archive.writestr('input-version.json', json.dumps(fixed, ensure_ascii=False))
            for index, item in enumerate(request['inputs'], 1):
                archive.writestr(f'inputs/{index:03d}.fasta', base64.b64decode(item['contentBase64'], validate=True))
            if succeeded:
                archive.writestr('synthesis.fasta', fasta)
                archive.writestr('synthesis.xlsx', excel)
        files.append(exported('records.zip', 'application/zip', bundle.getvalue()))
        print(json.dumps({'ok': True, 'result': report, 'files': files}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'network_attempts': network_attempts - baseline}, ensure_ascii=False))


if __name__ == '__main__':
    main()
