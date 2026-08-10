"""Token 用量读取、采样和聚合。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

from .client import (
    get_chat_messages,
    get_node_executions,
    list_all_chat_conversations_in_range,
    list_all_workflow_logs_in_range,
)
from .progress import format_progress
from .settings import (
    CHAT_APP_MODES,
    MONITOR_PAGE_LIMIT,
    TOKEN_STATS_WORKERS,
    WORKFLOW_TOKEN_SAMPLE_SIZE,
)


def get_item_id(
    item: dict, id_keys: tuple[str, ...] = ("id", "conversation_id")
) -> str | None:
    for key in id_keys:
        if item.get(key):
            return str(item[key])
    return None


def token_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def get_chat_conversation_usage_from_messages(
    headers: dict,
    app_id: str,
    conversation_id: str,
    limit: int = MONITOR_PAGE_LIMIT,
) -> tuple[int, int, int, int, bool]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    failed_messages = 0
    complete = True
    first_id: str | None = None
    seen_message_ids: set[str] = set()
    while True:
        _, data = get_chat_messages(
            headers,
            app_id=app_id,
            conversation_id=conversation_id,
            limit=limit,
            first_id=first_id,
        )
        if data is None:
            complete = False
            break
        messages = data.get("data", [])
        new_messages = []
        for message in messages:
            message_id = str(message.get("id") or "")
            if message_id and message_id in seen_message_ids:
                continue
            if message_id:
                seen_message_ids.add(message_id)
            new_messages.append(message)
        for message in new_messages:
            usage = (message.get("metadata") or {}).get("usage") or {}
            message_input = token_int(
                usage.get("prompt_tokens", message.get("message_tokens"))
            )
            message_output = token_int(
                usage.get("completion_tokens", message.get("answer_tokens"))
            )
            message_total = usage.get("total_tokens")
            input_tokens += message_input
            output_tokens += message_output
            total_tokens += (
                token_int(message_total)
                if message_total is not None
                else message_input + message_output
            )
            status = str(message.get("status") or "").lower()
            if status and status not in {
                "normal", "success", "succeeded", "completed"
            }:
                failed_messages += 1
        if not data.get("has_more") or not messages:
            break
        next_first_id = get_item_id(messages[0])
        if not next_first_id or next_first_id == first_id or not new_messages:
            complete = False
            break
        first_id = next_first_id
    return input_tokens, output_tokens, total_tokens, failed_messages, complete


def get_workflow_run_token_breakdown(
    headers: dict, app_id: str, run_id: str
) -> tuple[int, int, int] | None:
    _, data = get_node_executions(headers, app_id, run_id)
    if not data:
        return None
    nodes = data if isinstance(data, list) else data.get("data", [])
    input_tokens = output_tokens = total_tokens = 0
    for node in nodes:
        if node.get("node_type") != "llm":
            continue
        metadata = node.get("execution_metadata") or {}
        usage = (node.get("outputs") or {}).get("usage") or {}
        node_input = token_int(
            usage.get(
                "prompt_tokens",
                metadata.get("prompt_tokens", metadata.get("input_tokens")),
            )
        )
        node_output = token_int(
            usage.get(
                "completion_tokens",
                metadata.get("completion_tokens", metadata.get("output_tokens")),
            )
        )
        node_total = usage.get("total_tokens", metadata.get("total_tokens"))
        input_tokens += node_input
        output_tokens += node_output
        total_tokens += (
            token_int(node_total)
            if node_total is not None
            else node_input + node_output
        )
    return input_tokens, output_tokens, total_tokens


def evenly_sample_workflow_runs(
    logs: list[dict], sample_size: int = WORKFLOW_TOKEN_SAMPLE_SIZE
) -> list[tuple[str, dict]]:
    candidates = []
    for item in logs:
        workflow_run = item.get("workflow_run") or {}
        run_id = workflow_run.get("id") or item.get("id")
        if run_id:
            candidates.append((str(run_id), item))
    if sample_size <= 0 or not candidates:
        return []
    if len(candidates) <= sample_size:
        return candidates
    if sample_size == 1:
        return [candidates[len(candidates) // 2]]
    indexes = {
        round(index * (len(candidates) - 1) / (sample_size - 1))
        for index in range(sample_size)
    }
    return [candidates[index] for index in sorted(indexes)]


def collect_flow_group_token_stats(
    headers: dict, apps: list[dict], start: datetime, end: datetime
) -> list[dict]:
    stats_by_app: dict[str, dict] = {}
    workflow_logs_by_app: dict[str, list[dict]] = {}
    chat_conversations_by_app: dict[str, list[dict]] = {}
    progress_lock = Lock()

    def load_app_records(app: dict) -> tuple[dict, list[dict], bool]:
        app_id = app["app_id"]
        app_name = app.get("name") or app_id
        mode = app.get("mode") or "workflow"

        def show_page_progress(
            page: int, total_pages: int, loaded: int, total: int
        ) -> None:
            record_label = "会话" if mode in CHAT_APP_MODES else "运行"
            with progress_lock:
                print(
                    f"  {format_progress(loaded, total)} · "
                    f"[{app_name}] 第 {page}/{total_pages} 页"
                    f"（{record_label}）"
                )

        if mode in CHAT_APP_MODES:
            records, complete = list_all_chat_conversations_in_range(
                dict(headers), app_id, start, end,
                progress_callback=show_page_progress,
            )
        else:
            records, complete = list_all_workflow_logs_in_range(
                dict(headers), app_id, start, end,
                progress_callback=show_page_progress,
            )
        return app, records, complete

    print(
        f"正在读取分组内 {len(apps)} 个应用的运行记录 "
        f"(并发 {TOKEN_STATS_WORKERS})..."
    )
    with ThreadPoolExecutor(max_workers=TOKEN_STATS_WORKERS) as pool:
        futures = {pool.submit(load_app_records, app): app for app in apps}
        for done, future in enumerate(as_completed(futures), start=1):
            app = futures[future]
            app_id = app["app_id"]
            try:
                _, records, complete = future.result()
            except Exception:
                records, complete = [], False
            stats = {
                "app_id": app_id,
                "name": app.get("name") or app_id,
                "mode": app.get("mode") or "workflow",
                "records": len(records),
                "success": 0,
                "failed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "complete": complete,
                "data_available": complete or bool(records),
                "io_available": (app.get("mode") or "workflow")
                in CHAT_APP_MODES,
                "io_estimated": False,
                "sampled_runs": 0,
                "sample_target": 0,
            }
            if stats["mode"] in CHAT_APP_MODES:
                chat_conversations_by_app[app_id] = records
            else:
                workflow_logs_by_app[app_id] = records
                for item in records:
                    workflow_run = item.get("workflow_run") or {}
                    stats["total_tokens"] += token_int(
                        workflow_run.get("total_tokens")
                    )
                    if workflow_run.get("status") == "succeeded":
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
            stats_by_app[app_id] = stats
            with progress_lock:
                state = "完成" if complete else "数据不完整"
                print(
                    f"  {format_progress(done, len(apps))} · "
                    f"{stats['name']}：记录读取{state}"
                )

    sample_tasks = []
    for app_id, logs in workflow_logs_by_app.items():
        samples = evenly_sample_workflow_runs(logs)
        stats_by_app[app_id]["sample_target"] = len(samples)
        sample_tasks.extend((app_id, run_id) for run_id, _ in samples)
    if sample_tasks:
        print(
            f"正在抽样 {len(sample_tasks)} 条 Workflow 运行估算 input/output "
            f"(每个 Flow 最多 {WORKFLOW_TOKEN_SAMPLE_SIZE} 条，并发 "
            f"{TOKEN_STATS_WORKERS})..."
        )
        sample_sums = {
            app_id: {"input": 0, "output": 0, "total": 0, "done": 0}
            for app_id in workflow_logs_by_app
        }
        with ThreadPoolExecutor(max_workers=TOKEN_STATS_WORKERS) as pool:
            futures = {
                pool.submit(
                    get_workflow_run_token_breakdown,
                    dict(headers), app_id, run_id,
                ): app_id
                for app_id, run_id in sample_tasks
            }
            for future in as_completed(futures):
                app_id = futures[future]
                sample = sample_sums[app_id]
                sample["done"] += 1
                try:
                    breakdown = future.result()
                    if breakdown is not None:
                        input_tokens, output_tokens, total_tokens = breakdown
                        if input_tokens + output_tokens > 0:
                            sample["input"] += input_tokens
                            sample["output"] += output_tokens
                            sample["total"] += total_tokens
                            stats_by_app[app_id]["sampled_runs"] += 1
                except Exception:
                    pass
                target = stats_by_app[app_id]["sample_target"]
                step = max(1, target // 4)
                if sample["done"] == target or sample["done"] % step == 0:
                    with progress_lock:
                        print(
                            f"  {format_progress(sample['done'], target)} · "
                            f"{stats_by_app[app_id]['name']}：Workflow 比例采样"
                        )
        for app_id, sample in sample_sums.items():
            stats = stats_by_app[app_id]
            sample_io_tokens = sample["input"] + sample["output"]
            if stats["total_tokens"] == 0:
                stats["io_available"] = True
            elif sample_io_tokens > 0:
                input_ratio = sample["input"] / sample_io_tokens
                estimated_input = round(stats["total_tokens"] * input_ratio)
                stats["input_tokens"] = estimated_input
                stats["output_tokens"] = stats["total_tokens"] - estimated_input
                stats["io_available"] = True
                stats["io_estimated"] = True

    conversation_tasks = [
        (app_id, get_item_id(conversation))
        for app_id, conversations in chat_conversations_by_app.items()
        for conversation in conversations
        if get_item_id(conversation)
    ]
    if conversation_tasks:
        print(
            f"正在统计 {len(conversation_tasks)} 条 Chatflow 会话消息 Token "
            f"(并发 {TOKEN_STATS_WORKERS})..."
        )
        with ThreadPoolExecutor(max_workers=TOKEN_STATS_WORKERS) as pool:
            futures = {
                pool.submit(
                    get_chat_conversation_usage_from_messages,
                    dict(headers), app_id, conversation_id,
                ): app_id
                for app_id, conversation_id in conversation_tasks
            }
            completed_by_app = {
                app_id: 0 for app_id in chat_conversations_by_app
            }
            totals_by_app = {
                app_id: len(conversations)
                for app_id, conversations in chat_conversations_by_app.items()
            }
            progress_steps = {
                app_id: max(1, total // 10)
                for app_id, total in totals_by_app.items()
            }
            for future in as_completed(futures):
                app_id = futures[future]
                stats = stats_by_app[app_id]
                try:
                    (
                        input_tokens, output_tokens, total_tokens,
                        failed_messages, complete,
                    ) = future.result()
                    stats["input_tokens"] += input_tokens
                    stats["output_tokens"] += output_tokens
                    stats["total_tokens"] += total_tokens
                    if failed_messages:
                        stats["failed"] += 1
                    else:
                        stats["success"] += 1
                    stats["complete"] = stats["complete"] and complete
                except Exception:
                    stats["complete"] = False
                completed_by_app[app_id] += 1
                app_done = completed_by_app[app_id]
                app_total = totals_by_app[app_id]
                if app_done == app_total or app_done % progress_steps[app_id] == 0:
                    with progress_lock:
                        print(
                            f"  {format_progress(app_done, app_total)} · "
                            f"{stats['name']}：Chatflow Token"
                        )
    return [stats_by_app[app["app_id"]] for app in apps]
