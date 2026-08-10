# daily-work

日常工作自动化工具仓库。目前主要包含一套用于查询和监控 **Dify Console** 的 Python 命令行工具。

第一次使用？请直接阅读 [Dify 日志查询工具入门指南](dify/使用指南.md)，按照文档一步一步操作即可。

## 当前功能

`dify/` 目录中的工具可以：

- 查询 Dify 应用列表
- 查看 Workflow 最近运行记录及节点执行详情
- 统计 Workflow 和 Chatflow 的运行量、异常数及 Token 消耗
- 按业务组汇总应用
- 检查指定业务组当天的失败运行
- 将结果输出为便于复制的 Markdown 表格
- 在 Cookie 失效时提示更新认证信息
- 通过 YAML 配置切换 Dify 实例和采集参数

> 本项目调用的是 Dify Console 内部接口，而不是稳定的公开 API。Dify 升级后，接口路径和返回字段可能发生变化。

## 目录结构

```text
daily-work/
├─ README.md
└─ dify/
   ├─ analyze_nezha_apis.py          # 启动入口
   ├─ config.yaml                    # 通用监控配置
   ├─ dify_flow_groups.json          # 应用分组配置
   ├─ nezha_api_response_examples.md # Console API 返回结构示例
   ├─ requirements.txt
   ├─ .env.example
   ├─ nezha_api/
   │  ├─ config.py                   # YAML 配置加载与校验
   │  ├─ settings.py                 # 运行时配置映射
   │  ├─ auth.py                     # Cookie 与 CSRF 认证
   │  ├─ client.py                   # HTTP 请求和分页查询
   │  ├─ flow_groups.py              # 分组和统计周期
   │  ├─ reports.py                  # Token 与运行报告
   │  ├─ monitor.py                  # 失败运行监控
   │  └─ cli.py                      # 命令行入口
   └─ tests/
      ├─ test_config.py
      └─ test_nezha_api.py
```

## 运行环境

建议使用 Python 3.10 或更高版本，以及支持 UTF-8 的终端。

## 安装

```powershell
git clone https://github.com/guihuatang-258/daily-work.git
cd daily-work\dify

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 配置 Dify 实例

编辑 `dify/config.yaml`：

```yaml
instance:
  name: production
  base_url: https://dify.example.com
  timezone: Asia/Shanghai
  workspace_id: 00000000-0000-0000-0000-000000000001

authentication:
  type: cookie

collection:
  apps_page_size: 30
  interactive_log_limit: 10
  token_stats_limit: 20
  monitor_page_size: 100
  token_stats_workers: 10

token_statistics:
  workflow_sample_size: 20

applications:
  groups_file: dify_flow_groups.json
  chat_modes:
    - advanced-chat
    - chat
```

### 当前可配置参数

| 参数 | 说明 |
|---|---|
| `instance.name` | Dify 实例名称 |
| `instance.base_url` | Dify Console 地址 |
| `instance.timezone` | IANA 时区名称 |
| `instance.workspace_id` | 期望使用的 Workspace UUID；不一致时停止运行 |
| `authentication.type` | 认证方式：`cookie` 或 `authorization` |
| `collection.apps_page_size` | 应用列表每页数量 |
| `collection.interactive_log_limit` | 交互查询默认日志数量 |
| `collection.token_stats_limit` | Token 查询每页数量 |
| `collection.monitor_page_size` | 监控分页大小 |
| `collection.token_stats_workers` | Token 统计并发数 |
| `token_statistics.workflow_sample_size` | Workflow Token 估算样本量 |
| `applications.groups_file` | 应用分组文件路径 |
| `applications.chat_modes` | 需要按 Chatflow 处理的应用类型 |

所有正整数参数都会在程序启动时校验。配置文件不存在时，程序使用内置默认值，以兼容旧版运行方式。

`workspace_id` 留空时跳过 Workspace 校验。建议多 Workspace 账号务必填写，防止网页切换 Workspace 后查询到另一套应用。可以在浏览器开发者工具的 Network 面板查看 `/console/api/workspaces` 响应，找到 `current: true` 对象的 `id`。

### 使用其他配置文件

通过环境变量指定配置文件：

```powershell
$env:DIFY_MONITOR_CONFIG = "C:\configs\dify-test.yaml"
python analyze_nezha_apis.py
```

这样可以为生产、测试和不同客户实例分别保存配置，而不修改代码。

## 配置认证信息

```powershell
Copy-Item .env.example .env
```

先根据目标 Dify 实例使用的认证方式编辑 `config.yaml`：

```yaml
authentication:
  type: cookie # 或 authorization
```

Cookie 认证编辑 `.env`：

```env
NEZHA_COOKIE="粘贴浏览器请求中的完整 Cookie"
```

Cookie 必须包含 `__Host-csrf_token`。程序会自动将该值作为 `X-CSRF-Token` 请求头。

Authorization 认证编辑 `.env`：

```env
DIFY_AUTHORIZATION="粘贴浏览器请求中的完整 Authorization 值"
```

例如浏览器请求头是 `Authorization: Bearer eyJ...`，应保存 `Bearer eyJ...`。程序会原样发送该值，不会自动添加 `Bearer`。

获取方式：在已登录 Dify Console 的浏览器中打开开发者工具，在 Network 面板选择 `/console/api/` 请求，然后从 Request Headers 中复制对应的完整 Cookie 或 Authorization 值。

> `.env` 包含登录凭证，严禁提交到仓库或发送给其他人。

## 配置应用分组

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

`mode` 当前主要支持 `workflow`、`advanced-chat` 和 `chat`。也可以在 `config.yaml` 的 `applications.chat_modes` 中扩展 Chat 类应用类型。

## 使用方式

### 交互模式

```powershell
python analyze_nezha_apis.py
```

### 检查指定业务组当天的失败运行

```powershell
python analyze_nezha_apis.py --check-failures coach
```

同时检查多个组：

```powershell
python analyze_nezha_apis.py --check-failures coach knowledge_search isa summary
```

业务组参数取自分组文件中 `groups` 对象的键。

## Token 统计说明

Chatflow 会按会话和消息数据统计 Token。部分 Workflow 接口不能直接提供完整 Token 汇总，因此程序会抽样运行记录进行估算。输出中带 `~` 的数字表示估算值。

可通过以下配置调整抽样量和并发：

```yaml
token_statistics:
  workflow_sample_size: 20

collection:
  token_stats_workers: 10
```

请求过多或平台压力较大时，应降低并发数。

## 运行测试

```powershell
python -m unittest discover -s tests -v
```

测试使用离线模拟数据，不应请求真实 Console API。

## 常见问题

- **Cookie 或 Authorization 已过期：** 按 `authentication.type` 对应的方式重新复制认证值并更新 `.env`。
- **缺少 `__Host-csrf_token`：** 当前 Cookie 不完整或来源请求不正确。
- **HTTP 401/403：** 认证值过期、认证方式不匹配或账号没有权限。
- **当前 Workspace 与配置不一致：** 在 Dify 网页切回提示的 Workspace，再重新运行程序。
- **HTTP 429：** 请求频率过高，应降低并发或稍后重试。
- **配置时区报错：** 使用有效的 IANA 时区，例如 `Asia/Shanghai`、`Asia/Taipei`。
- **统计数字带 `~`：** 该结果由抽样数据估算，并非精确总量。

## 安全注意事项

- 不要提交 `.env`、Cookie、Token 或其他登录凭证。
- 仓库公开前，应检查分组文件中的内部应用名称和应用 ID。
- 无人值守任务使用浏览器 Cookie 存在过期风险，应做好认证失败告警。

## 下一阶段

- 将请求超时、重试和退避策略配置化
- 将失败次数、失败率和 Token 异常阈值配置化
- 支持 JSON、CSV、HTML 和 Prometheus 输出
- 增加飞书、企业微信等告警渠道
- 把 Console API 路径和字段解析拆成版本适配器
