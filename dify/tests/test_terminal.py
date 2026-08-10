"""终端配色行为测试。"""

import os
import unittest
from io import StringIO
from unittest.mock import patch

from dify_api.terminal import (
    BOLD_CYAN,
    CYAN,
    GREEN,
    RED,
    RESET,
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


if __name__ == "__main__":
    unittest.main()
