"""Run the synthetic macOS boundary checks and print evidence without local paths."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

from execution import PythonProbe


def main():
    directory = Path(__file__).resolve().parent
    for source in directory.glob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"), filename=source.name)
    with PythonProbe() as host:
        environment = host.environment
    suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    print(json.dumps({
        "scope": "issue-3-local-macos-single-process-python-probe",
        "result": "passed",
        "tests": result.testsRun,
        "environment": environment,
        "source_sha256": {source.name: hashlib.sha256(source.read_bytes()).hexdigest()
                          for source in sorted(directory.glob("*.py"))},
        "delivery_status": "local boundary experiment passed; production generated-code delivery remains gated",
        "limits": [
            "Deprecated sandbox-exec, only the current local macOS/Python combination was exercised.",
            "Fork/spawn is denied, Python-only re-exec retains policy; multiprocessing is unsupported.",
            "No real credentials, external network requests, model/science providers or application integration.",
            "No signed/notarized app, crash-supervisor, hostile-kernel, remote-volume or availability proof.",
            "Read-only OS/stdlib runtime resources, bounded metadata, stdout/stderr and selected inputs are necessary exceptions.",
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
