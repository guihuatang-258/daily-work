"""Dify 监控工具的离线行为测试。

测试只关注输入、返回值和模块调用关系，不检查终端颜色、边框或具体菜单文案。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nezha_api.auth import build_auth_headers
from nezha_api.client import (
    list_all_apps,
    list_all_chat_conversations_in_range,
    list_workflow_logs,
)
from nezha_api.cli import (
    choose_query_mode,
    normalize_query_mode,
    pick_app_token_period,
    pick_failure_check_group,
    pick_flow_group_token_period,
    pick_generic_workflow_action,
)
from nezha_api.flow_groups import (
    get_monitoring_time_range,
    load_flow_group,
    load_flow_groups,
)
from nezha_api.markdown import table
from nezha_api.monitor import collect_app_failure_stats
from nezha_api.settings import MONITOR_TIMEZONE
from nezha_api.stats import evenly_sample_workflow_runs, normalize_quality_user_id


class MarkdownTests(unittest.TestCase):
    def test_table_escapes_special_content(self) -> None:
        output = table(["名称", "值"], [[r"Flow \| A", "第一行\n第二行"]])
        self.assertIn(r"Flow \\\| A", output)
        self.assertIn("第一行<br>第二行", output)

    def test_table_rejects_incorrect_row_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "预期 2 列"):
            table(["名称", "数量"], [["Flow A"]])


class FlowGroupTests(unittest.TestCase):
    def _write_config(self, directory: str, config: dict) -> Path:
        path = Path(directory) / "groups.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return path

    def test_loads_group_from_explicit_file(self) -> None:
        config = {
            "groups": {
                "example": {
                    "display_name": "示例组",
                    "apps": [{
                        "name": "示例应用",
                        "app_id": "00000000-0000-0000-0000-000000000001",
                        "mode": "workflow",
                    }],
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, config)
            group = load_flow_group("example", path)
        self.assertEqual(group["display_name"], "示例组")
        self.assertEqual(group["apps"][0]["mode"], "workflow")

    def test_missing_group_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, {"groups": {}})
            with self.assertRaisesRegex(RuntimeError, "Flow 组不存在"):
                load_flow_group("missing", path)

    def test_duplicate_app_id_is_rejected(self) -> None:
        app = {
            "name": "示例应用",
            "app_id": "00000000-0000-0000-0000-000000000001",
            "mode": "workflow",
        }
        config = {
            "groups": {
                "example": {
                    "display_name": "示例组",
                    "apps": [app, dict(app)],
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, config)
            with self.assertRaisesRegex(RuntimeError, "重复 app_id"):
                load_flow_groups(path)

    def test_unsupported_mode_is_rejected(self) -> None:
        config = {
            "groups": {
                "example": {
                    "display_name": "示例组",
                    "apps": [{
                        "name": "示例应用",
                        "app_id": "00000000-0000-0000-0000-000000000001",
                        "mode": "unsupported",
                    }],
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory, config)
            with self.assertRaisesRegex(RuntimeError, "不支持的 mode"):
                load_flow_groups(path)


class TimeRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 22, 12, 30, tzinfo=MONITOR_TIMEZONE)

    def test_today_uses_natural_day(self) -> None:
        label, start, end = get_monitoring_time_range("today", self.now)
        self.assertEqual(label, "今天")
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-22 00:00:00")
        self.assertEqual(end.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-22 23:59:59")

    def test_relative_periods_include_expected_days(self) -> None:
        cases = {
            "yesterday": ("昨天", "2026-07-21 00:00:00"),
            "3d": ("最近 3 天", "2026-07-20 00:00:00"),
            "7d": ("最近 7 天", "2026-07-16 00:00:00"),
        }
        for period, (expected_label, expected_start) in cases.items():
            with self.subTest(period=period):
                label, start, end = get_monitoring_time_range(period, self.now)
                self.assertEqual(label, expected_label)
                self.assertEqual(start.strftime("%Y-%m-%d %H:%M:%S"), expected_start)
                self.assertEqual(end.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-22 23:59:59")

    def test_unknown_period_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_monitoring_time_range("30d", self.now)


class StatsTests(unittest.TestCase):
    def test_quality_user_suffix_is_removed(self) -> None:
        self.assertEqual(normalize_quality_user_id("user-123-4"), "user-123")
        self.assertEqual(normalize_quality_user_id("user-alpha"), "user-alpha")

    def test_workflow_sampling_is_even(self) -> None:
        logs = [{"workflow_run": {"id": str(index)}} for index in range(10)]
        sampled = evenly_sample_workflow_runs(logs, sample_size=3)
        self.assertEqual([run_id for run_id, _ in sampled], ["0", "4", "9"])


class ClientAndAuthTests(unittest.TestCase):
    def test_auth_headers_use_csrf_cookie(self) -> None:
        headers = build_auth_headers("foo=bar; __Host-csrf_token=csrf-value")
        self.assertEqual(headers["X-CSRF-Token"], "csrf-value")
        self.assertIn("foo=bar", headers["Cookie"])

    def test_app_pagination_collects_every_page(self) -> None:
        responses = [
            ("url-1", {"data": [{"id": "a"}], "has_more": True}),
            ("url-2", {"data": [{"id": "b"}], "has_more": False}),
        ]
        with patch("nezha_api.client.list_workflow_apps", side_effect=responses):
            urls, apps = list_all_apps({}, limit=1)
        self.assertEqual(urls, ["url-1", "url-2"])
        self.assertEqual([app["id"] for app in apps], ["a", "b"])

    @patch("nezha_api.client.request_json", return_value={"data": []})
    def test_workflow_log_query_passes_filters(self, request_json) -> None:
        url, _ = list_workflow_logs(
            {},
            "app-1",
            limit=10,
            status="failed",
            created_at_after="2026-07-27T00:00:00+08:00",
            created_at_before="2026-07-27T23:59:59+08:00",
        )
        self.assertIn("limit=10", url)
        self.assertIn("status=failed", url)
        self.assertIn("created_at__after=", url)
        request_json.assert_called_once()

    @patch("nezha_api.client.list_chat_conversations")
    def test_chat_range_uses_api_minute_format(self, list_conversations) -> None:
        list_conversations.return_value = (
            "url",
            {"data": [], "total": 0, "has_more": False},
        )
        start = datetime(2026, 7, 23, 0, 0, tzinfo=MONITOR_TIMEZONE)
        end = datetime(2026, 7, 23, 23, 59, 59, tzinfo=MONITOR_TIMEZONE)
        records, complete = list_all_chat_conversations_in_range({}, "app-1", start, end)
        self.assertEqual(records, [])
        self.assertTrue(complete)
        call = list_conversations.call_args.kwargs
        self.assertEqual(call["start"], "2026-07-23 00:00")
        self.assertEqual(call["end"], "2026-07-23 23:59")


class MonitorTests(unittest.TestCase):
    @patch("nezha_api.monitor.list_all_chat_conversations_in_range")
    @patch("nezha_api.monitor.list_workflow_logs")
    def test_failure_collection_uses_correct_source_for_each_mode(
        self, workflow_logs, chat_conversations
    ) -> None:
        workflow_logs.return_value = (
            "url",
            {"total": 7, "data": [{"workflow_run": {"status": "failed"}}]},
        )
        chat_conversations.return_value = (
            [
                {"status_count": {"success": 2, "failed": 1}},
                {"status_count": {"success": 1, "failed": 3}},
            ],
            True,
        )
        apps = [
            {
                "app_id": "workflow-app",
                "group_name": "group-a",
                "name": "Workflow",
                "mode": "workflow",
            },
            {
                "app_id": "chat-app",
                "group_name": "group-b",
                "name": "Chatflow",
                "mode": "advanced-chat",
            },
        ]
        now = datetime(2026, 7, 27, 13, 0, tzinfo=MONITOR_TIMEZONE)
        with contextlib.redirect_stdout(io.StringIO()):
            stats = collect_app_failure_stats({}, apps, now, now)
        self.assertEqual([item["failed"] for item in stats], [7, 4])
        workflow_logs.assert_called_once()
        self.assertEqual(workflow_logs.call_args.kwargs["status"], "failed")
        chat_conversations.assert_called_once()


class CliTests(unittest.TestCase):
    def test_query_mode_normalization(self) -> None:
        self.assertEqual(normalize_query_mode(""), "workflow")
        self.assertEqual(normalize_query_mode("1"), "workflow")
        self.assertEqual(normalize_query_mode("2"), "chatflow")
        self.assertIsNone(normalize_query_mode("3"))
        self.assertIsNone(normalize_query_mode("unknown"))

    @patch("nezha_api.cli.load_flow_groups", return_value={})
    @patch("builtins.input", return_value="3")
    def test_main_menu_routes_failure_check(self, _input, _load_groups) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = choose_query_mode()
        self.assertEqual(result, "failure-check")

    @patch("nezha_api.cli.print_group_failure_report")
    @patch("nezha_api.cli.load_flow_groups")
    def test_failure_check_selection_passes_expected_groups(
        self, load_groups, print_report
    ) -> None:
        load_groups.return_value = {
            "group_a": {"display_name": "A 组", "apps": []},
            "group_b": {"display_name": "B 组", "apps": []},
        }
        headers = {"Authorization": "test"}
        for choice, expected in (("1", ["group_a", "group_b"]), ("3", ["group_b"])):
            with self.subTest(choice=choice):
                print_report.reset_mock()
                with patch("builtins.input", return_value=choice):
                    with contextlib.redirect_stdout(io.StringIO()):
                        pick_failure_check_group(headers)
                print_report.assert_called_once_with(headers, expected)

    @patch("nezha_api.cli.print_flow_group_token_stats")
    @patch("nezha_api.cli.load_flow_group", return_value={"display_name": "测试组"})
    def test_period_selection_passes_period_code(self, _load_group, print_stats) -> None:
        for choice, expected_period in (("3", "yesterday"), ("4", "3d")):
            with self.subTest(choice=choice):
                print_stats.reset_mock()
                with patch("builtins.input", return_value=choice):
                    with contextlib.redirect_stdout(io.StringIO()):
                        pick_flow_group_token_period({}, "test")
                print_stats.assert_called_once_with({}, "test", expected_period)

    @patch("nezha_api.cli.print_apps_token_stats")
    @patch("nezha_api.cli.choose_token_period", return_value="3d")
    def test_single_app_token_query_reuses_common_report(
        self, _choose_period, print_stats
    ) -> None:
        app = {"id": "app-1", "name": "知识库检索", "mode": "advanced-chat"}
        pick_app_token_period({"Authorization": "test"}, app)
        print_stats.assert_called_once_with(
            {"Authorization": "test"},
            "知识库检索",
            [{"app_id": "app-1", "name": "知识库检索", "mode": "advanced-chat"}],
            "3d",
        )

    @patch("nezha_api.cli.pick_app_token_period")
    @patch("builtins.input", return_value="2")
    def test_workflow_token_action_routes_to_common_period_flow(
        self, _input, pick_period
    ) -> None:
        app = {"id": "app-1", "name": "通用流", "mode": "workflow"}
        with contextlib.redirect_stdout(io.StringIO()):
            pick_generic_workflow_action({}, app)
        pick_period.assert_called_once_with({}, app)


if __name__ == "__main__":
    unittest.main()
