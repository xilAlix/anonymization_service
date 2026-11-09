import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from application.anonymization_workflow import anonymize_manual_direct_identifiers
from infrastructure.attribute_profile_store import save_manual_role_overrides


class AnonymizationWorkflowTests(unittest.TestCase):
    def test_requires_manual_direct_identifier_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "records.csv"
            profile_path = root / "profiles.json"
            csv_path.write_text("customer_id\nC1\n", encoding="utf-8")
            dataframe = pd.DataFrame({"customer_id": ["C1"]})

            with self.assertRaisesRegex(ValueError, "вручную не назначен"):
                anonymize_manual_direct_identifiers(
                    dataframe,
                    csv_path,
                    profile_path,
                )

    def test_uses_only_manually_assigned_direct_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "records.csv"
            profile_path = root / "profiles.json"
            csv_path.write_text("customer_id,age\nC1,25\nC2,30\n", encoding="utf-8")
            save_manual_role_overrides(
                csv_path,
                {"customer_id": ["direct_identifier"], "age": ["quasi_identifier"]},
                profile_path,
            )
            dataframe = pd.DataFrame({"customer_id": ["C1", "C2"], "age": [25, 30]})

            result, selected = anonymize_manual_direct_identifiers(
                dataframe,
                csv_path,
                profile_path,
            )

            self.assertEqual(selected, ["customer_id"])
            self.assertEqual(dataframe["customer_id"].tolist(), ["C1", "C2"])
            self.assertEqual(result["age"].tolist(), [25, 30])
            self.assertTrue(all(value.startswith("ID_") for value in result["customer_id"]))


if __name__ == "__main__":
    unittest.main()
