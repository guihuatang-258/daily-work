"""Flow 分组模板文件测试。"""

import json
import unittest
from pathlib import Path

from dify_api.flow_groups import load_flow_groups


PROJECT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_DIR / "dify_flow_groups.example.json"


class FlowGroupsTemplateTests(unittest.TestCase):
    def test_template_is_valid_json(self) -> None:
        with TEMPLATE_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)

        self.assertIsInstance(config.get("groups"), dict)
        self.assertTrue(config["groups"])

    def test_template_matches_runtime_schema(self) -> None:
        groups = load_flow_groups(TEMPLATE_PATH)

        self.assertIn("example_workflows", groups)
        self.assertIn("example_chatflows", groups)
        self.assertEqual(
            groups["example_workflows"]["apps"][0]["mode"],
            "workflow",
        )
        self.assertEqual(
            groups["example_chatflows"]["apps"][0]["mode"],
            "advanced-chat",
        )


if __name__ == "__main__":
    unittest.main()
