"""Persistent loopback-only simulated executor; no scientific software or external network."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sqlite3
from socketserver import TCPServer
import threading
import time
from urllib.parse import parse_qs, urlparse
import uuid


class SimulatedExecutor:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS service (id TEXT NOT NULL)')
            if db.execute('SELECT id FROM service').fetchone() is None:
                db.execute('INSERT INTO service VALUES (?)', (str(uuid.uuid4()),))
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                request_key TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                payload_hash TEXT NOT NULL, ready_at REAL NOT NULL, state TEXT NOT NULL,
                queryable INTEGER NOT NULL, submit_attempts INTEGER NOT NULL)''')
        executor = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def reply(self, code, value):
                raw = json.dumps(value, ensure_ascii=False).encode()
                try:
                    self.send_response(code)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass
            def do_GET(self):
                try:
                    parsed = urlparse(self.path)
                    if parsed.path == '/info':
                        self.reply(200, executor.info())
                        return
                    if parsed.path != '/find':
                        self.reply(404, {'error': 'unsupported simulated operation'})
                        return
                    key = parse_qs(parsed.query).get('requestKey', [''])[0]
                    self.reply(200, executor.find(key))
                except (OSError, sqlite3.Error) as error:
                    self.reply(503, {'error': str(error)})
            def do_POST(self):
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if length > 100000:
                        raise ValueError('simulated request exceeds limit')
                    data = json.loads(self.rfile.read(length))
                    if self.path == '/submit':
                        job = executor.submit(data)
                        # Fault occurs after the independent durable acceptance, before the receipt.
                        if data.get('responseMode') == 'hold_after_accept':
                            time.sleep(3)
                        if data.get('responseMode') == 'lost':
                            self.reply(503, {'error': 'simulated accepted job with lost receipt'})
                        else:
                            self.reply(200, job)
                    elif self.path == '/cancel':
                        self.reply(200, executor.cancel(data['requestKey']))
                    else:
                        self.reply(404, {'error': 'unsupported simulated operation'})
                except (ValueError, KeyError, OSError, sqlite3.Error) as error:
                    self.reply(400 if isinstance(error, (ValueError, KeyError)) else 503, {'error': str(error)})
        class LoopbackServer(ThreadingHTTPServer):
            def server_bind(self):
                # HTTPServer's default calls getfqdn and can block on DNS, despite
                # this being an exclusively local service with no hostname use.
                TCPServer.server_bind(self)
                self.server_name='127.0.0.1';self.server_port=self.server_address[1]
        self.server = LoopbackServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def service_id(self, db):
        return db.execute('SELECT id FROM service').fetchone()['id']

    def info(self):
        with self.connect() as db:
            jobs = db.execute('SELECT request_key,id,payload_hash,state,submit_attempts FROM jobs ORDER BY rowid').fetchall()
            return {'kind': 'simulated-only', 'serviceId': self.service_id(db), 'jobs': [dict(job) for job in jobs], 'createdJobs': len(jobs)}

    def receipt(self, db, row):
        state = row['state']
        if state == 'running' and time.time() >= row['ready_at']:
            state = 'succeeded'
            db.execute('UPDATE jobs SET state=? WHERE request_key=?', (state, row['request_key']))
        result = {'kind': 'simulated-result', 'requestKey': row['request_key'], 'jobId': row['id'],
                  'payloadHash': row['payload_hash'], 'payload': row['payload'], 'characters': len(row['payload'])}
        return {'serviceId': self.service_id(db), 'requestKey': row['request_key'], 'jobId': row['id'],
                'payloadHash': row['payload_hash'], 'state': state,
                **({'result': result} if state == 'succeeded' else {}), 'simulated': True}

    def submit(self, data):
        key, payload = data['requestKey'], data['payload']
        if not isinstance(key, str) or not key or len(key) > 200 or not isinstance(payload, str) or len(payload) > 10000:
            raise ValueError('simulated key/payload invalid')
        duration = data.get('durationMs', 1000)
        if not isinstance(duration, int) or not 0 <= duration <= 60000:
            raise ValueError('simulated duration invalid')
        payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            if row is None:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)', (key, str(uuid.uuid4()), payload, payload_hash, time.time() + duration / 1000, 'running', bool(data.get('queryable', True)), 1))
            else:
                if row['payload_hash'] != payload_hash:
                    raise ValueError('request identity conflicts with prior payload')
                db.execute('UPDATE jobs SET submit_attempts=submit_attempts+1 WHERE request_key=?', (key,))
            row = db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            return self.receipt(db, row)

    def find(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            if row is None:
                return {'known': False, 'reason': 'not_found', 'serviceId': self.service_id(db)}
            if not row['queryable']:
                return {'known': False, 'reason': 'query_unsupported', 'serviceId': self.service_id(db)}
            return {'known': True, **self.receipt(db, row)}

    def cancel(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            if row is None:
                return {'known': False, 'reason': 'not_found', 'serviceId': self.service_id(db)}
            receipt = self.receipt(db, row)
            if receipt['state'] != 'succeeded':
                db.execute('UPDATE jobs SET state=? WHERE request_key=?', ('cancelled', key))
                row = db.execute('SELECT * FROM jobs WHERE request_key=?', (key,)).fetchone()
            return {'known': True, **self.receipt(db, row)}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
