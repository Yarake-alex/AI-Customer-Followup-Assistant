import logging
import time
import traceback
from typing import Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# Fast-token-estimate heuristics
FALLBACK_MESSAGE = (
    "AI 服务暂时不可用，请稍后重试。你仍可以先记录本次跟进内容。"
)
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _estimate_tokens(text: str) -> int:
    """Rough estimate: Chinese 1-2 char/token, English ~4 char/token.

    Uses a blended rate of 2.5 chars per token — good enough for cost
    visibility, intentionally not a precise tokenizer.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 2.5))


def _is_retryable_error(exc: Exception) -> bool:
    """True for transient network / 5xx errors that merit a retry.

    False for auth errors, bad requests, or other permanent failures.
    """
    msg = str(exc).lower()

    # openai library wraps HTTP errors; check status code
    code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if code is not None and code in RETRYABLE_HTTP_STATUS:
        return True
    if code is not None and code not in (0, None):
        return False  # 4xx, etc. — not retryable

    # Connection / timeout errors
    for keyword in (
        "timeout", "timed out", "connection", "connectionerror",
        "retryable", "server error", "internal server error",
        "service unavailable", "bad gateway", "gateway timeout",
        "too many requests", "rate limit",
    ):
        if keyword in msg:
            return True

    # Permanent errors
    for keyword in (
        "401", "403", "invalid api key", "unauthorized",
        "authentication", "incorrect api key",
    ):
        if keyword in msg:
            return False

    return True  # unknown errors → retry once (conservative)


def _write_usage_log(
    db: Optional[Session],
    *,
    user_id: Optional[int],
    feature: str,
    provider: str,
    model: str,
    prompt_chars: int,
    response_chars: int,
    status: str,
    error_message: Optional[str],
    duration_ms: int,
) -> None:
    """Persist an AiCallLog row.  Failure here is logged but never raised."""
    if not settings.LLM_ENABLE_USAGE_LOG or db is None:
        return
    try:
        # re-import within try so import failures don't propagate
        from app.models import AiCallLog

        log_entry = AiCallLog(
            user_id=user_id,
            feature=feature,
            provider=provider,
            model=model,
            prompt_chars=prompt_chars,
            response_chars=response_chars,
            estimated_prompt_tokens=_estimate_tokens("x" * prompt_chars) if prompt_chars else 0,
            estimated_response_tokens=_estimate_tokens("x" * response_chars) if response_chars else 0,
            status=status,
            error_message=(error_message[:500] if error_message else None),
            duration_ms=duration_ms,
        )
        db.add(log_entry)
        db.commit()
    except Exception:
        try:
            if db is not None:
                db.rollback()
        except Exception:
            pass
        logger.warning("AiCallLog write failed (non-fatal): %s", traceback.format_exc())


def build_customer_context(customer, followups):
    records = "\n".join(
        [
            f"- 时间：{f.created_at.strftime('%Y-%m-%d %H:%M')}；内容：{f.content}；下一步：{f.next_action or '暂无'}"
            for f in followups
        ]
    ) or "暂无跟进记录"

    return f"""
客户姓名：{customer.name}
公司名称：{customer.company}
行业：{customer.industry or '未知'}
客户等级：{customer.level or '未设置'}
意向程度：{customer.intention or '未设置'}
合作状态：{customer.cooperation_status or '未设置'}
电话：{customer.phone or '未填写'}
邮箱：{customer.email or '未填写'}

历史跟进记录：
{records}
"""


def call_llm(
    prompt: str,
    *,
    feature: str = "unknown",
    user_id: Optional[int] = None,
    db: Optional[Session] = None,
) -> str:
    """Call the LLM with timeout, retries, fallback, and usage logging.

    Old callers that use ``call_llm(prompt)`` continue to work unchanged.
    """
    t0 = time.perf_counter()
    max_chars = settings.LLM_MAX_PROMPT_CHARS
    provider = "mock"
    model = ""
    status = "error"  # default; set to "success" only on actual success
    error_message: Optional[str] = None
    response_text = ""

    # ── Prompt truncation ──
    if len(prompt) > max_chars:
        truncated = prompt[-max_chars:]  # keep the tail (newest context)
        logger.warning(
            "Prompt truncated from %d to %d chars (feature=%s, user=%s)",
            len(prompt), max_chars, feature, user_id,
        )
        prompt = truncated

    prompt_chars = len(prompt)

    # ── Mock path ──
    if settings.LLM_PROVIDER != "openai_compatible" or not settings.OPENAI_API_KEY:
        provider = "mock"
        model = "mock"
        try:
            response_text = mock_llm_response(prompt)
            status = "success"
        except Exception:
            status = "error"
            error_message = "mock LLM returned an unexpected error"
            response_text = FALLBACK_MESSAGE
        duration_ms = round((time.perf_counter() - t0) * 1000)
        try:
            _write_usage_log(
                db, user_id=user_id, feature=feature, provider=provider,
                model=model, prompt_chars=prompt_chars,
                response_chars=len(response_text), status=status,
                error_message=error_message, duration_ms=duration_ms,
            )
        except Exception:
            logger.warning("Usage log write failed (non-fatal): %s", traceback.format_exc())
        return response_text

    # ── Real API path ──
    provider = "openai_compatible"
    model = settings.OPENAI_MODEL

    import httpx

    client = OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS),
        max_retries=0,  # we handle retries ourselves for smart classification
    )

    last_exc: Optional[Exception] = None

    for attempt in range(1 + settings.LLM_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的 ToB 销售客户跟进助手，回答要具体、可执行、适合销售人员使用。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_COMPLETION_TOKENS,
            )
            response_text = response.choices[0].message.content or ""
            status = "success"
            error_message = None
            break  # success — exit retry loop
        except Exception as exc:
            last_exc = exc
            can_retry = _is_retryable_error(exc) and (attempt < settings.LLM_MAX_RETRIES)
            logger.warning(
                "LLM call failed (attempt %d/%d, feature=%s, user=%s): %s",
                attempt + 1, 1 + settings.LLM_MAX_RETRIES, feature, user_id, exc,
            )
            if can_retry:
                time.sleep(min(2 ** attempt, 4))  # exponential backoff capped at 4s
                continue
            break

    if status != "success":
        # API call failed — record the error, then deliver the fallback.
        if not error_message and last_exc is not None:
            error_message = str(last_exc)[:500]
        if not response_text:
            response_text = FALLBACK_MESSAGE
        status = "fallback"

    duration_ms = round((time.perf_counter() - t0) * 1000)
    try:
        _write_usage_log(
            db, user_id=user_id, feature=feature, provider=provider,
            model=model, prompt_chars=prompt_chars,
            response_chars=len(response_text), status=status,
            error_message=error_message, duration_ms=duration_ms,
        )
    except Exception:
        logger.warning("Usage log write failed (non-fatal): %s", traceback.format_exc())
    return response_text


def mock_llm_response(prompt: str) -> str:
    if "知识库资料" in prompt or "参考资料" in prompt:
        return """【AI模拟RAG回答】
根据已上传资料，当前问题可以从产品应用场景、客户需求匹配和下一步沟通三个方面分析。

1. 产品匹配：建议优先结合客户行业、屏幕尺寸、亮度、接口方式和交付周期进行判断。
2. 客户沟通：可以追问客户项目阶段、预计用量、应用场景和是否有定制需求。
3. 下一步动作：建议发送产品资料，并同步确认客户的技术参数要求和采购时间节点。

注意：当前为 mock 模式，如需真实回答，请在 .env 中配置 DeepSeek API。"""

    if "总结" in prompt:
        return """【AI模拟总结】
该客户已建立基础联系，目前需要重点判断真实采购需求、项目时间节点、预算情况和决策链条。
从现有跟进信息看，下一步不应只做普通寒暄，而应围绕客户业务场景继续追问需求，并沉淀关键信息。"""

    return """【AI模拟建议】
1. 先确认客户目前是否有明确项目、采购计划或替换需求。
2. 重点询问：应用场景、预计数量、预算范围、决策人、时间节点。
3. 可以准备一段简短话术：您好，我这边想根据贵司实际应用场景，帮您初步匹配更合适的方案，方便了解下目前项目大概处在哪个阶段吗？
4. 跟进后及时记录客户反馈，为后续报价或方案推荐做准备。"""
