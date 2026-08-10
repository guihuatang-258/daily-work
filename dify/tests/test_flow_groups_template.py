"""Flow 分组模板文件测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from dify_api.flow_groups import (
    add_app_to_flow_group,
    create_flow_group,
    delete_flow_group,
    load_flow_groups,
    remove_app_from_flow_group,
    save_flow_groups,
    update_flow_group,
)


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

    def test_flow_group_crud_and_membership(self) -> None:
        groups = create_flow_group({}, "customer_service", "客服组")
        self.assertEqual(groups["customer_service"]["apps"], [])

        groups = add_app_to_flow_group(
            groups,
            "customer_service",
            {"id": "app-1", "name": "客服问答", "mode": "advanced-chat"},
        )
        self.assertEqual(
            groups["customer_service"]["apps"][0],
            {
                "name": "客服问答",
                "app_id": "app-1",
                "mode": "advanced-chat",
            },
        )

        groups = update_flow_group(
            groups,
            "customer_service",
            new_group_name="support",
            display_name="客户支持组",
        )
        self.assertNotIn("customer_service", groups)
        self.assertEqual(groups["support"]["display_name"], "客户支持组")

        groups = remove_app_from_flow_group(groups, "support", "app-1")
        self.assertEqual(groups["support"]["apps"], [])
        self.assertEqual(delete_flow_group(groups, "support"), {})

    def test_flow_group_crud_rejects_invalid_or_duplicate_values(self) -> None:
        groups = create_flow_group({}, "support", "支持组")
        with self.assertRaisesRegex(ValueError, "只能包含"):
            create_flow_group(groups, "中文代号", "测试")
        with self.assertRaisesRegex(ValueError, "已存在"):
            create_flow_group(groups, "support", "重复")

        groups = add_app_to_flow_group(
            groups,
            "support",
            {"id": "app-1", "name": "应用一", "mode": "workflow"},
        )
        with self.assertRaisesRegex(ValueError, "已经在"):
            add_app_to_flow_group(
                groups,
                "support",
                {"id": "app-1", "name": "应用一", "mode": "workflow"},
            )

    def test_save_flow_groups_can_create_and_reload_file(self) -> None:
        groups = create_flow_group({}, "support", "支持组")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "groups.json"
            save_flow_groups(groups, path)
            self.assertEqual(load_flow_groups(path), groups)
            self.assertFalse(list(path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
