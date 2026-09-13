"""V10.2 启动自检测试；不创建模型客户端、不访问网络。"""

import os
import tempfile
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from doctor import run_doctor


class DoctorTests(unittest.TestCase):
    def test_valid_local_environment_passes_without_exposing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "api.env").write_text(
                "API_KEY=doctor-secret\n"
                "BASE_URL=https://example.com/v1\n"
                "MODEL=fake-model\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                report = run_doctor(root, root / "state.sqlite3")

        self.assertTrue(report.ok)
        rendered = "\n".join(item.detail for item in report.checks)
        self.assertNotIn("doctor-secret", rendered)
        self.assertIn("model=fake-model", rendered)

    def test_missing_dependencies_and_configuration_are_reported_without_import_crash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True), patch(
                "doctor.version", side_effect=PackageNotFoundError
            ):
                report = run_doctor(root, root / "state.sqlite3")

        config_check = next(item for item in report.checks if item.name == "api.env")
        dependency_check = next(
            item for item in report.checks if item.name == "Python 依赖"
        )
        self.assertFalse(report.ok)
        self.assertFalse(config_check.ok)
        self.assertFalse(dependency_check.ok)
        self.assertIn("API_KEY", config_check.detail)


if __name__ == "__main__":
    unittest.main()
