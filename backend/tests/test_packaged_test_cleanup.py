"""Test harness failures must restore build directories and avoid permission requests."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/e2e/fixtures'))
import packaged_app


class PackagedCleanupTests(unittest.TestCase):
    def test_hidden_builder_restored_when_owner_initialization_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            builder=Path(directory)/'builder';builder.mkdir();(builder/'public-source').write_text('untouched')
            with self.assertRaisesRegex(OSError,'artificial'):
                with packaged_app.hidden_builder(builder):
                    self.assertFalse(builder.exists())
                    raise OSError('artificial owner initialization failed')
            self.assertEqual((builder/'public-source').read_text(),'untouched')
            self.assertFalse(builder.with_name(builder.name+'-temporarily-unavailable').exists())

    def test_notification_permission_preflight_failure_does_not_call_service_or_enable(self):
        spec=importlib.util.spec_from_file_location('installed_notices',ROOT/'tests/e2e/packaged_notifications.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Owner:
            def __init__(self,*args):self.app=Path('/artificial/SilicoLab.app');self.info=None;self.closed=False
            def launch(self):raise AssertionError('permission preflight must run first')
            def api(self,*args,**kwargs):raise AssertionError('no service operation before grant')
            def close(self):self.closed=True
        class Center:
            def __init__(self,*args):self.operations=[]
            def call(self,op):self.operations.append(op);return {'authorization':0}
            def close(self):pass
        owner=Owner();center=Center()
        with patch.object(module,'PackagedApp',return_value=owner),patch.object(module,'NativeNotifications',return_value=center),patch.object(sys,'argv',['check','--app','/artificial/app','--output','/unused.json']):
            with self.assertRaisesRegex(AssertionError,'Permission must already'):module.main()
        self.assertTrue(owner.closed);self.assertEqual(center.operations,['status'])


if __name__=='__main__':unittest.main()
