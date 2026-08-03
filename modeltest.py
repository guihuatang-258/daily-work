import json
import os

import requests
from dotenv import load_dotenv


API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def extract_delta_content(chunk: dict) -> str:
    choices = chunk.get("choices") or []
    if not choices:
        return ""

    delta = choices[0].get("delta") or {}
    return delta.get("content") or ""


def stream_chat() -> None:
    load_dotenv()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置环境变量 DASHSCOPE_API_KEY")

    request_body = {
        "model": "qwen3.7-plus",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "你好"}],
            }
        ],
        "thinking": {"type": "disabled"},
        "stream": True,
    }
    request_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    with requests.post(
        API_URL,
        json=request_body,
        headers=request_headers,
        stream=True,
        timeout=120,
    ) as response:
        response.raise_for_status()
        response.encoding = "utf-8"

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue

            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break

            chunk = json.loads(data)
            content = extract_delta_content(chunk)
            if content:
                print(content, end="", flush=True)

    print()


if __name__ == "__main__":
    stream_chat()
