import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from silicolab.features.codon import client as client


def success(dna="ATGAAG", **updates):
    result = {"success": "1", "msg": "Optimization succeeded", "seq": dna, "log_id": "test-id"}
    result.update(updates)
    return result


class SequenceTests(unittest.TestCase):
    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(client.normalize_sequence(" m k\nT* "), "MKT*")

    def test_rejects_invalid_empty_and_internal_stops(self):
        for sequence in ("", "  ", "M*KT", "M**", "*", "MX", "MA-", "M1", "M" * 10001):
            with self.subTest(sequence=sequence[:20]), self.assertRaises(ValueError):
                client.normalize_sequence(sequence)

    def test_avoid_expands_special_motif_and_deduplicates(self):
        self.assertEqual(client.normalize_avoid(" gaa ttc,GGT(A/T)ACC,GAATTC,,"),
                         "GAATTC,GGTAACC,GGTTACC")

    def test_rejects_ambiguous_or_named_motifs(self):
        for motif in ("EcoRI", "GCN", "GAATTC;GGTCTC"):
            with self.subTest(motif=motif), self.assertRaises(ValueError):
                client.normalize_avoid(motif)

    def test_genetic_code_is_complete_and_standard(self):
        self.assertEqual(len(client.GENETIC_CODE), 64)
        self.assertEqual(client.GENETIC_CODE["ATG"], "M")
        self.assertEqual(client.GENETIC_CODE["TGG"], "W")
        for stop in ("TAA", "TAG", "TGA"):
            self.assertEqual(client.GENETIC_CODE[stop], "*")


class ResultTests(unittest.TestCase):
    def test_success_with_string_or_integer_flag_and_terminal_stop(self):
        for flag in (1, "1"):
            self.assertEqual(client.validate_result(success("atgaagtaa", success=flag), "MK*"),
                             "ATGAAGTAA")

    def test_rejects_service_failure_and_attaches_original_response(self):
        response = {"success": "0", "msg": "warning"}
        with self.assertRaises(client.OptimizationError) as error:
            client.validate_result(response, "MK")
        self.assertIs(error.exception.response, response)

    def test_rejects_nonobject_missing_fields_bad_dna_length_and_translation(self):
        responses = ([], {}, success(None), success("ATGNAA"), success("ATGA"), success("ATGTAA"))
        for response in responses:
            with self.subTest(response=response), self.assertRaises(client.OptimizationError):
                client.validate_result(response, "MK")

    def test_rejects_forward_avoid_motif(self):
        with self.assertRaisesRegex(client.OptimizationError, "GAATTC"):
            client.validate_result(success("ATGGAATTC"), "MEF", "GAATTC")

    def test_rejects_reverse_complement_avoid_motif(self):
        # GAGACC is the reverse complement of the non-palindromic BsaI site GGTCTC.
        with self.assertRaisesRegex(client.OptimizationError, "GGTCTC"):
            client.validate_result(success("ATGGAGACC"), "MET", "GGTCTC")

    def test_success_without_forbidden_motif(self):
        self.assertEqual(client.validate_result(success(), "MK", "GAATTC"), "ATGAAG")


class TransportTests(unittest.TestCase):
    @patch.object(client, "urlopen")
    def test_posts_json_to_fixed_https_endpoint_without_auth(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(success()).encode()
        self.assertEqual(client.optimize(" m k ", name="test")["seq"], "ATGAAG")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, client.BASE_URL + "/toDnaAjaxCodon")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertIsNone(request.get_header("Cookie"))
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(json.loads(request.data), {
            "fileName": "test", "jumpName": "pep", "sequence": "MK",
            "ignoreCodonQueue": "", "speciesName": "D2P(default)",
        })

    @patch.object(client, "urlopen")
    def test_non_json_response_is_explained(self, urlopen):
        for raw in (b"<html>login</html>", bytes([255])):
            urlopen.return_value.__enter__.return_value.read.return_value = raw
            with self.subTest(raw=raw), self.assertRaisesRegex(client.OptimizationError, "JSON"):
                client.request_json("/getSpeciesName")

    @patch.object(client, "urlopen")
    def test_transport_errors_are_not_silently_retried(self, urlopen):
        for error in (URLError("offline"), TimeoutError("timeout"),
                      HTTPError(client.BASE_URL, 429, "rate limited", {}, None)):
            with self.subTest(error=error):
                urlopen.reset_mock()
                urlopen.side_effect = error
                with self.assertRaises(client.OptimizationError):
                    client.request_json("/getSpeciesName")
                self.assertEqual(urlopen.call_count, 1)

    @patch.object(client, "request_json")
    def test_species_list_deduplicates_and_validates_schema(self, request):
        request.return_value = [{"speciesName": "E_coli"}, {"speciesName": "E_coli"}]
        self.assertEqual(client.list_species(), ["E_coli"])
        for data in ({}, ["E_coli"], [{"speciesName": None}]):
            request.return_value = data
            with self.assertRaises(client.OptimizationError):
                client.list_species()


class FastaAndCliTests(unittest.TestCase):
    def test_reads_multiline_fasta_and_normalizes_sequences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.fasta"
            path.write_text("\ufeff>first protein\nmk\nT*\n\n>second\nMA\n", encoding="utf-8")
            self.assertEqual(client.read_fasta(path), [("first protein", "MKT*"), ("second", "MA")])

    def test_rejects_malformed_or_empty_fasta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.fasta"
            for content in ("", "MK", ">\nMK", ">empty\n>next\nMK", ">empty"):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    client.read_fasta(path)

    @patch.object(client, "optimize", return_value=success())
    @patch.object(client.time, "sleep")
    def test_batch_writes_dna_and_traceable_raw_responses(self, sleep, optimize):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, raw = root / "input.fa", root / "output.fa", root / "raw"
            source.write_text(">first\nMK\n>../second protein\nMK\n")
            with patch("sys.stderr", new_callable=io.StringIO):
                code = client.main(["-i", str(source), "-o", str(output), "--raw-dir", str(raw)])
            self.assertEqual(code, 0)
            self.assertEqual(optimize.call_count, 2)
            sleep.assert_called_once_with(0.5)
            self.assertEqual(output.read_text(), ">first\nATGAAG\n>../second protein\nATGAAG\n")
            artifacts = sorted(raw.glob("*.json"))
            self.assertEqual(len(artifacts), 2)
            self.assertEqual(json.loads(artifacts[0].read_text())["response"]["seq"], "ATGAAG")
            self.assertEqual(json.loads(artifacts[0].read_text())["request"]["sequence"], "MK")

    @patch.object(client, "optimize", side_effect=client.OptimizationError("failed", {"success": "0"}))
    def test_failed_response_is_saved_but_not_written_as_fasta(self, optimize):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            with patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                    patch("sys.stderr", new_callable=io.StringIO):
                code = client.main(["--sequence", "MK", "--raw-dir", str(raw)])
            self.assertEqual(code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(json.loads(next(raw.glob("*.json")).read_text())["response"], {"success": "0"})

    @patch.object(client, "optimize")
    def test_input_and_output_cannot_be_the_same_file(self, optimize):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.fa"
            path.write_text(">protein\nMK\n")
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(client.main(["-i", str(path), "-o", str(path)]), 1)
            self.assertEqual(path.read_text(), ">protein\nMK\n")
            optimize.assert_not_called()

    @patch.object(client, "optimize")
    def test_invalid_input_is_rejected_before_any_request(self, optimize):
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(client.main(["--sequence", "MX"]), 1)
        optimize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
