import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from application import cli


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.csv_path = self.root / "input.csv"
        self.profile_path = self.root / "profiles.json"
        pd.DataFrame(
            {"customer_id": ["C1", "C2", "C1"], "age": [20, 30, 20]}
        ).to_csv(self.csv_path, index=False)
        self.original_profile_path = cli.PROFILE_PATH
        self.original_settings_path = cli.SETTINGS_PATH
        cli.PROFILE_PATH = self.profile_path
        cli.SETTINGS_PATH = self.root / "settings.json"

    def tearDown(self):
        cli.PROFILE_PATH = self.original_profile_path
        cli.SETTINGS_PATH = self.original_settings_path
        self.temp_dir.cleanup()

    def test_classify_attributes_prints_automatic_suggestions(self):
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli(["classify-attributes", str(self.csv_path)])
        self.assertEqual(code, 0)
        self.assertIn("customer_id", output.getvalue())
        self.assertIn("Прямой идентификатор", output.getvalue())

    def test_set_roles_persists_manual_assignment(self):
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli([
                "set-roles", str(self.csv_path),
                "--column", "customer_id",
                "--roles", "direct_identifier",
            ])
        self.assertEqual(code, 0)
        self.assertTrue(self.profile_path.exists())

    def test_anonymize_requires_manual_role_and_writes_output(self):
        error_output = StringIO()
        with redirect_stderr(error_output):
            code = cli.run_cli([
                "anonymize", str(self.csv_path), str(self.root / "out.csv")
            ])
        self.assertEqual(code, 2)
        self.assertIn("вручную не назначен", error_output.getvalue())

        cli.run_cli([
            "set-roles", str(self.csv_path),
            "--column", "customer_id",
            "--roles", "direct_identifier",
        ])
        output_path = self.root / "out.csv"
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli(["anonymize", str(self.csv_path), str(output_path)])
        self.assertEqual(code, 0)
        result = pd.read_csv(output_path)
        self.assertNotEqual(result["customer_id"].iloc[0], "C1")
        self.assertEqual(result["customer_id"].iloc[0], result["customer_id"].iloc[2])
        self.assertIn("псевдонимизацией", output.getvalue())

    def test_anonymize_refuses_to_overwrite_input(self):
        output = StringIO()
        with redirect_stderr(output):
            code = cli.run_cli([
                "anonymize", str(self.csv_path), str(self.csv_path)
            ])
        self.assertEqual(code, 2)
        self.assertIn("не должен совпадать", output.getvalue())


if __name__ == "__main__":
    unittest.main()
