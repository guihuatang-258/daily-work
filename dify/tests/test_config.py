"""通用监控配置的离线测试。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nezha_api.config import (
    CONFIG_ENV_NAME,
    DEFAULT_CONFIG,
    get_config_value,
    load_config,
    require_positive_int,
    resolve_config_path,
)


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.yaml")
        self.assertEqual(
            get_config_value(config, "collection.token_stats_workers"),
            DEFAULT_CONFIG["collection"]["token_stats_workers"],
        )

    def test_yaml_values_override_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                "instance:\n"
                "  base_url: https://dify.example.com\n"
                "  workspace_id: 00000000-0000-0000-0000-000000000001\n"
                "authentication:\n"
                "  type: authorization\n"
                "collection:\n"
                "  token_stats_workers: 4\n",
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(
            get_config_value(config, "instance.base_url"),
            "https://dify.example.com",
        )
        self.assertEqual(
            get_config_value(config, "instance.workspace_id"),
            "00000000-0000-0000-0000-000000000001",
        )
        self.assertEqual(
            require_positive_int(config, "collection.token_stats_workers"), 4
        )
        self.assertEqual(
            get_config_value(config, "authentication.type"),
            "authorization",
        )
        self.assertEqual(
            get_config_value(config, "collection.monitor_page_size"), 100
        )

    def test_environment_can_select_config_file(self):
        custom = Path("custom-monitor.yaml").resolve()
        with patch.dict(os.environ, {CONFIG_ENV_NAME: str(custom)}):
            self.assertEqual(resolve_config_path(), custom)

    def test_positive_integer_validation(self):
        config = {"collection": {"token_stats_workers": 0}}
        with self.assertRaises(RuntimeError):
            require_positive_int(config, "collection.token_stats_workers")

    def test_invalid_top_level_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("- invalid\n- config\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
