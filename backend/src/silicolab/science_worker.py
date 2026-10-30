"""Trusted structured science worker. Never executes model-generated code."""
import base64
import json
from pathlib import Path
import socket
import sys
import tempfile


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
        if parameters.get('stopPolicy') not in {'preserve', 'add'}:
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
                  'network_guard_self_test': 'blocked', 'scope': 'D2P/pD2P_1.08t/predefined insertion; no vector validation implemented'}
        files = []
        if succeeded:
            files = [{'name': 'synthesis.fasta', 'mediaType': 'text/plain; charset=utf-8', 'contentBase64': base64.b64encode(fasta).decode()},
                     {'name': 'synthesis.xlsx', 'mediaType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                      'contentBase64': base64.b64encode(synthesis_workbook(records)).decode()}]
        print(json.dumps({'ok': True, 'result': report, 'files': files}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'network_attempts': network_attempts - baseline}, ensure_ascii=False))


if __name__ == '__main__':
    main()
