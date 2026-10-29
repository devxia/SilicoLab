import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import httpx
from fastapi.testclient import TestClient

from silicolab.features.codon import client as codon
from silicolab.features.codon.transport import optimize_remote
from silicolab.server import create_app


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_json_and_rate_limit_match_existing_errors(self):
        real_client = httpx.AsyncClient
        async def success(request):
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('authorization', request.headers)
            self.assertEqual(json.loads(request.content)['sequence'], 'MK')
            return httpx.Response(200, json={'success': '1', 'seq': 'ATGAAG'})
        with patch('httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(success), **kwargs)):
            self.assertEqual((await optimize_remote({'sequence': 'MK'}))['seq'], 'ATGAAG')
        async def limited(request):
            return httpx.Response(429, text='limited')
        with patch('httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(limited), **kwargs)):
            with self.assertRaises(codon.OptimizationError) as caught:
                await optimize_remote({'sequence': 'MK'})
        self.assertIsInstance(caught.exception.__cause__, HTTPError)
        self.assertEqual(caught.exception.__cause__.code, 429)

    async def test_cancellation_releases_pending_request(self):
        real_client = httpx.AsyncClient
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def pending(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(pending), **kwargs)):
            task = asyncio.create_task(optimize_remote({'sequence': 'MK'}))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())

    async def test_html_is_reported_without_leaking_response(self):
        real_client = httpx.AsyncClient
        with patch('httpx.AsyncClient', side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='<html>not JSON</html>')), **kwargs)):
            with self.assertRaisesRegex(codon.OptimizationError, 'JSON'):
                await optimize_remote({'sequence': 'MK'})


class WorkerCancellationTests(unittest.TestCase):
    def test_real_worker_awaits_and_cancels_async_remote_without_executor(self):
        import threading
        entered, cancelled = threading.Event(), threading.Event()
        async def pending(payload):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with tempfile.TemporaryDirectory() as directory, patch('silicolab.features.codon.transport.optimize_remote', side_effect=pending), patch('silicolab.features.codon.client.request_json', side_effect=AssertionError('No network or blocking executor')):
            app = create_app(Path(directory) / 'db.sqlite3')
            with TestClient(app) as client:
                response = client.post('/api/jobs', json={'name': 'pending', 'records': [{'name': 'a', 'sequence': 'MK'}]})
                self.assertEqual(response.status_code, 201)
                self.assertTrue(entered.wait(1), 'Worker did not use the cancellable async remote transport')
            self.assertTrue(cancelled.is_set())
            job = app.state.store.get(response.json()['id'])
            self.assertNotEqual(job['records'][0]['status'], 'completed')
