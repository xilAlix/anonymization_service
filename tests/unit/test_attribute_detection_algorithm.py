import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from data_processing.algorithms.attribute_detection import suggest_attribute_roles


class AttributeDetectionAlgorithmTests(unittest.TestCase):
    def test_algorithm_returns_plain_data_without_application_models(self):
        result = suggest_attribute_roles(
            "customer_id",
            ["C1", "C2", "C3"],
        )
        self.assertEqual(result[0]["role"], "direct_identifier")
        self.assertIsInstance(result[0], dict)
        self.assertIsInstance(result[0]["reasons"], list)

    def test_algorithm_uses_values_to_detect_email(self):
        result = suggest_attribute_roles(
            "contact",
            ["a@example.com", "b@example.com", "c@example.com"],
        )
        self.assertEqual(result[0]["role"], "direct_identifier")
        self.assertEqual(result[0]["confidence"], "высокая")


if __name__ == "__main__":
    unittest.main()
