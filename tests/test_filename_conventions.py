from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fet_analyzer.analysis.classifier import MeasurementType, classify_measurement
from fet_analyzer.analysis.geometry import infer_geometry
from fet_analyzer.analysis.tlm_workflow import _identity
from fet_analyzer.device_parameters import load_master_table, resolve_device_parameters
from fet_analyzer.filename_conventions import parse_filename_conventions


class FilenameConventionTests(unittest.TestCase):
    def test_combined_geometry_block_and_provenance(self):
        facts = parse_filename_conventions("IdVg_S_TLM1_CL25_GL20_CW100.csv")
        self.assertTrue(facts.is_tlm)
        self.assertEqual(facts.tlm_id, "TLM1")
        self.assertEqual(facts.parameters, {
            "channel_length_um": 25.0, "channel_width_um": 100.0,
            "gate_length_um": 20.0,
        })
        self.assertEqual(facts.parameter_sources["channel_length_um"], "filename:CL")

    def test_geometry_variants_are_case_insensitive(self):
        for name in ("x_cl25.5_gl20_cw100.csv", "x_CL_25_GL_20_CW_100.csv",
                     "x_CL25um_GL20µm_CW100μm.csv"):
            with self.subTest(name=name):
                facts = parse_filename_conventions(name)
                self.assertEqual(facts.parameters["channel_length_um"], 25.5 if "25.5" in name else 25.0)
                self.assertEqual(facts.parameters["gate_length_um"], 20.0)
                self.assertEqual(facts.parameters["channel_width_um"], 100.0)

    def test_individual_aliases_and_other_parameters(self):
        facts = parse_filename_conventions("x_Lch10_Wch50_Lg8_tox90nm_tfilm20nm.csv")
        self.assertEqual(facts.parameters, {
            "channel_length_um": 10.0, "channel_width_um": 50.0,
            "gate_length_um": 8.0, "oxide_thickness_nm": 90.0,
            "film_thickness_nm": 20.0,
        })

    def test_short_aliases_require_boundaries(self):
        facts = parse_filename_conventions("Flow25_Window50_CL10.csv")
        self.assertEqual(facts.parameters, {"channel_length_um": 10.0})

    def test_tlm_is_detected_anywhere_and_ltlm_is_ungated(self):
        for name in ("TLM_device.csv", "device_tlm.csv", "device_tLm_extra.csv"):
            self.assertTrue(parse_filename_conventions(name).is_tlm)
        facts = parse_filename_conventions("LTLM_S_TLM02_10um.csv")
        self.assertTrue(facts.is_ltlm)
        self.assertEqual(facts.tlm_id, "TLM02")

    def test_geometry_block_does_not_imply_tlm(self):
        facts = parse_filename_conventions("IdVg_S_CL10_GL8_CW50.csv")
        self.assertFalse(facts.is_tlm)
        self.assertEqual(facts.parameters["channel_length_um"], 10.0)

    def test_single_unlabelled_tlm_length_anywhere(self):
        for name in ("IdVg_S_TLM1_25um.csv", "S_25um_TLM1_IdVg.csv", "s_tlm_25µm.csv"):
            with self.subTest(name=name):
                facts = parse_filename_conventions(name)
                self.assertEqual(facts.parameters["channel_length_um"], 25.0)
                self.assertEqual(facts.parameter_sources["channel_length_um"], "filename:unlabelled_tlm_length")

    def test_unlabelled_length_is_not_used_for_non_tlm(self):
        self.assertNotIn("channel_length_um", parse_filename_conventions("IdVg_S_25um.csv").parameters)

    def test_repeated_equal_unlabelled_value_deduplicates(self):
        facts = parse_filename_conventions("TLM_S_25um_repeat_25um.csv")
        self.assertEqual(facts.parameters["channel_length_um"], 25.0)
        self.assertFalse(facts.errors)

    def test_different_unlabelled_values_are_ambiguous(self):
        facts = parse_filename_conventions("TLM_S_25um_50um.csv")
        self.assertNotIn("channel_length_um", facts.parameters)
        self.assertEqual(facts.errors[0]["code"], "ambiguous_tlm_channel_length")

    def test_tagged_geometry_is_excluded_from_unlabelled_candidates(self):
        facts = parse_filename_conventions("TLM_S_CL25um_GL20um_CW100um.csv")
        self.assertEqual(facts.parameters["channel_length_um"], 25.0)
        self.assertFalse(facts.errors)

    def test_conflicting_explicit_values_are_reported(self):
        facts = parse_filename_conventions("TLM_S_CL25_Lch50.csv")
        self.assertNotIn("channel_length_um", facts.parameters)
        self.assertEqual(facts.errors[0]["code"], "conflicting_filename_parameter")

    def test_invalid_values_are_reported(self):
        for name in ("TLM_CL0.csv", "TLM_CL_-2.csv", "TLM_CLnan.csv", "TLM_CL.csv"):
            with self.subTest(name=name):
                self.assertTrue(parse_filename_conventions(name).errors)

    def test_configured_lch_regex_precedes_builtin(self):
        facts = parse_filename_conventions("TLM_S_CL25_SPECIAL50.csv", configured_lch_regex=r"SPECIAL(\d+)")
        self.assertEqual(facts.parameters["channel_length_um"], 50.0)
        self.assertEqual(facts.parameter_sources["channel_length_um"], "filename:tlm.lch_regex")

    def test_invalid_configured_regex_is_visible(self):
        facts = parse_filename_conventions("TLM_25um.csv", configured_lch_regex="(")
        self.assertEqual(facts.warnings[0]["code"], "invalid_lch_regex")

    def test_unconfirmed_table_does_not_erase_filename_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            table = Path(folder) / "device_parameters.txt"
            table.write_text(
                "sample_label\tdevice_pattern\tchannel_length_um\tparameter_set_name\n"
                "*\t*\t999\tTEMPLATE_UNCONFIRMED\n", encoding="utf-8")
            rows = load_master_table(table)
            values, sources = infer_geometry(Path("TLM_CL25_GL20_CW100.csv"), {})
            resolved, resolved_sources, _ = resolve_device_parameters(
                {}, rows, "unknown", "TLM_CL25_GL20_CW100.csv", values, sources)
        self.assertEqual(resolved["channel_length_um"], 25.0)
        self.assertEqual(resolved_sources["channel_length_um"], "filename:CL")

    def test_confirmed_table_overrides_filename_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            table = Path(folder) / "device_parameters.txt"
            table.write_text(
                "sample_label\tdevice_pattern\tchannel_length_um\nS\t*\t42\n", encoding="utf-8")
            facts = parse_filename_conventions("TLM_S_CL25_Lch50.csv")
            values, sources, _ = resolve_device_parameters(
                {}, load_master_table(table), "S", "TLM_S_CL25_Lch50.csv",
                facts.parameters, facts.parameter_sources)
        self.assertEqual(values["channel_length_um"], 42.0)
        self.assertTrue(sources["channel_length_um"].startswith("device_parameters.txt:"))

    def test_classifier_and_tlm_identity_use_shared_facts(self):
        filename = "IdVg__S_TLM7_CL25_GL20_CW100.csv"
        classification = classify_measurement(
            {}, ["Vg", "Vd", "Id"],
            {"Vg": [-1, 0, 1], "Vd": [.1, .1, .1], "Id": [1e-9, 1e-8, 1e-7]},
            filename=filename,
        )
        values, sources = infer_geometry(Path(filename), {})
        identity = _identity({"source_file": Path(filename), "classification": classification,
                              "device_params": values, "parameter_sources": sources})
        self.assertEqual(classification["type"], MeasurementType.TRANSFER)
        self.assertTrue(classification["is_tlm"])
        self.assertEqual(identity, ("S", "TLM7", 25.0))


if __name__ == "__main__":
    unittest.main()
