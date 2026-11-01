"""Local executor startup must not depend on DNS or a machine hostname."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from silicolab.simulated_executor import SimulatedExecutor


class LoopbackExecutorTests(unittest.TestCase):
    def test_loopback_server_binds_without_any_hostname_lookup(self):
        with tempfile.TemporaryDirectory() as directory,patch('socket.getfqdn',side_effect=AssertionError('local executor must not resolve a hostname')):
            executor=SimulatedExecutor(Path(directory)/'jobs.sqlite3')
            try:
                self.assertTrue(executor.url.startswith('http://127.0.0.1:'))
                self.assertEqual(executor.info()['createdJobs'],0)
            finally:executor.close()


if __name__=='__main__':unittest.main()
