"""Test-only separate fake external service, deliberately outliving application quits."""
import json
import sys
from pathlib import Path
from silicolab.simulated_executor import SimulatedExecutor
from silicolab.desktop_lifecycle import atomic_json

root=Path(sys.argv[1])
executor=SimulatedExecutor(root/'independent-simulated.sqlite3')
atomic_json(root/'independent-executor.json',{'url':executor.url,'serviceId':executor.info()['serviceId']})
try:
    sys.stdin.read()
finally:
    executor.close()
