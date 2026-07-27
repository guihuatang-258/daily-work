# daily-work

日常工作自动化工具仓库。目前主要包含一套用于查询和监控 **哪吒平台 Dify Console** 的 Python 命令行工具。

## 当前功能

`dify/` 目录中的工具可以：

- 查询 Dify 应用列表
- 查看 Workflow 最近运行记录
- 查看单次 Workflow 及节点执行详情
- 统计 Workflow 和 Chatflow 的运行量及 Token 消耗
- 按业务组汇总 Coach、KS、ISA、小结组等应用
- 检查指定 Flow 组当天的失败运行
- 将结果输出为便于复制的 Markdown 表格
- 在 Cookie 失效时提示更新认证信息

> 本项目调用的是 Dify Console 内部接口，而不是稳定的公开 API。Dify 或哪吒平台升级后，接口路径和返回字段可能发生变化。

## 目录结构

```text
daily-work/
├─ README.md
├─ .gitignore
└─ dify/
   ├─ analyze_nezha_apis.py          # 兼容启动入口
   ├─ dify_flow_groups.json          # 业务应用分组配置
   ├─ nezha_api_response_examples.md # Console API 返回结构示例
   ├─ requirements.txt               # Python 依赖
   ├─ .env.example                   # 环境变量模板
   ├─ nezha_api/
   │  ├─ auth.py                     # Cookie 与 CSRF 认证
   │  ├─ cli.py                      # 命令行入口和交互菜单
   │  ├─ client.py                   # HTTP 请求和分页查询
   │  ├─ flow_groups.py              # 分组配置和统计周期
   │  ├─ markdown.py                 # Markdown 输出组件
   │  ├─ monitor.py                  # 失败运行监控
   │  ├─ progress.py                 # 终端进度显示
   │  ├─ reports.py                  # Token 与运行报告
   │  └─ settings.py                 # 默认配置
   └─ tests/
      └─ test_nezha_api.py           # 离线单元测试
```

## 运行环境

建议使用：

- Python 3.10 或更高版本
- Windows PowerShell 或其他支持 UTF-8 的终端
- 能够访问哪吒平台的网络环境
- 已登录哪吒 Dify Console 的浏览器会话

## 安装

克隆仓库：

```powershell
git clone https://github.com/guihuatang-258/daily-work.git
cd daily-work\dify
```

创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 配置认证信息

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```env
NEZHA_COOKIE="粘贴浏览器请求中的完整 Cookie"
```

Cookie 中必须包含：

```text
__Host-csrf_token
```

程序会自动读取该字段，并将其作为 `X-CSRF-Token` 请求头。

### 获取 Cookie

1. 在浏览器中登录哪吒平台。
2. 打开开发者工具。
3. 切换到 Network（网络）面板。
4. 刷新 Dify 应用管理页面。
5. 选择一个发往 `/console/api/` 的请求。
6. 在 Request Headers 中复制完整的 `Cookie` 值。
7. 将其写入 `dify/.env` 的 `NEZHA_COOKIE`。

> `.env` 包含登录凭证，严禁提交到 Git 仓库或发送给其他人。

## 使用方式

### 交互模式

```powershell
python analyze_nezha_apis.py
```

程序会先验证 Cookie，然后显示交互菜单。可在菜单中选择应用、业务组、统计周期或失败检查功能。

### 检查指定业务组当天的失败运行

```powershell
python analyze_nezha_apis.py --check-failures coach
```

同时检查多个组：

```powershell
python analyze_nezha_apis.py --check-failures coach knowledge_search isa summary
```

业务组名称取自 `dify_flow_groups.json` 中 `groups` 对象的键，而不是界面显示名称。

当前配置包含：

| 参数 | 显示名称 |
|---|---|
| `coach` | Coach 组 |
| `knowledge_search` | KS 组 |
| `isa` | ISA 组 |
| `summary` | 小结组 |

失败检查成功完成时退出码为 `0`；认证或请求无法完成时退出码为 `2`。

## 新增或调整应用分组

编辑 `dify_flow_groups.json`：

```json
{
  "groups": {
    "example": {
      "display_name": "示例组",
      "apps": [
        {
          "name": "示例应用",
          "app_id": "Dify 应用 UUID",
          "mode": "workflow"
        }
      ]
    }
  }
}
```

`mode` 当前主要支持：

- `workflow`
- `advanced-chat`
- `chat`

Workflow 和 Chatflow 使用不同的 Console API 与 Token 统计逻辑，请按实际应用类型填写。

## Token 统计说明

Chatflow 会按会话和消息数据统计 Token。

部分 Workflow 列表接口不能直接提供完整 Token 汇总，因此程序可能通过抽样运行记录进行估算。输出中带 `~` 的数字表示估算值，例如：

```text
~301154
```

相关默认参数位于 `dify/nezha_api/settings.py`：

```python
TOKEN_STATS_WORKERS = 10
WORKFLOW_TOKEN_SAMPLE_SIZE = 20
MONITOR_PAGE_LIMIT = 100
```

请求过多或平台压力较大时，可以适当降低并发数。

## 运行测试

在 `dify/` 目录执行：

```powershell
python -m unittest discover -s tests -v
```

测试使用离线模拟数据，不应请求真实 Console API。

## 常见问题

### 提示 Cookie 或 Token 已过期

重新从浏览器开发者工具复制完整 Cookie，并更新 `.env` 中的 `NEZHA_COOKIE`。

### 提示缺少 `__Host-csrf_token`

复制的 Cookie 不完整。请确认来源是已经登录的平台请求，并复制完整的 Request Headers Cookie。

### 请求返回 401 或 403

通常表示 Cookie 过期、CSRF Token 不匹配或当前账号没有对应权限。

### 请求返回 429

表示请求频率过高。降低并发数或稍后重新执行。

### 统计结果带 `~`

代表该结果由抽样数据估算，不是精确总量。

## 安全注意事项

- 不要提交 `.env`、Cookie、Token 或其他登录凭证。
- 不要在日志、截图和聊天消息中暴露完整 Cookie。
- 仓库公开前，应检查 `dify_flow_groups.json` 中的内部应用名称和应用 ID 是否适合公开。
- 无人值守任务使用浏览器 Cookie 存在过期风险，应做好认证失败告警。

## 后续改进方向

- 增加统一的 `pyproject.toml` 和可安装命令
- 为网络异常和 429 增加重试及退避机制
- 支持导出 JSON、CSV 和 Markdown 文件
- 增加企业微信或飞书失败告警
- 增加定时任务配置示例
- 尽可能替换为稳定的官方 API 或服务账号认证
