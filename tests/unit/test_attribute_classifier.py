import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from data_processing.attribute_classifier import classify_attributes
from infrastructure.attribute_profile_store import (
    load_manual_role_overrides,
    save_manual_role_overrides,
)


class AttributeClassifierTests(unittest.TestCase):
    def test_suggests_roles_from_column_names(self):
        dataframe = pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3"],
                "age": [24, 31, 45],
                "district": ["North", "South", "East"],
                "monthly_income": [50000, 65000, 72000],
                "purchase_amount": [1200, 800, 2400],
            }
        )

        results = {result.attribute: result for result in classify_attributes(dataframe)}

        self.assertEqual(results["customer_id"].assigned_roles, ("direct_identifier",))
        self.assertEqual(results["age"].assigned_roles, ("quasi_identifier",))
        self.assertEqual(results["district"].assigned_roles, ("quasi_identifier",))
        self.assertEqual(results["monthly_income"].assigned_roles, ("sensitive_attribute",))
        self.assertEqual(results["purchase_amount"].assigned_roles, ())

    def test_email_values_can_suggest_direct_identifier(self):
        dataframe = pd.DataFrame(
            {"contact": ["a@example.com", "b@example.com", "c@example.com", "d@example.com"]}
        )
        result = classify_attributes(dataframe)[0]
        self.assertEqual(result.assigned_roles, ("direct_identifier",))
        self.assertEqual(result.suggestions[0].confidence, "высокая")

    def test_product_id_is_not_assumed_to_identify_a_person(self):
        dataframe = pd.DataFrame({"product_id": ["P-1", "P-2", "P-3"]})
        result = classify_attributes(dataframe)[0]
        self.assertEqual(result.assigned_roles, ())

    def test_manual_roles_override_suggestions_and_can_be_multiple(self):
        dataframe = pd.DataFrame({"age": [20, 30, 40]})
        results = classify_attributes(
            dataframe,
            {"age": ["quasi_identifier", "analytical_attribute"]},
        )

        self.assertEqual(
            results[0].assigned_roles,
            ("quasi_identifier", "analytical_attribute"),
        )
        self.assertEqual(results[0].assignment_source, "Вручную")

    def test_empty_manual_assignment_suppresses_automatic_suggestion(self):
        dataframe = pd.DataFrame({"age": [20, 30, 40]})
        result = classify_attributes(dataframe, {"age": []})[0]
        self.assertEqual(result.assigned_roles, ())
        self.assertEqual(result.assignment_source, "Вручную")
        self.assertTrue(result.suggestions)

    def test_manual_roles_are_persisted_per_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "records.csv"
            profile_path = root / "profiles.json"
            csv_path.write_text("age\n20\n30\n", encoding="utf-8")

            expected = {
                "age": ["quasi_identifier", "analytical_attribute"],
                "region": [],
            }
            save_manual_role_overrides(csv_path, expected, profile_path)
            self.assertEqual(
                load_manual_role_overrides(csv_path, profile_path),
                expected,
            )

            csv_path.write_text("age\n21\n31\n", encoding="utf-8")
            self.assertEqual(
                load_manual_role_overrides(csv_path, profile_path),
                expected,
            )

            another_path = root / "renamed.csv"
            another_path.write_bytes(csv_path.read_bytes())
            self.assertEqual(load_manual_role_overrides(another_path, profile_path), {})

    def test_clearing_all_manual_roles_removes_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "records.csv"
            profile_path = root / "profiles.json"
            csv_path.write_text("age\n20\n", encoding="utf-8")

            save_manual_role_overrides(csv_path, {"age": []}, profile_path)
            self.assertEqual(load_manual_role_overrides(csv_path, profile_path), {"age": []})
            save_manual_role_overrides(csv_path, {}, profile_path)
            self.assertEqual(load_manual_role_overrides(csv_path, profile_path), {})


if __name__ == "__main__":
    unittest.main()
