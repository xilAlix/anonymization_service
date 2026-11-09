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

    def test_legacy_settings_keep_existing_anonymization_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"data_type_analysis": {}}),
                encoding="utf-8",
            )

            settings = load_settings(path)

            self.assertTrue(settings.anonymization.tokenize_direct_identifiers)

    def test_anonymization_operation_setting_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = AppSettings(
                data_type_analysis=DataTypeAnalysisSettings(True, 12.5),
                anonymization=AnonymizationSettings(False),
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


if __name__ == "__main__":
    unittest.main()
