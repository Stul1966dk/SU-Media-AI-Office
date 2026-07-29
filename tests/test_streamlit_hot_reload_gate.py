"""Mandatory regression gate for stale Streamlit module state."""

import importlib
import importlib.util
import unittest
from pathlib import Path

import core.task_deliverables as task_deliverables


ROOT = Path(__file__).resolve().parents[1]
DAILY_WORK_PAGE = ROOT / "dashboard" / "pages" / "15_Dagens_Arbejde.py"


class StreamlitHotReloadGateTests(unittest.TestCase):
    def test_daily_work_recovers_new_api_from_stale_loaded_module(self) -> None:
        """Simulate the server retaining a pre-change module in memory."""
        required = (
            "format_title_meta_option",
            "prefer_pipe_separator",
            "split_title_meta_option",
        )
        for name in required:
            self.assertTrue(hasattr(task_deliverables, name))
            delattr(task_deliverables, name)

        try:
            spec = importlib.util.spec_from_file_location(
                "daily_work_hot_reload_gate", DAILY_WORK_PAGE
            )
            page = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(page)
        finally:
            importlib.reload(task_deliverables)

        for name in required:
            self.assertTrue(hasattr(page, name))
            self.assertTrue(callable(getattr(page, name)))

    def test_daily_work_reloads_dependency_before_binding_symbols(self) -> None:
        source = DAILY_WORK_PAGE.read_text(encoding="utf-8")
        reload_at = source.index(
            "task_deliverables_module = importlib.reload("
        )
        binding_at = source.index(
            "format_title_meta_option = task_deliverables_module."
        )

        self.assertLess(reload_at, binding_at)
        self.assertNotIn(
            "from core.task_deliverables import",
            source,
        )


if __name__ == "__main__":
    unittest.main()
