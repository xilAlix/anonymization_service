import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from data_processing.schema_inspector import analyze_column_types


class SchemaInspectorTests(unittest.TestCase):
    def setUp(self):
        self.dataframe = pd.DataFrame(
            {
                "district": ["North", "South", "North", "South", "East"],
                "age": [20, 21, 22, 23, 24],
                "empty": [None, None, None, None, None],
            }
        )

    def test_nominal_detection_uses_unique_non_null_percentage(self):
        results = {
            item.attribute: item
            for item in analyze_column_types(
                self.dataframe,
                detect_nominal_attributes=True,
                nominal_unique_threshold_percent=60.0,
            )
        }

        self.assertTrue(results["district"].is_nominal)
        self.assertFalse(results["age"].is_nominal)
        self.assertIsNone(results["empty"].is_nominal)
        self.assertAlmostEqual(results["district"].unique_percent, 60.0)

    def test_nominal_detection_can_be_disabled(self):
        results = analyze_column_types(self.dataframe)
        self.assertTrue(all(item.is_nominal is None for item in results))
        self.assertTrue(all(item.unique_count is None for item in results))

    def test_default_ten_percent_threshold_flags_low_cardinality_column(self):
        dataframe = pd.DataFrame(
            {
                "color": ["red"] * 50 + ["blue"] * 50,
                "customer_id": [f"C-{index}" for index in range(100)],
            }
        )
        results = {
            item.attribute: item
            for item in analyze_column_types(
                dataframe,
                detect_nominal_attributes=True,
                nominal_unique_threshold_percent=10.0,
            )
        }

        self.assertTrue(results["color"].is_nominal)
        self.assertFalse(results["customer_id"].is_nominal)
        self.assertAlmostEqual(results["color"].unique_percent, 2.0)


if __name__ == "__main__":
    unittest.main()
