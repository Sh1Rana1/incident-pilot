"""不包含故障标准答案的公开 Smoke Test。"""

import unittest

from demo_app.run_case import run_case


class DemoSmokeTests(unittest.TestCase):
    def test_registered_case_entrypoint_is_callable(self) -> None:
        self.assertTrue(callable(run_case))

    def test_demo_package_imports_without_side_effects(self) -> None:
        import demo_app.app  # noqa: F401


if __name__ == "__main__":
    unittest.main()
