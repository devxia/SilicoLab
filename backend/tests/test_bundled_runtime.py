"""Frozen resource/worker contract; never falls back to developer runtime paths."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from silicolab import bundled_runtime as runtime


class BundledRuntimeTests(unittest.TestCase):
    def test_frozen_paths_ignore_ambient_developer_overrides_and_workers_use_fixed_subcommands(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();resources=root/'Resources';frameworks=root/'Frameworks';frameworks.mkdir()
            (resources/'runtime/bin').mkdir(parents=True);(resources/'backend-src/silicolab').mkdir(parents=True)
            for name in ('runtime','backend-src'):(frameworks/name).symlink_to('../Resources/'+name)
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(frameworks),create=True),patch.dict('os.environ',{'SILICOLAB_NODE':'/untrusted/node','SILICOLAB_RUNTIME':'/untrusted/runtime'}):
                self.assertEqual(runtime.node_runtime(),(resources/'runtime',str(resources/'runtime/bin/node')))
                self.assertEqual(runtime.backend_sources(),resources/'backend-src/silicolab')
                self.assertEqual(runtime.worker_command('science_supervisor',27),[sys.executable,'--science-supervisor','27'])
                self.assertEqual(runtime.worker_command('science_worker'),[sys.executable,'--science-worker','local'])
                self.assertEqual(runtime.worker_command('remote_science_worker'),[sys.executable,'--science-worker','remote'])
                with self.assertRaises(ValueError):runtime.worker_command('arbitrary_module')

    def test_source_worker_remains_isolated_and_explicit(self):
        with patch.object(sys,'frozen',False,create=True):
            command=runtime.worker_command('science_supervisor',27)
            self.assertEqual(command[:4],[sys.executable,'-I','-B','-c'])
            self.assertEqual(command[-1],'27')
            self.assertIn('silicolab.science_supervisor',command[4])
            self.assertEqual(runtime.backend_sources().name,'silicolab')


if __name__=='__main__':unittest.main()
