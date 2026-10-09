from __future__ import annotations

import base64
import json
import math
import re
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_PROMPT = (
    "你是高精度商品详情页文字转写器。任务不是理解、概括或改写，而是从这张"
    "小红书商品详情页截图中逐字抄录商品标题，并提取当前实际成交价。\n"
    "请在内部严格执行以下检查，但最终只输出符合给定JSON结构的结果：\n"
    "1. 先定位价格区。商品标题是价格及促销标签下方、商品服务标签或店铺信息上方的"
    "黑色正文。不要把主图、广告图、顶部导航、推荐标签、销量标签或服务说明里的大字"
    "当成商品标题。\n"
    "2. 标题可能分成两行或多行。必须按从上到下、每行从左到右完整拼接；逐字保留"
    "汉字、数字、字母、标点和符号，不得总结、纠错、同义改写、补词或漏字，也不要"
    "因为语义相似而合并字符。\n"
    "3. 生成title后必须对照原图从第一个字符到最后一个字符再核对一遍。对连续数字、"
    "年级和序列词逐项点验，尤其不得漏掉类似‘一二三四五六’中的任何一项。\n"
    "4. price取当前实际成交价或到手价；若同时出现原价、划线价和到手价，必须选择"
    "到手价，完整保留小数。\n"
    "5. evidence只简短写明标题正文的开头与结尾片段，以及采用的是哪一种价格。"
    "若标题或价格有任何字符看不清、被遮挡或无法唯一确认，title返回空字符串且"
    "price返回0，让程序停止；禁止猜测。\n"
    "只返回JSON对象，不要输出Markdown、解释、候选答案或原图中其他文字。"
)

_RESPONSE_LIMIT_BYTES = 1024 * 1024
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class VisionFieldsError(RuntimeError):
    """本地视觉字段服务不可用或返回了不可安全采用的结果。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence = dict(evidence or {})


def vision_fields_enabled(config: dict) -> bool:
    return config.get("enabled") is True


def _validated_endpoint(config: dict) -> str:
    endpoint = str(config.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOCAL_HOSTS
        or parsed.username
        or parsed.password
        or not parsed.path
    ):
        raise VisionFieldsError(
            "vision_config_invalid",
            "视觉模型接口必须是本机HTTP地址",
            evidence={"endpoint": endpoint},
        )
    return endpoint


def _positive_number(value: object, *, field: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisionFieldsError(
            "vision_response_invalid",
            f"视觉模型字段 {field} 不是数字",
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > maximum:
        raise VisionFieldsError(
            "vision_response_invalid",
            f"视觉模型字段 {field} 超出安全范围",
        )
    return number


def _validated_content(content: object) -> dict:
    if not isinstance(content, str) or not content.strip():
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型没有返回JSON正文",
        )
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型返回内容不是严格JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型JSON顶层不是对象",
        )

    raw_title = payload.get("title")
    if not isinstance(raw_title, str):
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型缺少字符串标题",
        )
    title = re.sub(r"[\r\n\t]+", "", raw_title).strip()
    if not title or len(title) > 240:
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型标题为空或长度异常",
        )
    price = _positive_number(payload.get("price"), field="price", maximum=1_000_000)
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise VisionFieldsError(
            "vision_response_invalid",
            "视觉模型 evidence 不是字符串",
        )
    return {
        "title": title,
        "price": price,
        "evidence": (evidence or "").strip(),
    }


def extract_product_fields_with_vision(
    image_path: Path,
    config: dict,
) -> dict:
    """调用本机Ollama一次，返回经过严格校验的商品标题和实际价格。"""

    image_path = image_path.resolve()
    endpoint = _validated_endpoint(config)
    model = str(config.get("model") or "").strip()
    if not model:
        raise VisionFieldsError(
            "vision_config_invalid",
            "未配置视觉模型名称",
            evidence={"endpoint": endpoint},
        )
    timeout_seconds = _positive_number(
        config.get("timeout_seconds", 600),
        field="timeout_seconds",
        maximum=1800,
    )
    if not image_path.is_file():
        raise VisionFieldsError(
            "vision_image_missing",
            "视觉模型输入截图不存在",
            evidence={"screenshot": str(image_path)},
        )

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "price": {"type": "number"},
            "evidence": {"type": "string"},
        },
        "required": ["title", "price", "evidence"],
    }
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": str(config.get("prompt") or DEFAULT_PROMPT),
                "images": [
                    base64.b64encode(image_path.read_bytes()).decode("ascii")
                ],
            }
        ],
        "stream": False,
        "think": False,
        "format": schema,
        "keep_alive": str(config.get("keep_alive") or "30m"),
        "options": {
            "temperature": 0,
            "num_predict": int(config.get("num_predict") or 180),
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(_RESPONSE_LIMIT_BYTES + 1)
    except HTTPError as exc:
        raise VisionFieldsError(
            "vision_service_http_error",
            f"本地视觉模型接口返回HTTP {exc.code}",
            evidence={
                "endpoint": endpoint,
                "model": model,
                "screenshot": str(image_path),
            },
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise VisionFieldsError(
            "vision_service_timeout",
            f"本地视觉模型推理超过 {timeout_seconds:g} 秒",
            evidence={
                "endpoint": endpoint,
                "model": model,
                "screenshot": str(image_path),
            },
        ) from exc
    except (URLError, OSError) as exc:
        raise VisionFieldsError(
            "vision_service_unavailable",
            f"无法连接本地视觉模型：{exc}",
            evidence={
                "endpoint": endpoint,
                "model": model,
                "screenshot": str(image_path),
            },
        ) from exc
    wall_seconds = time.monotonic() - started
    if len(raw) > _RESPONSE_LIMIT_BYTES:
        raise VisionFieldsError(
            "vision_response_invalid",
            "本地视觉模型响应超过安全大小限制",
            evidence={"endpoint": endpoint, "model": model},
        )
    try:
        response_payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisionFieldsError(
            "vision_response_invalid",
            "本地视觉模型响应不是有效UTF-8 JSON",
            evidence={"endpoint": endpoint, "model": model},
        ) from exc
    if not isinstance(response_payload, dict):
        raise VisionFieldsError(
            "vision_response_invalid",
            "本地视觉模型响应顶层不是对象",
        )
    message = response_payload.get("message")
    if not isinstance(message, dict):
        raise VisionFieldsError(
            "vision_response_invalid",
            "本地视觉模型响应缺少 message",
        )
    fields = _validated_content(message.get("content"))

    def seconds(name: str) -> float | None:
        value = response_payload.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return round(float(value) / 1_000_000_000, 3)

    return {
        **fields,
        "source": "ollama_vision",
        "model": model,
        "endpoint": endpoint,
        "screenshot": str(image_path),
        "timing": {
            "wall_seconds": round(wall_seconds, 3),
            "total_seconds": seconds("total_duration"),
            "load_seconds": seconds("load_duration"),
            "prompt_seconds": seconds("prompt_eval_duration"),
            "eval_seconds": seconds("eval_duration"),
        },
        "token_counts": {
            "prompt": response_payload.get("prompt_eval_count"),
            "output": response_payload.get("eval_count"),
        },
    }
