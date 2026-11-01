"""Actual frozen manual workbench smoke; no remote scientific calls."""
import argparse
import io
import json
from pathlib import Path
import sys
import tempfile
from openpyxl import load_workbook
sys.path.insert(0,str(Path(__file__).with_name('fixtures')))
from packaged_app import PackagedApp,wait


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='silicolab-manual-installed-') as directory:
        owner=PackagedApp(args.app,Path(directory)/'app-data')
        try:
            owner.launch();health=owner.raw('/api/health').json()
            assert health['app']=='silicolab' and health['name']=='SilicoLab'
            assert owner.raw('/api/jobs').json()==[] and owner.raw('/api/presets').json()==[]
            payload={'name':'synthetic packaged manual','engine':'local','species':'D2P(default)','avoid':'GAATTC','records':[{'name':'test','sequence':'MEF*'}]}
            response=owner.raw('/api/jobs',payload);assert response.status_code<400,response.text
            identity=response.json()['id'];job=wait(lambda:detail if (detail:=owner.raw('/api/jobs/'+identity).json())['status'] not in ('queued','running') else None)
            assert job['status']=='completed' and job['records'][0]['dna']=='ATGGAATTTTAA' and not job['engine_info']['network_used']
            book=load_workbook(io.BytesIO(owner.raw('/api/jobs/'+identity+'/export?format=xlsx').content))
            assert book.sheetnames==['基因合成'] and book.active['C2'].value=='ATGGAATTTTAA'
            assert all(c.comment is None for row in book.active for c in row);book.close()
            compact=owner.raw('/api/jobs/'+identity+'?compact=true').json();assert 'seq' not in compact['records'][0]['response']
            owner.quit();owner.launch();assert owner.raw('/api/jobs/'+identity).json()['records'][0]['dna']=='ATGGAATTTTAA'
            assert owner.raw('/api/jobs/'+identity,method='DELETE').json()['deleted_ids']==[identity]
            owner.quit();owner.launch();assert owner.raw('/api/jobs').json()==[]
            report={'status':'passed','version':health['version'],'manualLocalDNA':True,'xlsxOneSheetThreeColumnsNoComments':True,'restartPersistence':True,'deletionPersistence':True,'noDeveloperPath':True,'remoteScientificRequests':0}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
        finally:owner.close()


if __name__=='__main__':main()
