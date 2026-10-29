#!/usr/bin/env python3
"""Experimental local D2P-style encoding. No network requests; not the official algorithm.

python3 -m silicolab.features.codon.local --sequence 'MKTAYIAK*'
python3 -m silicolab.features.codon.local -i examples/proteins.fasta --avoid GAATTC,GGTCTC -o outputs/local.fasta
"""

import argparse
from collections import deque
import json
from pathlib import Path
import sys

from silicolab.features.codon.client import GENETIC_CODE, normalize_avoid, normalize_sequence, read_fasta, validate_result

VERSION = "d2p-local-experimental-1"
MODEL = Path(__file__).resolve().parent / "resources" / "d2p_codon_table.json"


class LocalOptimizationError(ValueError):
    pass


def load_mapping():
    mapping = json.loads(MODEL.read_text())["mapping"]
    for aa in "ACDEFGHIKLMNPQRSTVWY*":
        if GENETIC_CODE.get(mapping.get(aa)) != aa:
            raise LocalOptimizationError(f"Invalid local model mapping: {aa}")
    return mapping


class ForbiddenAutomaton:
    """Aho-Corasick states detect forbidden motifs at every base, in both strands."""

    def __init__(self, motifs):
        self.transitions = [{}]
        self.failure = [0]
        self.forbidden = [False]
        for motif in motifs:
            node = 0
            for base in motif:
                if base not in self.transitions[node]:
                    self.transitions[node][base] = len(self.transitions)
                    self.transitions.append({})
                    self.failure.append(0)
                    self.forbidden.append(False)
                node = self.transitions[node][base]
            self.forbidden[node] = True
        pending = deque()
        for base in "ACGT":
            child = self.transitions[0].get(base)
            if child is None:
                self.transitions[0][base] = 0
            else:
                pending.append(child)
        while pending:
            node = pending.popleft()
            self.forbidden[node] |= self.forbidden[self.failure[node]]
            for base in "ACGT":
                child = self.transitions[node].get(base)
                if child is None:
                    self.transitions[node][base] = self.transitions[self.failure[node]][base]
                else:
                    self.failure[child] = self.transitions[self.failure[node]][base]
                    pending.append(child)

    def step_codon(self, state, codon):
        for base in codon:
            state = self.transitions[state][base]
            if self.forbidden[state]:
                return None
        return state


def local_optimize(sequence: str, avoid: str = "", max_work: int = 5_000_000) -> dict:
    """Minimize (# codons changed from fixed D2P table, # nucleotide edits).

    Exact for this explicit objective when completed. It is NOT claimed to
    reproduce the remote constraint-repair tie-breaking or expression outcomes.
    Budget exhaustion is reported separately from mathematically infeasible input.
    """
    protein = normalize_sequence(sequence)
    normalized_avoid = normalize_avoid(avoid)
    motifs = list(filter(None, normalized_avoid.split(",")))
    if len(motifs) > 128 or any(len(motif) > 256 for motif in motifs) or sum(map(len, motifs)) > 8192:
        raise LocalOptimizationError("本地原型限制：最多 128 个位点，单个位点最长 256 bp，总长最多 8192 bp")
    mapping = load_mapping()
    baseline = "".join(mapping[aa] for aa in protein)
    constraints = sorted(set(motifs + [motif.translate(str.maketrans("ACGT", "TGCA"))[::-1] for motif in motifs]))
    work = 0
    if not constraints or all(motif not in baseline for motif in constraints):
        dna = baseline
    else:
        automaton = ForbiddenAutomaton(constraints)
        candidates = {aa: [mapping[aa]] + sorted(codon for codon, translated in GENETIC_CODE.items()
                                               if translated == aa and codon != mapping[aa]) for aa in set(protein)}
        costs = {0: (0, 0)}
        layers = []
        cache = {}
        for index, aa in enumerate(protein):
            following, parents = {}, {}
            preferred = mapping[aa]
            for state, cost in costs.items():
                for codon in candidates[aa]:
                    work += 1
                    if work > max_work:
                        raise LocalOptimizationError("本地搜索达到工作量上限；未判断无解。请减少位点或提高 max_work")
                    key = state, codon
                    if key not in cache:
                        cache[key] = automaton.step_codon(state, codon)
                    destination = cache[key]
                    if destination is None:
                        continue
                    next_cost = (cost[0] + (codon != preferred), cost[1] + sum(a != b for a, b in zip(codon, preferred)))
                    if destination not in following or next_cost < following[destination]:
                        following[destination] = next_cost
                        parents[destination] = (state, codon)
            if not following:
                raise LocalOptimizationError(f"无同义编码可以满足所选避免位点（处理到第 {index + 1} 位）")
            costs = following
            layers.append(parents)
        state = min(costs, key=costs.get)
        reverse_codons = []
        for parents in reversed(layers):
            state, codon = parents[state]
            reverse_codons.append(codon)
        dna = "".join(reversed(reverse_codons))
    result = {"success": "1", "seq": dna, "engine": VERSION, "species": "D2P-like experimental",
              "network_used": False, "avoid": normalized_avoid, "work": work,
              "changed_codons": sum(dna[i:i + 3] != baseline[i:i + 3] for i in range(0, len(dna), 3))}
    validate_result(result, protein, normalized_avoid)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sequence")
    source.add_argument("-i", "--input", type=Path)
    parser.add_argument("--name", default="local_sequence")
    parser.add_argument("--avoid", default="")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--max-work", type=int, default=5_000_000)
    args = parser.parse_args()
    try:
        if args.max_work <= 0:
            raise ValueError("max-work must be positive")
        if args.output and args.input and args.output.resolve() == args.input.resolve():
            raise ValueError("输入和输出文件不能相同")
        records = read_fasta(args.input) if args.input else [(args.name, normalize_sequence(args.sequence))]
        output = []
        for name, protein in records:
            if not name.strip() or "\n" in name or "\r" in name:
                raise ValueError("序列名称不能为空或包含换行")
            result = local_optimize(protein, args.avoid, args.max_work)
            dna = result["seq"]
            output.append(f">{name}\n" + "\n".join(dna[index:index + 80] for index in range(0, len(dna), 80)) + "\n")
            print(f"{name}: {len(dna)} bp, {result['changed_codons']} codons changed; local experimental engine", file=sys.stderr)
        text = "".join(output)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
        else:
            print(text, end="")
        return 0
    except (ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
