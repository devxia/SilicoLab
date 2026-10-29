#!/usr/bin/env python3
"""Call the ProteinFactory codon optimizer without a browser (Python 3.10+)."""

import argparse
import itertools
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://www.ourproteinfactory.com"
DEFAULT_SPECIES = "D2P(default)"
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
GENETIC_CODE = dict(zip(
    ("".join(codon) for codon in itertools.product("TCAG", repeat=3)),
    "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
))


class OptimizationError(Exception):
    """A failed request or a response that fails biological validation."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


def normalize_sequence(sequence: str) -> str:
    sequence = re.sub(r"\s+", "", sequence).upper()
    if not sequence:
        raise ValueError("氨基酸序列不能为空")
    invalid = set(sequence) - AMINO_ACIDS - {"*"}
    if invalid:
        raise ValueError(f"不支持的氨基酸字符：{', '.join(sorted(invalid))}")
    if "*" in sequence[:-1] or sequence == "*":
        raise ValueError("只允许在完整氨基酸序列的末尾添加一个终止符 *")
    if len(sequence) > 10000:
        raise ValueError("序列超过网页标示的 10,000 字符限制，请先确认服务端支持范围")
    return sequence


def normalize_avoid(avoid: str) -> str:
    motifs = []
    for motif in re.sub(r"\s+", "", avoid).upper().split(","):
        expanded = ["GGTAACC", "GGTTACC"] if motif == "GGT(A/T)ACC" else [motif]
        for item in expanded:
            if not item:
                continue
            if re.fullmatch(r"[ACGT]+", item) is None:
                raise ValueError(f"避免位点必须为 A/C/G/T 序列，以英文逗号分隔：{item}")
            if item not in motifs:
                motifs.append(item)
    return ",".join(motifs)


def request_json(path: str, payload=None, timeout: float = 120):
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(BASE_URL + path, data=body, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raise OptimizationError(f"接口返回 HTTP {exc.code}：{path}") from exc
    except (URLError, OSError) as exc:
        raise OptimizationError(f"请求失败：{exc}；请确认网络后再重试") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise OptimizationError("接口未返回有效 JSON，网站的接口或登录要求可能已改变") from exc


def list_species(timeout: float = 120) -> list[str]:
    data = request_json("/getSpeciesName", timeout=timeout)
    if not isinstance(data, list) or not all(
        isinstance(item, dict) and isinstance(item.get("speciesName"), str)
        for item in data
    ):
        raise OptimizationError("物种列表格式发生变化", response=data)
    return list(dict.fromkeys(item["speciesName"] for item in data))


def validate_result(data, protein: str, avoid: str = "") -> str:
    if not isinstance(data, dict):
        raise OptimizationError("优化接口返回的 JSON 不是对象", response=data)
    if str(data.get("success")) != "1":
        raise OptimizationError(f"优化未成功：{data.get('msg', '缺少 success 字段')}", response=data)
    dna = data.get("seq")
    if not isinstance(dna, str) or re.fullmatch(r"[ACGT]+", dna.upper()) is None:
        raise OptimizationError("返回的 seq 不是有效 DNA 序列", response=data)
    dna = dna.upper()
    if len(dna) != 3 * len(protein):
        raise OptimizationError("返回 DNA 的长度与输入氨基酸序列不符", response=data)
    translated = "".join(GENETIC_CODE[dna[i:i + 3]] for i in range(0, len(dna), 3))
    if translated != protein:
        raise OptimizationError("返回 DNA 翻译后与输入氨基酸序列不一致", response=data)
    for motif in filter(None, avoid.split(",")):
        reverse_complement = motif.translate(str.maketrans("ACGT", "TGCA"))[::-1]
        if motif in dna or reverse_complement in dna:
            raise OptimizationError(f"返回 DNA 仍含避免位点 {motif} 或其反向互补序列", response=data)
    return dna


def optimize(sequence: str, name: str = "sequence", species: str = DEFAULT_SPECIES,
             avoid: str = "", timeout: float = 120) -> dict:
    """Return the API response after checking success, translation and motifs.

    The input must be a protein sequence, optionally ending in '*'. No stop
    codon is added by this client. Avoided motifs are checked on both strands.
    """
    protein = normalize_sequence(sequence)
    avoid = normalize_avoid(avoid)
    if not name.strip() or not species.strip():
        raise ValueError("序列名称和目标物种不能为空")
    payload = {
        "fileName": name,
        "jumpName": "pep",
        "sequence": protein,
        "ignoreCodonQueue": avoid,
        "speciesName": species,
    }
    data = request_json("/toDnaAjaxCodon", payload, timeout=timeout)
    validate_result(data, protein, avoid)
    return data


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records = []
    name = None
    parts = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, normalize_sequence("".join(parts))))
            name, parts = line[1:].strip(), []
            if not name:
                raise ValueError(f"FASTA 第 {line_number} 行的序列名称为空")
        elif name is None:
            raise ValueError(f"FASTA 第 {line_number} 行之前缺少 >名称")
        else:
            parts.append(line)
    if name is not None:
        records.append((name, normalize_sequence("".join(parts))))
    if not records:
        raise ValueError("FASTA 文件没有序列")
    return records


def positive_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必须为大于 0 的有限数字")
    return number


def nonnegative_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("必须为大于等于 0 的有限数字")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sequence", help="单条氨基酸序列")
    source.add_argument("-i", "--input", type=Path, help="含一条或多条蛋白序列的 FASTA 文件")
    source.add_argument("--list-species", action="store_true", help="获取服务端物种名称列表")
    parser.add_argument("--name", default="sequence", help="单条序列名称")
    parser.add_argument("--species", default=DEFAULT_SPECIES, help="服务端物种名称，默认 D2P(default)")
    parser.add_argument("--avoid", default="", help="避免的 DNA 位点，以英文逗号分隔")
    parser.add_argument("-o", "--output", type=Path, help="输出 DNA FASTA；默认写入标准输出")
    parser.add_argument("--raw-dir", type=Path, help="每条序列保存请求参数和原始 JSON 响应")
    parser.add_argument("--timeout", type=positive_number, default=120, help="单次请求超时秒数，默认 120")
    parser.add_argument("--delay", type=nonnegative_number, default=0.5, help="批量请求间隔秒数，默认 0.5")
    args = parser.parse_args(argv)

    stream = None
    try:
        if args.list_species:
            print("\n".join(list_species(timeout=args.timeout)))
            return 0
        records = read_fasta(args.input) if args.input else [(args.name, normalize_sequence(args.sequence))]
        if any(not name.strip() or "\n" in name or "\r" in name for name, _ in records):
            raise ValueError("序列名称不能为空或包含换行符")
        if not args.species.strip():
            raise ValueError("目标物种不能为空")
        avoid = normalize_avoid(args.avoid)
        if args.output and args.input and args.output.resolve() == args.input.resolve():
            raise ValueError("输入和输出文件必须不同")
        if args.raw_dir:
            args.raw_dir.mkdir(parents=True, exist_ok=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            stream = args.output.open("w", encoding="utf-8")
        else:
            stream = sys.stdout
        for index, (name, protein) in enumerate(records, 1):
            if index > 1:
                time.sleep(args.delay)
            print(f"[{index}/{len(records)}] {name}：{len(protein.rstrip('*'))} aa，{args.species}", file=sys.stderr)
            result = None
            try:
                result = optimize(protein, name, args.species, avoid, args.timeout)
            except OptimizationError as exc:
                result = exc.response
                raise
            finally:
                if args.raw_dir and result is not None:
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")[:80] or "sequence"
                    artifact = {
                        "request": {"fileName": name, "jumpName": "pep", "sequence": protein,
                                    "ignoreCodonQueue": avoid, "speciesName": args.species},
                        "response": result,
                    }
                    (args.raw_dir / f"{index:04d}_{safe_name}.json").write_text(
                        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            dna = result["seq"].upper()
            stream.write(f">{name}\n")
            stream.write("\n".join(dna[i:i + 80] for i in range(0, len(dna), 80)) + "\n")
            stream.flush()
            print(f"  已验证 {len(dna)} bp；log_id={result.get('log_id', '')}", file=sys.stderr)
        return 0
    except (OptimizationError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        if stream is not None and stream is not sys.stdout:
            stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
