"""SilicoLab local API. Run with: python3 -m uvicorn silicolab.server:create_app --factory --host 127.0.0.1 --port 8765."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import io
import inspect
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Annotated, Callable, Literal
from urllib.error import HTTPError
from urllib.parse import urlparse
import uuid
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from silicolab.features.codon import client as codon
from silicolab.branding import APP_NAME, APP_VERSION, DATABASE_FILENAME, SERVICE_ID
from silicolab.features.codon.engines import LOCAL, REMOTE, d2p, engine_metadata, run_local, validate_engine, verify_local_version, with_engine_defaults
from silicolab.features.codon.spreadsheets import MAX_FILE_BYTES, SpreadsheetError, inspect_table, synthesis_workbook

from silicolab.paths import frontend_directory, browser_database
KNOWN_SPECIES = [
    "D2P(default)", "Escherichia_coli", "Chinsese_hamster_ovary(CHO)_cells",
    "Pichia_pastoris", "Saccharomyces_cerevisiae", "Bacillus_subtilis",
    "Clostridium_acetobutylicum", "Kluyveromyces_lactis", "Pseudomonas_fluorescens",
]
ACTIVE = {"queued", "running", "stopping"}
FINISHED_RECORDS = {"completed", "warning", "failed", "stopped", "interrupted"}


def now():
    return datetime.now(timezone.utc).isoformat()


class RecordInput(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    sequence: str = Field(min_length=1, max_length=100000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("序列名称不能为空或包含控制字符")
        return value.strip()

    @field_validator("sequence")
    @classmethod
    def clean_sequence(cls, value):
        return codon.normalize_sequence(value)


class Parameters(BaseModel):
    engine: Literal["remote", "local"] = REMOTE
    species: str = Field(default=codon.DEFAULT_SPECIES, min_length=1, max_length=150)
    avoid: str = Field(default="", max_length=2000)

    @field_validator("avoid")
    @classmethod
    def clean_avoid(cls, value):
        return codon.normalize_avoid(value)

    @field_validator("species")
    @classmethod
    def clean_species(cls, value):
        if value not in KNOWN_SPECIES:
            raise ValueError("请选择列表中的目标宿主")
        return value

    @model_validator(mode="after")
    def compatible_engine(self):
        validate_engine(self.engine, self.species, self.avoid)
        return self


class JobInput(Parameters):
    stop_policy: Literal["preserve", "add"] = "preserve"
    name: str = Field(min_length=1, max_length=200)
    records: list[RecordInput] = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("任务名称不能为空或包含控制字符")
        return value.strip()


class PresetInput(Parameters):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("预设名称不能为空")
        return value.strip()


class DeleteJobsInput(BaseModel):
    ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(min_length=1, max_length=1000)


class Store:
    """Persist complete, small job snapshots under one process-wide lock."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.revision = 0
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created TEXT, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS presets (id TEXT PRIMARY KEY, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS job_index (id TEXT PRIMARY KEY, created TEXT, status TEXT, engine TEXT, payload TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS job_index_status ON job_index(status, created)")
            # One-time, streaming backfill: never hold all raw history in memory.
            for row in db.execute("SELECT j.payload FROM jobs j LEFT JOIN job_index i ON j.id=i.id WHERE i.id IS NULL"):
                self._index(db, with_engine_defaults(json.loads(row[0])))
        self.path.chmod(0o600)
        # Decode only interrupted active jobs, not completed history.
        for job_id in self.ids_with_status(ACTIVE):
            job = self.get(job_id)
            job["status"] = "interrupted"
            for record in job["records"]:
                if record["status"] in {"pending", "running", "validating"}:
                    record.update(status="interrupted", error="程序上次关闭时任务尚未完成，可手动重新提交。")
            self.save(job)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def jobs(self):
        with self.lock, self.connect() as db:
            return [with_engine_defaults(json.loads(row[0])) for row in db.execute("SELECT payload FROM jobs ORDER BY created DESC")]

    @staticmethod
    def _index(db, job):
        item = summary(job)
        db.execute("INSERT OR REPLACE INTO job_index VALUES (?, ?, ?, ?, ?)",
                   (job["id"], job["created_at"], job["status"], job.get("engine", REMOTE),
                    json.dumps(item, ensure_ascii=False)))

    def summaries(self):
        with self.lock, self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM job_index ORDER BY created DESC")]

    def ids_with_status(self, statuses, engine=None):
        values = sorted(statuses)
        if not values:
            return []
        query = "SELECT id FROM job_index WHERE status IN (" + ",".join("?" * len(values)) + ")"
        if engine is not None:
            query += " AND engine=?"
            values.append(engine)
        with self.lock, self.connect() as db:
            return [row[0] for row in db.execute(query + " ORDER BY created ASC", values)]

    def active_count(self):
        return len(self.ids_with_status(ACTIVE))

    def get(self, job_id):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        return with_engine_defaults(json.loads(row[0]))

    def save(self, job):
        with self.lock, self.connect() as db:
            job["updated_at"] = now()
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)",
                       (job["id"], job["created_at"], json.dumps(job, ensure_ascii=False)))
            self._index(db, with_engine_defaults(job))
            self.revision += 1

    def mutate(self, job_id, update):
        with self.lock:
            job = self.get(job_id)
            update(job)
            self.save(job)
            return job

    def delete_jobs(self, job_ids):
        identifiers = list(dict.fromkeys(job_ids))
        if not identifiers or len(identifiers) > 1000:
            raise HTTPException(422, "每次请选择 1–1000 个任务")
        placeholders = ','.join('?' for _ in identifiers)
        with self.lock:
            with self.connect() as db:
                # Serialize with retry/worker writes, including other DB connections.
                db.execute("BEGIN IMMEDIATE")
                rows = list(db.execute(f"SELECT id, status FROM job_index WHERE id IN ({placeholders})", identifiers))
                if len(rows) != len(identifiers):
                    raise HTTPException(404, "部分任务已不存在，请刷新列表后重试；本次未删除任何任务")
                if any(status in ACTIVE for _, status in rows):
                    raise HTTPException(409, "包含排队、运行或正在停止的任务，请先停止并等待结束；本次未删除任何任务")
                db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", identifiers)
                db.execute(f"DELETE FROM job_index WHERE id IN ({placeholders})", identifiers)
            # Notify only after the two-table transaction has committed.
            self.revision += 1
        return {"deleted_ids": identifiers, "deleted_count": len(identifiers)}

    def presets(self):
        with self.lock, self.connect() as db:
            return [{"engine": REMOTE} | json.loads(row[0])
                    for row in db.execute("SELECT payload FROM presets ORDER BY rowid DESC")]

    def save_preset(self, preset):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO presets VALUES (?, ?)", (preset["id"], json.dumps(preset, ensure_ascii=False)))
            self.revision += 1

    def delete_preset(self, preset_id):
        with self.lock, self.connect() as db:
            cursor = db.execute("DELETE FROM presets WHERE id=?", (preset_id,))
            if cursor.rowcount == 0:
                raise HTTPException(404, "预设不存在")
            self.revision += 1


def summary(job):
    records = job["records"]
    return {key: value for key, value in job.items() if key != "records"} | {
        "total": len(records),
        "completed": sum(record["status"] == "completed" for record in records),
        "failed": sum(record["status"] in {"failed", "warning"} for record in records),
        "done": sum(record["status"] in FINISHED_RECORDS for record in records),
        "amino_acids": sum(len(record["sequence"].rstrip("*")) for record in records),
    }


async def default_optimizer(payload):
    from silicolab.features.codon.transport import optimize_remote
    return await optimize_remote(payload)


def checks_for(dna, protein, avoid):
    return {
        "translation": True,
        "length": True,
        "motifs": True,
        "stop": protein.endswith("*"),
        "gc": round((dna.count("G") + dna.count("C")) / len(dna) * 100, 2),
        "bp": len(dna),
        "aa": len(protein.rstrip("*")),
        "avoid_count": len(list(filter(None, avoid.split(",")))),
    }


class Worker:
    def __init__(self, store, optimizer: Callable, delay=0.5):
        self.store, self.optimizer, self.delay = store, optimizer, delay
        self.wake = asyncio.Event()

    async def run(self):
        while True:
            self.wake.clear()
            queued = self.store.ids_with_status({"queued"})
            if not queued:
                await self.wake.wait()
                continue
            await self.process(queued[0])

    async def process(self, job_id):
        self.store.mutate(job_id, lambda job: job.update(status="running"))
        for index in range(len(self.store.get(job_id)["records"])):
            job = self.store.get(job_id)
            if job["status"] == "stopping":
                break
            record = job["records"][index]
            if record["status"] != "pending":
                continue
            payload = {"fileName": record["name"], "jumpName": "pep", "sequence": record["sequence"],
                       "speciesName": job["species"], "ignoreCodonQueue": job["avoid"]}
            started = time.monotonic()
            self.store.mutate(job_id, lambda current: current["records"][index].update(
                status="running", error=None, started_at=now()))
            raw = None
            pause = False
            try:
                if job["engine"] == LOCAL:
                    raw = await asyncio.to_thread(run_local, payload, job["engine_info"])
                elif inspect.iscoroutinefunction(self.optimizer):
                    raw = await self.optimizer(payload)
                else:
                    raw = await asyncio.to_thread(self.optimizer, payload)
                self.store.mutate(job_id, lambda current: current["records"][index].update(status="validating"))
                dna = codon.validate_result(raw, record["sequence"], job["avoid"])
                change = {"status": "completed", "dna": dna, "checks": checks_for(dna, record["sequence"], job["avoid"])}
            except d2p.LocalOptimizationError as exc:
                change = {"status": "failed", "error": str(exc)}
            except codon.OptimizationError as exc:
                raw = exc.response if exc.response is not None else raw
                change = {"status": "warning" if raw is not None else "failed", "error": str(exc)}
                cause = exc.__cause__
                pause = isinstance(cause, HTTPError) and cause.code in {401, 403, 429}
            except Exception as exc:
                change = {"status": "failed", "error": f"请求未完成：{type(exc).__name__}。可手动重试该序列。"}
            change.update(response=raw, finished_at=now(), elapsed=round(time.monotonic() - started, 2))

            def finish(current):
                current_record = current["records"][index]
                current_record.update(change)
                current_record["attempts"].append({
                    "started_at": current_record["started_at"], "finished_at": change["finished_at"],
                    "status": change["status"], "error": change.get("error"), "response": raw,
                    "engine": current["engine"], "engine_info": current["engine_info"],
                })
                if pause:
                    current.update(status="paused", message="服务端要求登录或限制访问，队列已暂停。请稍后检查服务状态再重试。")
            self.store.mutate(job_id, finish)
            if pause:
                for queued_id in self.store.ids_with_status({"queued"}, REMOTE):
                    self.store.mutate(queued_id, lambda current: current.update(
                        status="paused", message="优化服务限制访问，已暂停后续提交。可稍后手动重试。"))
                return
            await asyncio.sleep(self.delay if job["engine"] == REMOTE else 0)

        def finish_job(job):
            if job["status"] == "stopping":
                for record in job["records"]:
                    if record["status"] == "pending":
                        record.update(status="stopped", error="已停止后续提交")
                job["status"] = "stopped"
            else:
                completed = sum(record["status"] == "completed" for record in job["records"])
                job["status"] = "completed" if completed == len(job["records"]) else "partial" if completed else "failed"
        self.store.mutate(job_id, finish_job)


def create_app(db_path=None, optimizer=None, delay=0.5):
    database = db_path or browser_database()
    store = Store(database)
    worker = Worker(store, optimizer or default_optimizer, delay)
    from silicolab.workbench import Workbench, router as workbench_router
    workbench = Workbench(Path(database).with_name('projects.json'))

    @asynccontextmanager
    async def lifespan(app):
        app.state.loop = asyncio.get_running_loop()
        task = asyncio.create_task(worker.run())
        app.state.worker_task = task
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        workbench.close()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    app.state.store = store
    app.state.worker = worker
    app.state.stopping = asyncio.Event()
    app.state.workbench = workbench
    app.include_router(workbench_router(workbench))

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Reject external sites trying to use the local service, including DNS rebinding.
        host = request.url.hostname
        origin = request.headers.get("origin")
        if host not in {"127.0.0.1", "localhost", "testserver", "::1"}:
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        if request.url.path.startswith("/api") and origin:
            if urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
                return JSONResponse({"detail": "不允许此来源访问本地服务"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"app": SERVICE_ID, "name": APP_NAME, "pid": os.getpid(), "status": "ok", "version": APP_VERSION, "active": store.active_count()}

    species_cache = {"items": KNOWN_SPECIES.copy(), "checked_at": None, "online": None}

    @app.get("/api/species")
    async def species(refresh: bool = False, cached: bool = False):
        if not cached and (refresh or species_cache["checked_at"] is None):
            try:
                items = await asyncio.to_thread(codon.list_species, 15)
                species_cache.update(items=list(dict.fromkeys([codon.DEFAULT_SPECIES] + items)), online=True, checked_at=now())
            except codon.OptimizationError:
                species_cache.update(online=False, checked_at=now())
        return species_cache

    @app.post("/api/import/table")
    async def import_table(request: Request, filename: str):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_FILE_BYTES:
                raise HTTPException(413, "文件超过 5 MB，请分批导入")
        try:
            return await asyncio.to_thread(inspect_table, bytes(content), filename)
        except SpreadsheetError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/jobs")
    async def jobs():
        return store.summaries()

    @app.post("/api/jobs", status_code=201)
    async def create_job(body: JobInput):
        if body.engine == REMOTE and store.ids_with_status({"paused"}, REMOTE):
            raise HTTPException(409, "队列因服务限制暂停，请先检查服务并手动重试已暂停的任务")
        if store.active_count() >= 10:
            raise HTTPException(409, "当前队列已满，请等待部分任务完成")
        records = []
        for item in body.records:
            add_stop = body.stop_policy == "add" and not item.sequence.endswith("*")
            try:
                sequence = codon.normalize_sequence(item.sequence + ("*" if add_stop else ""))
            except ValueError as exc:
                raise HTTPException(422, f"{item.name}：{exc}") from exc
            records.append({"id": str(uuid.uuid4()), "name": item.name, "sequence": sequence,
                            "original_sequence": item.sequence, "stop_added": add_stop,
                            "status": "pending", "dna": None, "checks": None, "response": None,
                            "error": None, "attempts": []})
        job = {"id": str(uuid.uuid4()), "name": body.name, "species": body.species, "avoid": body.avoid,
               "engine": body.engine, "engine_info": engine_metadata(body.engine),
               "stop_policy": body.stop_policy,
               "status": "queued", "created_at": now(), "message": None,
               "records": records}
        store.save(job)
        worker.wake.set()
        return job

    @app.post("/api/jobs/bulk-delete")
    async def bulk_delete_jobs(body: DeleteJobsInput):
        return store.delete_jobs(body.ids)

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str):
        return store.delete_jobs([job_id])

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, compact: bool = False):
        job = store.get(job_id)
        if compact:
            # UI needs DNA/checks but not raw per-codon data or repeated attempt payloads.
            for record in job["records"]:
                response = record.get("response")
                if isinstance(response, dict):
                    record["response"] = {key: value for key, value in response.items()
                                          if key not in {"data", "seq"}}
                record["attempts"] = []
        return job

    @app.post("/api/jobs/{job_id}/stop")
    async def stop_job(job_id: str):
        def stop(job):
            if job["status"] not in ACTIVE:
                raise HTTPException(409, "此任务已结束")
            if job["status"] == "queued":
                job["status"] = "stopped"
                for record in job["records"]:
                    if record["status"] == "pending":
                        record.update(status="stopped", error="已停止后续提交")
            else:
                job["status"] = "stopping"
        return store.mutate(job_id, stop)

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        def retry(job):
            if job["status"] in ACTIVE:
                raise HTTPException(409, "请等待当前任务结束后再重试")
            if job["engine"] == LOCAL:
                try:
                    verify_local_version(job["engine_info"])
                except d2p.LocalOptimizationError as exc:
                    raise HTTPException(409, str(exc)) from exc
            retryable = [record for record in job["records"] if record["status"] != "completed"]
            if not retryable:
                raise HTTPException(409, "所有序列均已完成")
            for record in retryable:
                record.update(status="pending", dna=None, checks=None, response=None, error=None,
                              started_at=None, finished_at=None, elapsed=None)
            job.update(status="queued", message=None)
        job = store.mutate(job_id, retry)
        worker.wake.set()
        return job

    @app.get("/api/jobs/{job_id}/export")
    async def export_job(job_id: str, format: str = "fasta", record_id: str | None = None):
        job = store.get(job_id)
        records = job["records"]
        if record_id:
            records = [record for record in records if record["id"] == record_id]
            if not records:
                raise HTTPException(404, "序列不存在")
        valid = [record for record in records if record["status"] == "completed"]
        fasta = "".join(f">{record['name']}\n" + "\n".join(record["dna"][i:i + 80]
                         for i in range(0, len(record["dna"]), 80)) + "\n" for record in valid)
        basename = f"codon-{job['id'][:8]}"
        if format == "fasta":
            if not valid:
                raise HTTPException(409, "还没有通过校验的结果可供导出")
            return Response(fasta, media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{basename}.fasta"'})
        if format == "xlsx":
            if not valid:
                raise HTTPException(409, "还没有通过校验的结果可供导出")
            content = await asyncio.to_thread(synthesis_workbook, records)
            return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{basename}.xlsx"'})
        if format != "zip":
            raise HTTPException(400, "仅支持 fasta、xlsx 或 zip")
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("optimized.fasta", fasta)
            archive.writestr("record.json", json.dumps(job | {"records": records}, ensure_ascii=False, indent=2))
            archive.writestr("README.txt", "SilicoLab\noptimized.fasta 仅包含通过校验的结果。\nrecord.json 包含输入、参数、引擎及版本、状态、原始响应及历次尝试。\n")
        return Response(content.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{basename}.zip"'})

    @app.get("/api/presets")
    async def presets():
        return store.presets()

    @app.post("/api/presets", status_code=201)
    async def create_preset(body: PresetInput):
        if len(store.presets()) >= 100:
            raise HTTPException(409, "最多保存 100 个预设")
        preset = body.model_dump() | {"id": str(uuid.uuid4()), "created_at": now()}
        store.save_preset(preset)
        return preset

    @app.delete("/api/presets/{preset_id}")
    async def delete_preset(preset_id: str):
        store.delete_preset(preset_id)
        return {"ok": True}

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = -1
            ticks = 0
            while not app.state.stopping.is_set() and not await request.is_disconnected():
                if store.revision != previous:
                    previous = store.revision
                    yield f"event: change\ndata: {previous}\n\n"
                elif ticks % 15 == 0:
                    yield ": keepalive\n\n"
                ticks += 1
                try:
                    await asyncio.wait_for(app.state.stopping.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = frontend_directory()
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        async def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "接口不存在")
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    return app
