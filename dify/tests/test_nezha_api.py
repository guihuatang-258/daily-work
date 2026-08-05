"""nezha_api 的离线单元测试。"""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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
    load_scheduled_auth_headers,
    normalize_query_mode,
    pick_app_token_period,
    pick_failure_check_group,
    pick_flow_group_token_period,
    pick_generic_workflow_action,
    run_cookie_refresh,
)
from nezha_api.flow_groups import get_monitoring_time_range, load_flow_group
from nezha_api.markdown import table
from nezha_api.monitor import (
    collect_app_failure_stats,
    print_group_failure_report,
)
from nezha_api.progress import format_progress
from nezha_api.reports import (
    print_flow_group_token_stats,
    print_workflow_run,
)
from nezha_api.settings import MONITOR_TIMEZONE
from nezha_api.stats import (
    evenly_sample_workflow_runs,
    normalize_quality_user_id,
)


class MarkdownTests(unittest.TestCase):
    def test_table_escapes_pipe_and_newline(self) -> None:
        output = table(["名称", "值"], [["Flow | A", "第一行\n第二行"]])
        self.assertIn("Flow \\| A", output)
        self.assertIn("第一行<br>第二行", output)

    def test_table_uses_standard_alignment_markers(self) -> None:
        output = table(
            ["名称", "状态", "数量"],
            [["Flow A", "成功", 12]],
            ["left", "center", "right"],
        )
        self.assertEqual(output.splitlines()[1], "| :--- | :---: | ---: |")

    def test_table_rejects_invalid_row_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "预期 2 列"):
            table(["名称", "数量"], [["Flow A"]])

    def test_table_escapes_backslash_before_pipe(self) -> None:
        output = table(["路径"], [[r"folder\|name"]])
        self.assertIn(r"folder\\\|name", output)

    def test_workflow_report_is_markdown_and_saves_json(self) -> None:
        data = {
            "id": "run-1",
            "status": "succeeded",
            "elapsed_time": 1.2,
            "total_tokens": 42,
            "total_steps": 2,
            "created_at": "2026-07-22T10:00:00",
            "finished_at": "2026-07-22T10:00:01",
            "inputs": {"query": "hello"},
            "outputs": {"answer": "world"},
        }
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "run.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                print_workflow_run(data, output_path)
            output = buffer.getvalue()
            self.assertIn("## API 2 单次运行详情返回结果", output)
            self.assertIn("| 运行 ID | run-1 |", output)
            self.assertTrue(output_path.exists())

    @patch("nezha_api.reports.collect_flow_group_token_stats")
    @patch("nezha_api.reports.load_flow_group")
    def test_flow_group_report_formats_numeric_columns(
        self, load_group, collect_stats
    ) -> None:
        load_group.return_value = {
            "display_name": "测试组",
            "apps": [{"app_id": "app-1"}],
        }
        collect_stats.return_value = [{
            "name": "Flow A",
            "mode": "workflow",
            "records": 1234,
            "success": 1230,
            "failed": 4,
            "input_tokens": 1000,
            "output_tokens": 2345,
            "total_tokens": 3345,
            "complete": True,
            "io_available": True,
            "io_estimated": True,
        }]
        now = datetime(2026, 7, 22, 12, 30, tzinfo=MONITOR_TIMEZONE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_flow_group_token_stats({}, "test", "today", now)
        output = buffer.getvalue()
        self.assertIn(
            "| :--- | :---: | ---: | ---: | ---: | ---: |",
            output,
        )
        self.assertIn(
            "| Flow A | workflow | 1,234 | ~1,000 | ~2,345 | 3,345 |",
            output,
        )
        self.assertNotIn("| 异常 |", output)
        self.assertIn("### 执行结果", output)
        self.assertIn("- **成功次数：** 1,230", output)
        self.assertIn("- **失败次数：** 4", output)

    @patch("nezha_api.reports.collect_flow_group_token_stats")
    @patch("nezha_api.reports.load_flow_group")
    def test_flow_group_report_does_not_render_failed_fetch_as_zero(
        self, load_group, collect_stats
    ) -> None:
        load_group.return_value = {
            "display_name": "测试组",
            "apps": [{"app_id": "app-1"}],
        }
        collect_stats.return_value = [{
            "name": "Flow A",
            "mode": "advanced-chat",
            "records": 0,
            "success": 0,
            "failed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "complete": False,
            "data_available": False,
            "io_available": True,
            "io_estimated": False,
        }]
        now = datetime(2026, 7, 23, 12, 30, tzinfo=MONITOR_TIMEZONE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_flow_group_token_stats({}, "test", "today", now)
        output = buffer.getvalue()
        self.assertIn(
            "| Flow A | advanced-chat | — * | — * | — * | — * |",
            output,
        )
        self.assertIn(
            "| **总计** | — | 0 * | — | — | 0 * |",
            output,
        )
        self.assertIn("- **成功次数：** 0 *", output)
        self.assertIn("- **失败次数：** 0 *", output)

    @patch("nezha_api.monitor.collect_app_failure_stats")
    @patch("nezha_api.monitor.load_flow_groups")
    def test_failure_monitor_report_is_concise_markdown(
        self, load_groups, collect_stats
    ) -> None:
        load_groups.return_value = {
            "coach": {
                "display_name": "Coach 组",
                "apps": [{"app_id": "app-1", "name": "Flow A"}],
            },
            "knowledge_search": {
                "display_name": "KS组",
                "apps": [{"app_id": "app-2", "name": "Flow B"}],
            },
        }
        collect_stats.return_value = [
            {
                "group_name": "coach",
                "name": "Flow A",
                "mode": "workflow",
                "failed": 1,
                "complete": True,
            },
            {
                "group_name": "knowledge_search",
                "name": "Flow B",
                "mode": "advanced-chat",
                "failed": 0,
                "complete": True,
            },
        ]
        now = datetime(2026, 7, 27, 13, 0, tzinfo=MONITOR_TIMEZONE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            found = print_group_failure_report(
                {}, ["coach", "knowledge_search"], now
            )
        output = buffer.getvalue()
        self.assertTrue(found)
        self.assertIn("| Coach 组 | 1 | 1 | 检查完成 |", output)
        self.assertIn("| KS组 | 1 | 0 | 检查完成 |", output)
        self.assertIn("### 失败应用", output)
        self.assertIn("| Coach 组 | Flow A | workflow | 1 |", output)
        self.assertIn("发现 **1** 次失败运行", output)


class DomainTests(unittest.TestCase):
    def test_shared_progress_bar_format(self) -> None:
        stream = SimpleNamespace(encoding="utf-8")
        with patch("nezha_api.progress.sys.stdout", stream):
            progress = format_progress(1, 4, width=4)
        self.assertIn("[█░░░]", progress)
        self.assertIn("1/4", progress)
        self.assertIn("25%", progress)

    def test_progress_bar_falls_back_for_legacy_console_encoding(self) -> None:
        stream = SimpleNamespace(encoding="ascii")
        with patch("nezha_api.progress.sys.stdout", stream):
            progress = format_progress(1, 4, width=4)
        self.assertIn("[#---]", progress)

    def test_empty_progress_is_complete(self) -> None:
        stream = SimpleNamespace(encoding="utf-8")
        with patch("nezha_api.progress.sys.stdout", stream):
            progress = format_progress(0, 0, width=4)
        self.assertEqual(progress, "[████] 0/0 100%")

    def test_isa_group_contains_expected_apps(self) -> None:
        group = load_flow_group("isa")
        self.assertEqual(group["display_name"], "ISA组")
        self.assertEqual(
            [app["name"] for app in group["apps"]],
            [
                "【ISA】知识库检索",
                "【ISA】案例库-对话数据提取",
                "【ISA】案例库-生成案例",
                "【ISA】问答交互",
                "【ISA】生成追问话术",
            ],
        )

    def test_quality_user_suffix_is_removed(self) -> None:
        self.assertEqual(normalize_quality_user_id("user-123-4"), "user-123")
        self.assertEqual(normalize_quality_user_id("user-alpha"), "user-alpha")

    def test_workflow_sampling_is_even(self) -> None:
        logs = [{"workflow_run": {"id": str(index)}} for index in range(10)]
        sampled = evenly_sample_workflow_runs(logs, sample_size=3)
        self.assertEqual([run_id for run_id, _ in sampled], ["0", "4", "9"])

    def test_monitoring_range_uses_natural_days(self) -> None:
        now = datetime(2026, 7, 22, 12, 30, tzinfo=MONITOR_TIMEZONE)
        label, start, end = get_monitoring_time_range("7d", now)
        self.assertEqual(label, "最近 7 天")
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-16 00:00:00")
        self.assertEqual(end.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-22 23:59:59")

    @patch("nezha_api.monitor.list_all_chat_conversations_in_range")
    @patch("nezha_api.monitor.list_workflow_logs")
    def test_failure_monitor_uses_server_side_failed_filter(
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
                "group_name": "coach",
                "name": "Workflow",
                "mode": "workflow",
            },
            {
                "app_id": "chat-app",
                "group_name": "knowledge_search",
                "name": "Chatflow",
                "mode": "advanced-chat",
            },
        ]
        now = datetime(2026, 7, 27, 13, 0, tzinfo=MONITOR_TIMEZONE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats = collect_app_failure_stats({}, apps, now, now)
        self.assertEqual([item["failed"] for item in stats], [7, 4])
        progress = buffer.getvalue()
        self.assertIn("正在并行检查 2 个应用", progress)
        self.assertIn("每页 100", progress)
        self.assertIn("1/2", progress)
        self.assertIn("2/2", progress)
        workflow_logs.assert_called_once()
        call = workflow_logs.call_args.kwargs
        self.assertEqual(call["status"], "failed")
        self.assertEqual(call["limit"], 100)

    def test_yesterday_monitoring_range(self) -> None:
        now = datetime(2026, 7, 22, 12, 30, tzinfo=MONITOR_TIMEZONE)
        label, start, end = get_monitoring_time_range("yesterday", now)
        self.assertEqual(label, "昨天")
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-21 00:00:00")
        self.assertEqual(end.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-21 23:59:59")

    def test_three_day_monitoring_range_includes_today(self) -> None:
        now = datetime(2026, 7, 22, 12, 30, tzinfo=MONITOR_TIMEZONE)
        label, start, end = get_monitoring_time_range("3d", now)
        self.assertEqual(label, "最近 3 天")
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-20 00:00:00")
        self.assertEqual(end.strftime("%Y-%m-%d %H:%M:%S"), "2026-07-22 23:59:59")


class ClientAndAuthTests(unittest.TestCase):
    def test_app_pagination(self) -> None:
        responses = [
            ("url-1", {"data": [{"id": "a"}], "has_more": True}),
            ("url-2", {"data": [{"id": "b"}], "has_more": False}),
        ]
        with patch("nezha_api.client.list_workflow_apps", side_effect=responses):
            urls, apps = list_all_apps({}, limit=1)
        self.assertEqual(urls, ["url-1", "url-2"])
        self.assertEqual([app["id"] for app in apps], ["a", "b"])

    def test_auth_headers_use_csrf_cookie(self) -> None:
        headers = build_auth_headers("foo=bar; __Host-csrf_token=csrf-value")
        self.assertEqual(headers["X-CSRF-Token"], "csrf-value")
        self.assertIn("foo=bar", headers["Cookie"])

    @patch("nezha_api.client.request_json", return_value={"data": []})
    def test_workflow_logs_support_server_side_status_filter(
        self, request_json
    ) -> None:
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
        records, complete = list_all_chat_conversations_in_range(
            {}, "app-1", start, end
        )
        self.assertEqual(records, [])
        self.assertTrue(complete)
        call = list_conversations.call_args.kwargs
        self.assertEqual(call["start"], "2026-07-23 00:00")
        self.assertEqual(call["end"], "2026-07-23 23:59")


class CliTests(unittest.TestCase):
    @patch.dict("os.environ", {"NEZHA_COOKIE_REFRESH_POPUP": "1"})
    @patch("builtins.input")
    @patch("nezha_api.cli.ensure_valid_auth_headers")
    def test_successful_cookie_refresh_closes_popup_automatically(
        self, ensure_auth, popup_input
    ) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_cookie_refresh()
        self.assertEqual(result, 0)
        ensure_auth.assert_called_once_with()
        popup_input.assert_not_called()

    @patch("nezha_api.cli.refresh_auth_in_new_console", return_value=True)
    @patch(
        "nezha_api.cli.validate_auth_headers",
        side_effect=[
            ("expired", "认证已过期（HTTP 401）"),
            ("valid", "认证有效"),
        ],
    )
    @patch("nezha_api.cli.load_auth_headers", return_value={"Cookie": "new"})
    def test_scheduled_check_refreshes_expired_cookie_in_new_console(
        self, load_headers, _validate, refresh_console
    ) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            headers = load_scheduled_auth_headers()
        self.assertEqual(headers, {"Cookie": "new"})
        self.assertEqual(load_headers.call_count, 2)
        refresh_console.assert_called_once_with()
        self.assertIn("正在打开 Cookie 更新窗口", buffer.getvalue())
        self.assertIn("继续执行失败运行检查", buffer.getvalue())

    @patch("nezha_api.cli.load_flow_groups")
    @patch("builtins.input", return_value="0")
    def test_main_menu_keeps_plain_console_format(
        self, _input, load_groups
    ) -> None:
        load_groups.return_value = {
            "coach": {"display_name": "Coach 组", "apps": []}
        }
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = choose_query_mode()
        output = buffer.getvalue()
        self.assertEqual(result, "exit")
        self.assertIn("┌─ Dify 日志查询工具", output)
        self.assertNotIn("质检打分 Workflow", output)
        self.assertIn("│  [1] 查询 · 通用 Workflow", output)
        self.assertIn("│  [2] 查询 · Chatflow", output)
        self.assertIn("│  [3] 检查 ·", output)
        self.assertIn("│  [4] 统计 · Coach 组 Token 消耗", output)
        self.assertIn("└─ [0] 退出", output)
        self.assertNotIn("## ", output)
        self.assertNotIn("`1`", output)

    def test_main_menu_shortcuts_shift_forward(self) -> None:
        self.assertEqual(normalize_query_mode(""), "workflow")
        self.assertEqual(normalize_query_mode("1"), "workflow")
        self.assertEqual(normalize_query_mode("2"), "chatflow")
        self.assertIsNone(normalize_query_mode("3"))
        self.assertIsNone(normalize_query_mode("quality-workflow"))

    @patch("nezha_api.cli.load_flow_groups")
    @patch("builtins.input", return_value="3")
    def test_main_menu_routes_failure_check(
        self, _input, load_groups
    ) -> None:
        load_groups.return_value = {}
        with contextlib.redirect_stdout(io.StringIO()):
            result = choose_query_mode()
        self.assertEqual(result, "failure-check")

    @patch("nezha_api.cli.print_group_failure_report")
    @patch("nezha_api.cli.load_flow_groups")
    def test_failure_check_menu_supports_single_group_and_all(
        self, load_groups, print_report
    ) -> None:
        load_groups.return_value = {
            "coach": {"display_name": "Coach 组", "apps": []},
            "knowledge_search": {"display_name": "KS组", "apps": []},
        }
        headers = {"Authorization": "test"}
        cases = (
            ("1", ["coach", "knowledge_search"]),
            ("3", ["knowledge_search"]),
        )
        for choice, expected in cases:
            with self.subTest(choice=choice):
                print_report.reset_mock()
                with patch("builtins.input", return_value=choice):
                    with contextlib.redirect_stdout(io.StringIO()):
                        pick_failure_check_group(headers)
                print_report.assert_called_once_with(headers, expected)

    @patch("builtins.input", return_value="")
    def test_action_menu_keeps_plain_console_format(self, _input) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            pick_generic_workflow_action({}, "app-1")
        output = buffer.getvalue()
        self.assertIn("┌─ 通用 Workflow", output)
        self.assertIn("│  [1] 查看最近日志", output)
        self.assertIn("└─ [Enter] 取消", output)
        self.assertNotIn("###", output)
        self.assertNotIn("`1`", output)

    @patch("nezha_api.cli.print_flow_group_token_stats")
    @patch("nezha_api.cli.load_flow_group")
    def test_period_menu_routes_new_periods(
        self, load_group, print_stats
    ) -> None:
        load_group.return_value = {"display_name": "测试组"}
        for choice, expected_period in (("3", "yesterday"), ("4", "3d")):
            with self.subTest(choice=choice):
                print_stats.reset_mock()
                buffer = io.StringIO()
                with patch("builtins.input", return_value=choice):
                    with contextlib.redirect_stdout(buffer):
                        pick_flow_group_token_period({}, "test")
                output = buffer.getvalue()
                self.assertIn("│  [3] 昨天", output)
                self.assertIn("│  [4] 最近 3 天", output)
                self.assertIn("└─ [0] 返回主界面", output)
                print_stats.assert_called_once_with(
                    {}, "test", expected_period
                )

    @patch("nezha_api.cli.print_apps_token_stats")
    @patch("nezha_api.cli.choose_token_period", return_value="3d")
    def test_single_app_reuses_group_token_statistics(
        self, _choose_period, print_stats
    ) -> None:
        app = {
            "id": "app-1",
            "name": "知识库检索",
            "mode": "advanced-chat",
        }
        headers = {"Authorization": "test"}
        pick_app_token_period(headers, app)
        print_stats.assert_called_once_with(
            headers,
            "知识库检索",
            [{
                "app_id": "app-1",
                "name": "知识库检索",
                "mode": "advanced-chat",
            }],
            "3d",
        )

    @patch("nezha_api.cli.pick_app_token_period")
    @patch("builtins.input", return_value="2")
    def test_generic_workflow_token_action_uses_common_period_flow(
        self, _input, pick_period
    ) -> None:
        app = {"id": "app-1", "name": "通用流", "mode": "workflow"}
        with contextlib.redirect_stdout(io.StringIO()):
            pick_generic_workflow_action({}, app)
        pick_period.assert_called_once_with({}, app)


if __name__ == "__main__":
    unittest.main()
