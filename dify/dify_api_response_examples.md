# Dify Console API 返回结构示例

本文档整理 `main.py` 当前使用的 API。示例已脱敏，字段值仅用于说明结构。

> 这些接口属于 Dify Console 内部接口，并非稳定的公开 API。升级 Dify 或部署平台后，字段可能增加、缺省或调整。

## 1. 公共约定

### 1.1 基础地址

```text
https://dify.example.com
```

### 1.2 认证请求头

```http
Cookie: <完整浏览器 Cookie>
X-CSRF-Token: <Cookie 中的 __Host-csrf_token>
Accept: application/json
Referer: https://dify.example.com/console/apps
```

### 1.3 常见字段格式

| 字段 | 格式 | 说明 |
|---|---|---|
| `app_id` | UUID | 应用 ID |
| `run_id` | UUID | Workflow 运行 ID |
| `conversation_id` | UUID | Chatflow 会话 ID |
| `created_at` | Unix 时间戳 | 单位通常为秒 |
| `total_tokens` | 整数 | 输入与输出 Token 总数 |
| `total_price` | 字符串 | 费用，计算时应转换为数值 |
| `currency` | 字符串 | 当前环境通常为 `RMB` |

### 1.4 通用分页结构

列表接口通常返回：

```json
{
  "page": 1,
  "limit": 100,
  "total": 2535,
  "has_more": true,
  "data": []
}
```

部分接口只返回 `limit`、`has_more` 和 `data`，不一定包含 `page` 或 `total`。

### 1.5 Workspace 列表与当前 Workspace

脚本在认证成功后会先调用此接口，确认 Dify 服务端当前选中的 Workspace，避免使用另一个 Workspace 的应用 ID 发起查询。

#### 请求

```http
GET /console/api/workspaces
```

该接口不需要查询参数，认证方式与其他 Console API 相同。

#### 返回示例

以下 ID 和名称均为脱敏示例：

```json
{
  "workspaces": [
    {
      "id": "00000000-0000-0000-0000-000000000001",
      "name": "示例 Workspace A",
      "plan": "sandbox",
      "status": "normal",
      "created_at": 1780000000,
      "current": false
    },
    {
      "id": "00000000-0000-0000-0000-000000000002",
      "name": "示例 Workspace B",
      "plan": "sandbox",
      "status": "normal",
      "created_at": 1780000100,
      "current": true
    }
  ]
}
```

#### 关键字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `workspaces[].id` | string | Workspace 的唯一 ID |
| `workspaces[].name` | string | Workspace 名称 |
| `workspaces[].current` | boolean | 是否为网页当前选中的 Workspace |
| `workspaces[].status` | string | Workspace 当前状态 |
| `workspaces[].plan` | string | Workspace 使用的套餐 |

#### 如何取得并配置 Workspace ID

1. 在浏览器中打开对应的 Dify 控制台，并切换到需要统计的 Workspace。
2. 按 `F12` 打开开发者工具，进入“网络（Network）”。
3. 刷新页面，找到 `GET /console/api/workspaces` 请求。
4. 在响应中的 `workspaces` 数组里找到 `current: true` 的对象。
5. 复制该对象的 `id`，填入 `config.yaml`：

```yaml
instance:
  workspace_id: "00000000-0000-0000-0000-000000000002"
```

脚本会比较配置的 `workspace_id` 与接口返回的当前 Workspace ID。两者一致才继续查询；不一致时会停止，提示先切换 Workspace。网页切换 Workspace 后，同一应用列表接口返回的 Workflow/Chatflow 也会随之变化，因为 Console API 会按服务端当前 Workspace 过滤数据。

> 当前兼容方案使用 `GET /console/api/workspaces` 返回的 `current` 字段判断当前 Workspace，不使用 `GET /console/api/workspaces/current`；后者在部分部署中不支持 GET 请求并会返回 `405 Method Not Allowed`。

## 2. 应用列表

### 2.1 请求

```http
GET /console/api/apps?page=1&limit=30&name=
```

### 2.2 查询参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | integer | 页码，从 `1` 开始 |
| `limit` | integer | 每页条数 |
| `name` | string | 名称过滤；当前脚本也会在本地二次过滤 |

### 2.3 返回示例

```json
{
  "page": 1,
  "limit": 30,
  "total": 30,
  "has_more": false,
  "data": [
    {
      "id": "e61efb5b-fd94-492e-8418-335bda35cdc9",
      "name": "Coach-质检打分（生产）",
      "mode": "workflow",
      "workflow_id": null
    },
    {
      "id": "92e1ad51-a4b0-4757-b2a7-d722deed0a56",
      "name": "【私教】Coach2.0-问答交互",
      "mode": "advanced-chat",
      "workflow_id": null
    }
  ]
}
```

### 2.4 关键字段

| JSON 路径 | 说明 |
|---|---|
| `data[].id` | 后续请求使用的 `app_id` |
| `data[].name` | 应用显示名称 |
| `data[].mode` | 常见值为 `workflow`、`chat`、`advanced-chat` |
| `data[].workflow_id` | 部分环境或应用可能为 `null` |

认证启动校验也使用该接口，只请求一条数据。

## 3. Workflow 日志列表

### 3.1 请求

```http
GET /console/api/apps/{app_id}/workflow-app-logs
    ?page=1
    &detail=true
    &limit=100
    &created_at__after=2026-07-20T00%3A00%3A00%2B08%3A00
    &created_at__before=2026-07-20T23%3A59%3A59%2B08%3A00
```

### 3.2 查询参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | integer | 页码 |
| `limit` | integer | 当前环境实测最大支持 `100` |
| `detail` | boolean | 是否返回详情 |
| `created_at__after` | ISO 8601 | 起始时间，包含 `+08:00` 时区 |
| `created_at__before` | ISO 8601 | 截止时间，包含 `+08:00` 时区 |

### 3.3 返回示例

```json
{
  "page": 1,
  "limit": 100,
  "total": 2535,
  "has_more": true,
  "data": [
    {
      "id": "log-id-placeholder",
      "workflow_run": {
        "id": "a5ee007b-6347-4228-be79-af56ee926bc4",
        "version": "2026-07-20 10:00:00.000000",
        "status": "succeeded",
        "triggered_from": "service-api",
        "error": null,
        "elapsed_time": 2.748643,
        "total_tokens": 1422,
        "total_steps": 5,
        "created_at": 1784541761,
        "finished_at": 1784541764,
        "exceptions_count": 0
      },
      "details": {
        "trigger_metadata": {}
      },
      "created_from": "service-api",
      "created_by_role": "end_user",
      "created_by_account": null,
      "created_by_end_user": {
        "id": "end-user-id-placeholder",
        "type": "service-api",
        "is_anonymous": false,
        "session_id": "session-id-placeholder"
      },
      "created_at": 1784541761
    }
  ]
}
```

### 3.4 关键字段

| JSON 路径 | 说明 |
|---|---|
| `total` | 时间范围内的运行总数 |
| `data[].workflow_run.id` | `run_id` |
| `data[].workflow_run.status` | 运行状态，例如 `succeeded`、`failed` |
| `data[].workflow_run.total_tokens` | 准确的运行总 Token |
| `data[].workflow_run.elapsed_time` | 运行耗时，单位为秒 |
| `data[].workflow_run.error` | 失败信息，成功时通常为 `null` |

该接口只直接提供 `total_tokens`，不提供 input/output 拆分。

## 4. Workflow 单次运行详情

### 4.1 请求

```http
GET /console/api/apps/{app_id}/workflow-runs/{run_id}
```

### 4.2 返回示例

```json
{
  "id": "a5ee007b-6347-4228-be79-af56ee926bc4",
  "version": "2026-07-20 10:00:00.000000",
  "graph": {
    "nodes": [
      {
        "id": "start-node-id",
        "data": {
          "type": "start",
          "title": "开始"
        }
      },
      {
        "id": "llm-node-id",
        "data": {
          "type": "llm",
          "title": "质检打分"
        }
      }
    ],
    "edges": []
  },
  "inputs": {
    "sys.user_id": "business-user-id",
    "sys.app_id": "app-id-placeholder",
    "sys.workflow_id": "workflow-id-placeholder",
    "sys.workflow_run_id": "run-id-placeholder",
    "ruleName": "服务态度"
  },
  "status": "succeeded",
  "outputs": {
    "result": "业务输出内容"
  },
  "error": null,
  "elapsed_time": 2.748643,
  "total_tokens": 1422,
  "total_steps": 5,
  "created_by_role": "end_user",
  "created_by_account": null,
  "created_by_end_user": {
    "id": "end-user-id-placeholder",
    "type": "service-api",
    "is_anonymous": false,
    "session_id": "session-id-placeholder"
  },
  "created_at": 1784541761,
  "finished_at": 1784541764,
  "exceptions_count": 0
}
```

### 4.3 注意事项

- `inputs` 和 `outputs` 完全由 Workflow 定义决定。
- `graph` 可能较大，包含完整节点和连线配置。
- `sys.user_id`、`ruleName` 等字段不是所有 Workflow 都存在。
- `total_tokens` 是运行总量，但该接口同样不保证提供 input/output 拆分。

## 5. Workflow 节点执行详情

### 5.1 请求

```http
GET /console/api/apps/{app_id}/workflow-runs/{run_id}/node-executions
```

### 5.2 返回示例

不同版本可能直接返回数组，也可能使用 `data` 包裹：

```json
{
  "data": [
    {
      "id": "node-execution-id",
      "node_id": "llm-node-id",
      "node_type": "llm",
      "title": "质检打分",
      "index": 4,
      "predecessor_node_id": null,
      "inputs": {},
      "process_data": {
        "model_mode": "chat",
        "prompts": [
          {
            "role": "system",
            "text": "系统提示词",
            "files": []
          },
          {
            "role": "user",
            "text": "用户提示词",
            "files": []
          }
        ]
      },
      "outputs": {
        "text": "模型输出",
        "finish_reason": "stop",
        "usage": {
          "prompt_tokens": 1339,
          "completion_tokens": 83,
          "total_tokens": 1422,
          "prompt_unit_price": "0.0008",
          "completion_unit_price": "0.0048",
          "total_price": "0.0014696",
          "currency": "RMB",
          "latency": 2.507,
          "time_to_first_token": 1.074,
          "time_to_generate": 1.433
        }
      },
      "status": "succeeded",
      "error": null,
      "elapsed_time": 2.512884,
      "execution_metadata": {
        "total_tokens": 1422,
        "total_price": "0.0014696",
        "currency": "RMB"
      },
      "inputs_truncated": false,
      "outputs_truncated": false,
      "process_data_truncated": false,
      "created_at": 1784541761,
      "finished_at": 1784541764
    }
  ]
}
```

### 5.3 Token 字段

仅对 `node_type == "llm"` 的节点统计：

| JSON 路径 | 说明 |
|---|---|
| `outputs.usage.prompt_tokens` | LLM 输入 Token |
| `outputs.usage.completion_tokens` | LLM 输出 Token |
| `outputs.usage.total_tokens` | 该 LLM 节点总 Token |
| `execution_metadata.total_tokens` | 节点总 Token 的简化字段 |
| `execution_metadata.total_price` | 节点费用 |

一次 Workflow 可能包含多个 LLM 节点，需要对全部 LLM 节点求和。

## 6. Chatflow 会话列表

### 6.1 请求

```http
GET /console/api/apps/{app_id}/chat-conversations
    ?page=1
    &limit=100
    &start=2026-07-20%2000%3A00
    &end=2026-07-20%2023%3A59
    &sort_by=-created_at
    &annotation_status=all
```

### 6.2 查询参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | integer | 页码 |
| `limit` | integer | 每页会话数 |
| `start` | string | 起始时间，格式为 `YYYY-MM-DD HH:mm` |
| `end` | string | 截止时间，格式为 `YYYY-MM-DD HH:mm` |
| `sort_by` | string | 当前使用 `-created_at` |
| `annotation_status` | string | 当前使用 `all` |

### 6.3 返回示例

```json
{
  "page": 1,
  "limit": 100,
  "total": 257,
  "has_more": true,
  "data": [
    {
      "id": "15df83b2-73ba-4e61-8c12-1e3411c164d8",
      "name": "会话摘要",
      "summary": "会话摘要内容",
      "status": "normal",
      "message_count": 1,
      "from_source": "api",
      "from_end_user_id": "end-user-id-placeholder",
      "from_end_user_session_id": "session-id-placeholder",
      "from_account_id": null,
      "from_account_name": null,
      "model_config": {},
      "annotated": false,
      "admin_feedback_stats": {},
      "user_feedback_stats": {},
      "status_count": {},
      "created_at": 1784541000,
      "updated_at": 1784541100,
      "read_at": null
    }
  ]
}
```

会话列表本身不提供 Token，需要继续查询会话消息。

## 7. Chatflow 消息列表

### 7.1 请求

```http
GET /console/api/apps/{app_id}/chat-messages
    ?conversation_id={conversation_id}
    &limit=100
    &first_id={first_message_id}
```

首次请求不传 `first_id`；当 `has_more == true` 时，使用当前页第一条消息 ID 继续向前分页。

### 7.2 返回示例

```json
{
  "limit": 100,
  "has_more": false,
  "data": [
    {
      "id": "message-id-placeholder",
      "conversation_id": "conversation-id-placeholder",
      "inputs": {},
      "query": "用户问题",
      "message": null,
      "message_tokens": 20,
      "answer": "模型回答",
      "answer_tokens": 14,
      "provider_response_latency": 1.194,
      "from_source": "api",
      "from_end_user_id": "end-user-id-placeholder",
      "from_account_id": null,
      "feedbacks": [],
      "workflow_run_id": "50f8695f-03ac-40c6-8a4b-2dcab0081541",
      "annotation": null,
      "annotation_hit_history": null,
      "created_at": 1784541000,
      "agent_thoughts": [],
      "message_files": [],
      "extra_contents": [],
      "metadata": {
        "retriever_resources": [],
        "annotation_reply": null,
        "usage": {
          "prompt_tokens": 686,
          "completion_tokens": 14,
          "total_tokens": 700,
          "prompt_unit_price": "0.0008",
          "prompt_price_unit": "0.001",
          "prompt_price": "0.0005488",
          "completion_unit_price": "0.0048",
          "completion_price_unit": "0.001",
          "completion_price": "0.0000672",
          "total_price": "0.000616",
          "currency": "RMB",
          "latency": 1.194,
          "time_to_first_token": 1.533,
          "time_to_generate": 0.0
        }
      },
      "status": "normal",
      "error": null,
      "parent_message_id": null
    }
  ]
}
```

### 7.3 Token 字段

| JSON 路径 | 说明 |
|---|---|
| `data[].metadata.usage.prompt_tokens` | 输入 Token |
| `data[].metadata.usage.completion_tokens` | 输出 Token |
| `data[].metadata.usage.total_tokens` | 总 Token |
| `data[].metadata.usage.total_price` | 消息费用 |
| `data[].workflow_run_id` | 该消息关联的 Workflow 运行 ID |

Chatflow 可以直接从消息 usage 精确汇总 input、output 和 total，无需逐个请求节点详情。

## 8. API 调用关系

所有查询在认证成功后，都会先调用 `GET /console/api/workspaces`，将 `current: true` 的 Workspace ID 与 `config.yaml` 中的 `instance.workspace_id` 比较。校验通过后才进入下面的应用和日志查询流程。

### 8.1 Workflow

```text
应用列表
  └─ workflow-app-logs
       ├─ workflow-runs/{run_id}
       └─ workflow-runs/{run_id}/node-executions
```

### 8.2 Chatflow

```text
应用列表
  └─ chat-conversations
       └─ chat-messages
            └─ workflow_run_id（需要时可继续查询节点详情）
```

## 9. 当前脚本的统计字段来源

| 统计项 | 数据来源 | 精确性 |
|---|---|---|
| Workflow 运行数 | `workflow-app-logs.total` 或全部分页条数 | 精确 |
| Workflow total tokens | `workflow_run.total_tokens` | 精确 |
| Workflow input/output | 均匀抽样 run 的 `node-executions[].outputs.usage` 后按比例估算 | 估算 |
| Chatflow 会话数 | `chat-conversations` 全部分页 | 精确 |
| Chatflow input/output/total | `chat-messages[].metadata.usage` | 精确 |
| 异常 Workflow 数 | `workflow_run.status != "succeeded"` | 精确 |
| 异常 Chatflow 消息数 | 消息 `status` 不属于正常状态集合 | 精确 |

## 10. 常见错误响应

Console API 的错误响应结构可能因网关而异，脚本主要根据 HTTP 状态码处理：

| HTTP 状态 | 含义 | 脚本行为 |
|---|---|---|
| `400` | 参数不合法，例如 `limit` 超过后端上限 | 打印请求失败 |
| `401` | Cookie 或 Token 已过期 | 提示更新认证信息 |
| `403` | CSRF 校验失败或无权限 | 启动认证校验判定为失效 |
| `404` | 应用 ID 不属于当前 Workspace，或请求路径在该部署中不存在 | 打印请求失败 |
| `429` | 请求过于频繁 | 当前打印失败；应降低并发或增加重试 |
| `5xx` | 服务端或网关异常 | 当前打印失败，不覆盖认证配置 |

Workspace 配置不一致通常不会表现为 HTTP 错误：脚本会在请求应用日志前主动停止，并显示当前 Workspace 与配置 Workspace 的名称和 ID，避免后续接口返回容易误解的 `404`。
