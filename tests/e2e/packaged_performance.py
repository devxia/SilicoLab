"""Bounded installed-app startup/close/idle observations, not a global benchmark."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).with_name('fixtures')))
from packaged_app import PackagedApp,windows


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--app',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();rows=[]
    for run in range(3):
        with tempfile.TemporaryDirectory(prefix='silicolab-package-perf-') as directory:
            owner=PackagedApp(args.app,Path(directory)/'app-data')
            try:
                gui=owner.launch();time.sleep(.5)
                samples=[]
                for _ in range(3):
                    values=subprocess.check_output(['ps','-p',str(gui.pid)+','+str(owner.info['pid']),'-o','pid=,rss=,%cpu='],text=True)
                    samples.append([{'pid':int(row.split()[0]),'rssKiB':int(row.split()[1]),'cpuPercent':float(row.split()[2])} for row in values.splitlines()]);time.sleep(.5)
                start=time.monotonic();assert owner.command('--close-window').returncode==0;gui.wait(timeout=15);elapsed=time.monotonic()-start
                assert not windows(gui.pid);assert owner.api('/projects')==[]
                rows.append({'startupSeconds':owner.startup_seconds,'closeSeconds':elapsed,'idleSamples':samples})
            finally:owner.close()
    result={'runs':rows,'startupMedianSeconds':statistics.median(r['startupSeconds'] for r in rows),'closeMedianSeconds':statistics.median(r['closeSeconds'] for r in rows),'scope':'real Cocoa window+independent service; no projects/models; ps RSS is not physical footprint','historicalManualAppWindowSeconds':1.122,'historicalManualAppCloseSeconds':.147}
    assert result['startupMedianSeconds']<5 and result['closeMedianSeconds']<.8,'Unexplained packaged lifecycle regression'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
