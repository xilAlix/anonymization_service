import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from anonymization.algorithms.tokenization import tokenize_values
from anonymization.tokenization_adapter import tokenize_identifier_columns


class TokenizationTests(unittest.TestCase):
    def test_algorithm_preserves_repeated_values_and_missing_values(self):
        tokens = iter(["T1", "T2"])
        result = tokenize_values(
            ["A", "B", "A", None],
            lambda: next(tokens),
        )
        self.assertEqual(result, ["T1", "T2", "T1", None])

    def test_algorithm_returns_new_list_and_rejects_duplicate_tokens(self):
        source = ["A", "B"]
        with self.assertRaises(ValueError):
            tokenize_values(source, lambda: "same")
        self.assertEqual(source, ["A", "B"])

    def test_adapter_only_changes_selected_columns(self):
        dataframe = pd.DataFrame(
            {
                "customer_id": ["C1", "C2", "C1"],
                "district": ["North", "South", "North"],
            }
        )
        result = tokenize_identifier_columns(dataframe, ["customer_id"])

        self.assertEqual(dataframe["customer_id"].tolist(), ["C1", "C2", "C1"])
        self.assertEqual(result["customer_id"].iloc[0], result["customer_id"].iloc[2])
        self.assertNotEqual(result["customer_id"].iloc[0], "C1")
        self.assertEqual(result["district"].tolist(), dataframe["district"].tolist())

    def test_adapter_rejects_missing_or_empty_column_selection(self):
        dataframe = pd.DataFrame({"id": ["A"]})
        with self.assertRaises(ValueError):
            tokenize_identifier_columns(dataframe, [])
        with self.assertRaises(ValueError):
            tokenize_identifier_columns(dataframe, ["unknown"])


if __name__ == "__main__":
    unittest.main()
