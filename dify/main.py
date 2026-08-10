"""通用 Dify Console API 查询工具启动入口。"""

from dify_api.cli import main
from dify_api.terminal import install_terminal_theme


if __name__ == "__main__":
    install_terminal_theme()
    raise SystemExit(main())
