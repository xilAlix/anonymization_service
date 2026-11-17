import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from infrastructure.settings_manager import (
    AnonymizationSettings,
    AppSettings,
    DataTypeAnalysisSettings,
    KAnonymizationSettings,
    load_settings,
    save_settings,
)


class SettingsManagerTests(unittest.TestCase):
    def test_settings_are_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(DataTypeAnalysisSettings(True, 12.5))
            save_settings(expected, path)
            self.assertEqual(load_settings(path), expected)

    def test_user_settings_are_not_reset_between_application_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(
                anonymization=AnonymizationSettings(
                    tokenize_direct_identifiers=True,
                    remove_direct_identifiers=False,
                    enable_k_anonymity=False,
                ),
                k_anonymization=KAnonymizationSettings(
                    enable_l_diversity=False,
                    default_k=7,
                    default_l=3,
                    l_diversity_variant="entropy",
                ),
            )
            save_settings(expected, path)

            first_start = load_settings(path)
            second_start = load_settings(path)

            self.assertEqual(first_start, expected)
            self.assertEqual(second_start, expected)
            self.assertEqual(load_settings(path), expected)

    def test_missing_settings_file_uses_safe_full_anonymization_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(Path(directory) / "missing.json")
            self.assertFalse(settings.anonymization.tokenize_direct_identifiers)
            self.assertTrue(settings.anonymization.remove_direct_identifiers)
            self.assertTrue(settings.anonymization.enable_k_anonymity)
            self.assertTrue(settings.k_anonymization.enable_l_diversity)
            self.assertEqual(settings.k_anonymization.default_k, 5)
            self.assertEqual(settings.k_anonymization.default_l, 2)
            self.assertEqual(settings.k_anonymization.l_diversity_variant, "both")

    def test_invalid_threshold_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"data_type_analysis": {
                    "detect_nominal_attributes": True,
                    "nominal_unique_threshold_percent": 150,
                }}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_settings(path)

    def test_legacy_settings_use_safe_full_anonymization_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"data_type_analysis": {}}),
                encoding="utf-8",
            )

            settings = load_settings(path)

            self.assertFalse(settings.anonymization.tokenize_direct_identifiers)
            self.assertTrue(settings.anonymization.remove_direct_identifiers)
            self.assertTrue(settings.anonymization.enable_k_anonymity)
            self.assertTrue(settings.k_anonymization.enable_l_diversity)

    def test_anonymization_operation_setting_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(
                data_type_analysis=DataTypeAnalysisSettings(True, 12.5),
                anonymization=AnonymizationSettings(False, True),
            )

            save_settings(expected, path)

            self.assertEqual(load_settings(path), expected)

    def test_invalid_anonymization_setting_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"anonymization": {"tokenize_direct_identifiers": "yes"}}),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_settings(path)

    def test_tokenization_and_removal_cannot_both_be_selected_for_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings(
                anonymization=AnonymizationSettings(True, True),
            )

            with self.assertRaisesRegex(ValueError, "альтернативными"):
                save_settings(settings, path)

            path.write_text(
                json.dumps({
                    "anonymization": {
                        "tokenize_direct_identifiers": True,
                        "remove_direct_identifiers": True,
                    }
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "альтернативными"):
                load_settings(path)

    def test_zero_anonymization_operations_are_allowed_in_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings(
                anonymization=AnonymizationSettings(False, False),
            )
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)


    def test_l_diversity_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(
                k_anonymization=KAnonymizationSettings(
                    default_k=7,
                    max_row_suppression_percent=3.0,
                    numeric_representative="median",
                    enable_l_diversity=True,
                    default_l=3,
                    l_diversity_variant="entropy",
                )
            )
            save_settings(expected, path)
            self.assertEqual(load_settings(path), expected)

    def test_legacy_settings_default_l_diversity_to_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"k_anonymization": {"default_k": 4}}', encoding="utf-8")
            settings = load_settings(path)
            self.assertTrue(settings.k_anonymization.enable_l_diversity)
            self.assertEqual(settings.k_anonymization.default_l, 2)
            self.assertEqual(settings.k_anonymization.l_diversity_variant, "both")

    def test_invalid_l_diversity_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                '{"k_anonymization": {"enable_l_diversity": true, "default_l": 1}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "l по умолчанию"):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
