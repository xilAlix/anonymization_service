import json
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
from infrastructure.attribute_profile_store import (
    new_manual_quasi_identifier_group,
    save_manual_role_overrides,
    save_quasi_identifier_groups,
)
from infrastructure.settings_manager import (
    AnonymizationSettings,
    AppSettings,
    KAnonymizationSettings,
    save_settings,
)


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

    def test_set_roles_warns_when_direct_identifier_is_also_sensitive(self):
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli([
                "set-roles", str(self.csv_path),
                "--column", "customer_id",
                "--roles", "direct_identifier", "sensitive_attribute",
            ])
        self.assertEqual(code, 0)
        self.assertIn("исключён из l-проверки", output.getvalue())

    def test_evaluate_l_reports_not_evaluable_when_only_sensitive_field_is_direct_identifier(self):
        dataframe = pd.DataFrame({"qi": ["same"] * 4, "account": ["A", "B", "C", "D"]})
        dataframe.to_csv(self.csv_path, index=False)
        group = new_manual_quasi_identifier_group("QI", ["qi"])
        save_quasi_identifier_groups(
            self.csv_path, [group], list(dataframe.columns), self.profile_path
        )
        save_manual_role_overrides(
            self.csv_path,
            {"account": ["direct_identifier", "sensitive_attribute"]},
            self.profile_path,
        )
        report_path = self.root / "l-report.json"
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli([
                "evaluate-l-diversity", str(self.csv_path),
                "--l", "2", "--variant", "both",
                "--report-json", str(report_path),
            ])
        self.assertEqual(code, 1)
        self.assertIn("статус=not_evaluable", output.getvalue())
        self.assertIn("account", output.getvalue())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "not_evaluable")

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

    def test_remove_direct_identifiers_requires_manual_role_and_writes_output(self):
        error_output = StringIO()
        with redirect_stderr(error_output):
            code = cli.run_cli([
                "remove-direct-identifiers",
                str(self.csv_path),
                str(self.root / "without_ids.csv"),
            ])
        self.assertEqual(code, 2)
        self.assertIn("вручную не назначен", error_output.getvalue())

        cli.run_cli([
            "set-roles", str(self.csv_path),
            "--column", "customer_id",
            "--roles", "direct_identifier",
        ])
        output_path = self.root / "without_ids.csv"
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli([
                "remove-direct-identifiers",
                str(self.csv_path),
                str(output_path),
            ])
        self.assertEqual(code, 0)
        result = pd.read_csv(output_path)
        self.assertNotIn("customer_id", result.columns)
        self.assertEqual(result["age"].tolist(), [20, 30, 20])
        self.assertIn("Удалённые столбцы: customer_id", output.getvalue())
        self.assertIn("customer_id", pd.read_csv(self.csv_path).columns)

    def test_anonymize_refuses_to_overwrite_input(self):
        output = StringIO()
        with redirect_stderr(output):
            code = cli.run_cli([
                "anonymize", str(self.csv_path), str(self.csv_path)
            ])
        self.assertEqual(code, 2)
        self.assertIn("не должен совпадать", output.getvalue())


    def test_k_anonymize_aborts_without_csv_when_l_diversity_fails(self):
        dataframe = pd.DataFrame({
            "qi": ["same"] * 4,
            "sensitive": ["same-value"] * 4,
        })
        dataframe.to_csv(self.csv_path, index=False)
        group = new_manual_quasi_identifier_group("Тестовый QI", ["qi"])
        save_quasi_identifier_groups(
            self.csv_path, [group], list(dataframe.columns), self.profile_path
        )
        save_manual_role_overrides(
            self.csv_path,
            {"sensitive": ["sensitive_attribute"]},
            self.profile_path,
        )
        output_path = self.root / "result.csv"
        report_path = self.root / "failure.json"
        error_output = StringIO()
        with redirect_stderr(error_output):
            code = cli.run_cli([
                "k-anonymize", str(self.csv_path), str(output_path),
                "--k", "2", "--l-diversity", "--l", "2",
                "--report-json", str(report_path),
            ])
        self.assertEqual(code, 2)
        self.assertFalse(output_path.exists())
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "l_diversity_failed")
        self.assertIn("CSV-результат не сохранён", error_output.getvalue())

    def test_evaluate_l_diversity_uses_profile_source_for_external_output(self):
        dataframe = pd.DataFrame({
            "qi": ["same"] * 4,
            "sensitive": ["a", "a", "b", "b"],
        })
        dataframe.to_csv(self.csv_path, index=False)
        group = new_manual_quasi_identifier_group("Тестовый QI", ["qi"])
        save_quasi_identifier_groups(
            self.csv_path, [group], list(dataframe.columns), self.profile_path
        )
        save_manual_role_overrides(
            self.csv_path,
            {"sensitive": ["sensitive_attribute"]},
            self.profile_path,
        )
        anonymized_path = self.root / "anonymized.csv"
        dataframe.to_csv(anonymized_path, index=False)
        output = StringIO()
        with redirect_stdout(output):
            code = cli.run_cli([
                "evaluate-l-diversity", str(anonymized_path),
                "--profile-source", str(self.csv_path), "--l", "2",
            ])
        self.assertEqual(code, 0)
        self.assertIn("статус=satisfied", output.getvalue())


    def test_anonymize_selected_aborts_without_csv_when_l_diversity_fails(self):
        dataframe = pd.DataFrame({
            "qi": ["same"] * 4,
            "sensitive": ["private-value"] * 4,
        })
        dataframe.to_csv(self.csv_path, index=False)
        group = new_manual_quasi_identifier_group("Тестовый QI", ["qi"])
        save_quasi_identifier_groups(
            self.csv_path, [group], list(dataframe.columns), self.profile_path
        )
        save_manual_role_overrides(
            self.csv_path,
            {"sensitive": ["sensitive_attribute"]},
            self.profile_path,
        )
        save_settings(
            AppSettings(
                anonymization=AnonymizationSettings(
                    tokenize_direct_identifiers=False,
                    remove_direct_identifiers=False,
                    enable_k_anonymity=True,
                ),
                k_anonymization=KAnonymizationSettings(
                    default_k=2,
                    enable_l_diversity=True,
                    default_l=2,
                    l_diversity_variant="both",
                ),
            ),
            cli.SETTINGS_PATH,
        )
        output_path = self.root / "selected.csv"
        error_output = StringIO()
        with redirect_stderr(error_output):
            code = cli.run_cli([
                "anonymize-selected", str(self.csv_path), str(output_path)
            ])
        self.assertEqual(code, 2)
        self.assertFalse(output_path.exists())
        failure_report = self.root / "selected_l_diversity_failed_report.json"
        self.assertTrue(failure_report.exists())
        payload = failure_report.read_text(encoding="utf-8")
        self.assertNotIn("private-value", payload)


if __name__ == "__main__":
    unittest.main()
