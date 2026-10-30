import json
from pathlib import Path
import tempfile
import unittest

from execution import PythonProbe


class AllowedAnalysisTests(unittest.TestCase):
    def test_preinstalled_analysis_produces_independently_readable_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-python-test-") as directory:
            original = Path(directory) / "values.csv"
            original.write_text("value\n1\n2\n6\n", encoding="utf-8")
            with PythonProbe() as host:
                run = host.start('''
import csv, json, statistics
from pathlib import Path
import openpyxl
values = [int(row['value']) for row in csv.DictReader(Path(INPUTS / 'values.csv').open())]
Path('analysis.json').write_text(json.dumps({'count': len(values), 'mean': statistics.mean(values)}))
workbook = openpyxl.Workbook()
workbook.active.append(['count', 'mean'])
workbook.active.append([len(values), statistics.mean(values)])
workbook.save('analysis.xlsx')
print('analysis finished')
''', inputs=[original])
                result = run.wait(timeout=12)
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(json.loads(run.artifact("analysis.json")), {"count": 3, "mean": 3})
                import io
                import openpyxl
                workbook = openpyxl.load_workbook(io.BytesIO(run.artifact("analysis.xlsx")))
                self.assertEqual(list(workbook.active.values), [("count", "mean"), (3, 3)])
                self.assertEqual(original.read_text(), "value\n1\n2\n6\n")
                self.assertEqual(result["environment"]["packages"], {"openpyxl": "3.1.5", "et-xmlfile": "2.0.0"})
                self.assertIn("analysis finished", result["stdout"])
                self.assertTrue(result["inputs_unchanged"])


if __name__ == "__main__":
    unittest.main()
