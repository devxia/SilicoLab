"""Route jobs to an explicit engine; local execution never falls back to HTTP."""

import hashlib
import json
from pathlib import Path

from silicolab.features.codon import client as codon
from silicolab.features.codon import local as d2p

REMOTE = "remote"
LOCAL = "local"
LOCAL_STRATEGY = "min_changed_codons_then_nucleotide_edits_v1"


def engine_metadata(engine: str) -> dict:
    if engine == REMOTE:
        return {"id": REMOTE, "label": "ProteinFactory 远端", "version": "unversioned",
                "endpoint": codon.BASE_URL + "/toDnaAjaxCodon", "network_used": True}
    if engine != LOCAL:
        raise ValueError("未知优化引擎")
    mapping = d2p.load_mapping()
    mapping_bytes = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    return {"id": LOCAL, "label": "本地实验", "version": d2p.VERSION,
            "mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
            "model_sha256": hashlib.sha256(d2p.MODEL.read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(Path(d2p.__file__).read_bytes()).hexdigest(),
            "constraint_strategy": LOCAL_STRATEGY, "max_work": 5_000_000, "network_used": False}


def validate_engine(engine: str, species: str, avoid: str):
    if engine == LOCAL:
        if species != codon.DEFAULT_SPECIES:
            raise ValueError("本地实验仅支持 D2P 默认体系，请切换宿主或选择远端")
        motifs = list(filter(None, avoid.split(",")))
        if len(motifs) > 128 or any(len(motif) > 256 for motif in motifs) or sum(map(len, motifs)) > 8192:
            raise ValueError("本地实验最多支持 128 个位点，单个位点最长 256 bp，总长最多 8192 bp")
    elif engine != REMOTE:
        raise ValueError("未知优化引擎")


def verify_local_version(expected: dict):
    if expected != engine_metadata(LOCAL):
        raise d2p.LocalOptimizationError("本地引擎或密码子表版本已变更。请复制此任务为新任务后运行，避免混用不同版本的结果。")


def run_local(payload: dict, expected: dict) -> dict:
    validate_engine(LOCAL, payload["speciesName"], payload["ignoreCodonQueue"])
    verify_local_version(expected)
    result = d2p.local_optimize(payload["sequence"], payload["ignoreCodonQueue"], max_work=expected["max_work"])
    return result | {"engine_info": expected}


def with_engine_defaults(job: dict) -> dict:
    """Old jobs predate engine selection and always used ProteinFactory HTTP."""
    job.setdefault("engine", REMOTE)
    if "engine_info" not in job:
        job["engine_info"] = engine_metadata(REMOTE) | {"legacy": True}
    return job
