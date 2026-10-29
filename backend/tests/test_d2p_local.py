import itertools
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

from silicolab.features.codon import client as codon

from silicolab.features.codon import local

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'd2p_regression.json'


def reverse_complement(motif):
    return motif.translate(str.maketrans('ACGT', 'TGCA'))[::-1]


def brute_force_cost(protein, avoid):
    mapping = local.load_mapping()
    baseline = ''.join(mapping[aa] for aa in protein)
    motifs = list(filter(None, avoid.split(',')))
    patterns = motifs + [reverse_complement(motif) for motif in motifs]
    candidates = [[codon_value for codon_value, residue in codon.GENETIC_CODE.items() if residue == aa]
                  for aa in protein]
    valid_costs = []
    for codons in itertools.product(*candidates):
        dna = ''.join(codons)
        if any(pattern in dna for pattern in patterns):
            continue
        valid_costs.append((sum(candidate != mapping[aa] for candidate, aa in zip(codons, protein)),
                            sum(left != right for left, right in zip(baseline, dna))))
    return min(valid_costs) if valid_costs else None


class LocalD2PTests(unittest.TestCase):
    def test_model_is_complete_and_uses_valid_synonyms(self):
        mapping = local.load_mapping()
        self.assertEqual(len(mapping), 21)
        for aa, value in mapping.items():
            self.assertEqual(codon.GENETIC_CODE[value], aa)
        self.assertEqual(mapping['*'], 'TAA')
        self.assertEqual(mapping['K'], 'AAG')

    @patch('silicolab.features.codon.client.request_json', side_effect=AssertionError('Network forbidden'))
    def test_local_result_never_calls_remote_and_preserves_terminal_stop(self, network):
        result = local.local_optimize(' m k * ')
        self.assertEqual(result['seq'], 'ATGAAGTAA')
        self.assertFalse(result['network_used'])
        self.assertEqual(result['changed_codons'], 0)
        self.assertEqual(local.local_optimize('MK')['seq'], 'ATGAAG')
        network.assert_not_called()

    def test_cached_unconstrained_holdouts_reproduce_remote_exactly(self):
        rows = json.loads(FIXTURES.read_text())['unconstrained']
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(local.local_optimize(row['protein'])['seq'], row['expected_dna'])

    def test_cached_constraint_holdouts_all_meet_biological_and_motif_checks(self):
        rows = json.loads(FIXTURES.read_text())['constrained']
        self.assertEqual(len(rows), 8)
        for row in rows:
            result = local.local_optimize(row['protein'], row['avoid'])
            codon.validate_result(result, row['protein'], row['avoid'])

    def test_forward_reverse_complement_overlapping_and_stop_constraints(self):
        cases = [('MEF', 'GAATTC'), ('KKKKK', 'AAGAAG'), ('MKK*', 'TAA'),
                 ('MLK', reverse_complement('TTGAAG')), ('MK', 'AAG'), ('MKKK', 'AAGAAG,AAAG')]
        for protein, avoid in cases:
            with self.subTest(protein=protein, avoid=avoid):
                result = local.local_optimize(protein, avoid)
                codon.validate_result(result, protein, avoid)

    def test_minimum_edit_objective_matches_exhaustive_enumeration(self):
        mapping = local.load_mapping()
        cases = [('KKK', 'AAGAAG'), ('MEF', 'GAATTC'), ('MKK*', 'AAG'),
                 ('MKK*', 'TAA'), ('MLK', 'TTGAAG'), ('KS', 'AAGTCT'), ('AK', 'AG')]
        for protein, avoid in cases:
            optimum = brute_force_cost(protein, avoid)
            with self.subTest(protein=protein, avoid=avoid):
                if optimum is None:
                    with self.assertRaises(local.LocalOptimizationError):
                        local.local_optimize(protein, avoid)
                else:
                    result = local.local_optimize(protein, avoid)
                    baseline = ''.join(mapping[aa] for aa in protein)
                    cost = (result['changed_codons'], sum(a != b for a, b in zip(result['seq'], baseline)))
                    self.assertEqual(cost, optimum)

    def test_infeasible_constraints_fail_without_returning_invalid_dna(self):
        for protein, avoid in [('MMMM', 'ATG'), ('KK', 'AAA,AAG'), ('M*', 'TAA,TAG,TGA')]:
            with self.subTest(protein=protein, avoid=avoid), self.assertRaisesRegex(local.LocalOptimizationError, '无同义编码'):
                local.local_optimize(protein, avoid)

    def test_budget_exhaustion_is_distinct_from_infeasible_constraint(self):
        with self.assertRaisesRegex(local.LocalOptimizationError, '未判断无解'):
            local.local_optimize('KKKKK', 'AAG', max_work=1)

    def test_automaton_agrees_with_direct_substring_detection(self):
        generator = random.Random(1741)
        patterns = ['AGA', 'GAGA', 'TAA', 'CTT', 'AAGAAG']
        machine = local.ForbiddenAutomaton(patterns)
        for _ in range(200):
            dna = ''.join(generator.choice('ACGT') for _ in range(30))
            state = 0
            accepted = True
            for index in range(0, len(dna), 3):
                state = machine.step_codon(state, dna[index:index + 3])
                if state is None:
                    accepted = False
                    break
            self.assertEqual(accepted, not any(pattern in dna for pattern in patterns))

    def test_invalid_protein_and_ambiguous_motifs_are_rejected(self):
        for sequence in ['MX', 'M*K', '', '*']:
            with self.assertRaises(ValueError):
                local.local_optimize(sequence)
        with self.assertRaises(ValueError):
            local.local_optimize('MK', 'EcoRI')

    def test_inactive_constraints_leave_baseline_unchanged(self):
        protein = 'MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ'
        result = local.local_optimize(protein, 'GCGCGCGC')
        self.assertEqual(result['seq'], local.local_optimize(protein)['seq'])
        self.assertEqual(result['work'], 0)


if __name__ == '__main__':
    unittest.main()
