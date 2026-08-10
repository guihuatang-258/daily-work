"""终端配色行为测试。"""

import os
import re
import unittest
from io import StringIO
from unittest.mock import patch

from dify_api.terminal import (
    BOLD_CYAN,
    CYAN,
    ColorStream,
    GREEN,
    RED,
    RESET,
    choose_menu,
    choose_multiple,
    color_enabled,
    style_text,
)


class FakeTTY(StringIO):
    def isatty(self):
        return True


class TerminalTests(unittest.TestCase):
    def test_menu_title_and_option_are_colored(self):
        self.assertIn(BOLD_CYAN, style_text("┌─ Dify 日志查询工具"))
        option = style_text("│  [1] 查询 · 通用 Workflow")
        self.assertIn(CYAN, option)
        self.assertIn("[1]", option)
        self.assertTrue(option.endswith(RESET) is False or RESET in option)

    def test_status_messages_use_simple_semantic_colors(self):
        self.assertIn(GREEN, style_text("认证校验成功。"))
        self.assertIn(RED, style_text("  ! 请输入数字编号。"))

    def test_plain_content_is_not_modified(self):
        text = "普通 Markdown 内容"
        self.assertEqual(style_text(text), text)

    def test_no_color_disables_tty_colors(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertFalse(color_enabled(FakeTTY()))

    def test_force_color_enables_non_tty_colors(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NO_COLOR", None)
                self.assertTrue(color_enabled(StringIO()))

    def test_multiple_choice_supports_focus_and_selection(self):
        keys = iter(["space", "down", "down", "space", "enter"])
        stream = FakeTTY()
        selected = choose_multiple(
            ["应用一", "应用二", "应用三"],
            lambda item: item,
            "选择应用",
            key_reader=lambda: next(keys),
            stream=stream,
        )
        self.assertEqual(selected, ["应用一", "应用三"])
        self.assertIn("[✓] 应用一", stream.getvalue())
        self.assertIn("空格 勾选", stream.getvalue())
        self.assertIn("┌─ 选择应用", stream.getvalue())
        self.assertIn(BOLD_CYAN, stream.getvalue())
        self.assertIn(GREEN, stream.getvalue())

    def test_multiple_choice_respects_no_color(self):
        stream = FakeTTY()
        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            choose_multiple(
                ["应用一"],
                lambda item: item,
                "选择应用",
                key_reader=lambda: "enter",
                stream=stream,
            )
        self.assertNotIn(BOLD_CYAN, stream.getvalue())
        self.assertNotIn(RESET, stream.getvalue())

    def test_multiple_choice_first_render_keeps_lines_with_color_stream(self):
        wrapped = FakeTTY()
        choose_multiple(
            ["应用一", "应用二", "应用三"],
            lambda item: item,
            "选择应用",
            key_reader=lambda: "enter",
            stream=ColorStream(wrapped),
        )
        plain_output = re.sub(r"\x1b\[[0-9;]*m", "", wrapped.getvalue())
        self.assertIn("│    [ ] 应用二\n│    [ ] 应用三\n└─", plain_output)

    def test_multiple_choice_can_cancel(self):
        selected = choose_multiple(
            ["应用一"],
            lambda item: item,
            "选择应用",
            key_reader=lambda: "cancel",
            stream=FakeTTY(),
        )
        self.assertIsNone(selected)

    @patch(
        "dify_api.terminal.shutil.get_terminal_size",
        return_value=os.terminal_size((80, 6)),
    )
    def test_multiple_choice_scrolls_long_lists(self, _terminal_size):
        keys = iter(["down", "down", "down", "down", "space", "enter"])
        stream = FakeTTY()
        selected = choose_multiple(
            [f"应用{index}" for index in range(1, 7)],
            lambda item: item,
            "选择应用",
            key_reader=lambda: next(keys),
            stream=stream,
        )
        self.assertEqual(selected, ["应用5"])
        self.assertIn("5/6", stream.getvalue())
        self.assertIn("应用5", stream.getvalue())

    def test_multiple_choice_falls_back_to_comma_separated_numbers(self):
        answers = iter(["1,3"])
        selected = choose_multiple(
            ["应用一", "应用二", "应用三"],
            lambda item: item,
            "选择应用",
            stream=StringIO(),
            input_func=lambda _prompt: next(answers),
        )
        self.assertEqual(selected, ["应用一", "应用三"])

    def test_single_choice_binds_arrow_focus_to_number(self):
        keys = iter(["down", "enter"])
        stream = FakeTTY()
        selected = choose_menu(
            "测试菜单",
            [("1", "第一项"), ("2", "第二项"), ("3", "第三项")],
            ("0", "返回"),
            key_reader=lambda: next(keys),
            stream=stream,
        )
        self.assertEqual(selected, "2")
        self.assertIn("当前 [2]", stream.getvalue())

    def test_single_choice_binds_multi_digit_number_to_focus(self):
        keys = iter(["digit:1", "digit:0", "enter"])
        stream = FakeTTY()
        selected = choose_menu(
            "测试菜单",
            [(str(index), f"第 {index} 项") for index in range(1, 13)],
            ("0", "返回"),
            key_reader=lambda: next(keys),
            stream=stream,
        )
        self.assertEqual(selected, "10")
        self.assertIn("当前 [10] · 输入 10", stream.getvalue())

    def test_single_choice_can_focus_numeric_footer(self):
        selected = choose_menu(
            "测试菜单",
            [("1", "第一项"), ("2", "第二项")],
            ("0", "返回"),
            key_reader=iter(["up", "enter"]).__next__,
            stream=FakeTTY(),
        )
        self.assertEqual(selected, "0")

    def test_single_choice_cancel_returns_footer_key(self):
        stream = FakeTTY()
        selected = choose_menu(
            "测试菜单",
            [("1", "第一项")],
            ("0", "返回"),
            key_reader=lambda: "cancel",
            stream=stream,
        )
        self.assertEqual(selected, "0")
        self.assertIn("Q 返回", stream.getvalue())

    def test_single_choice_keeps_numeric_fallback(self):
        selected = choose_menu(
            "测试菜单",
            [("1", "第一项"), ("2", "第二项")],
            ("0", "返回"),
            stream=StringIO(),
            input_func=lambda _prompt: "2",
        )
        self.assertEqual(selected, "2")

    def test_single_choice_first_render_keeps_lines_with_color_stream(self):
        wrapped = FakeTTY()
        choose_menu(
            "测试菜单",
            [("1", "第一项"), ("2", "第二项")],
            ("0", "返回"),
            key_reader=lambda: "enter",
            stream=ColorStream(wrapped),
        )
        plain_output = re.sub(r"\x1b\[[0-9;]*m", "", wrapped.getvalue())
        self.assertIn("│  › [1] 第一项\n│    [2] 第二项\n", plain_output)


if __name__ == "__main__":
    unittest.main()
