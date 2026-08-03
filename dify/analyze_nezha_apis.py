"""哪吒 Dify API 查询工具的兼容启动入口。"""

from nezha_api.cli import main
from nezha_api.terminal import install_terminal_theme


if __name__ == "__main__":
    install_terminal_theme()
    raise SystemExit(main())
