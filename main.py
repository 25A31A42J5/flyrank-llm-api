import json
import os
import random
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(title="FlyRank LLM API")

BASE_DIR = Path(__file__).parent
QUARANTINE_PATH = BASE_DIR / "logs" / "quarantine.jsonl"

TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
MAX_ATTEMPTS = max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "4")))


def log_event(**details) -> None:
    """Write one structured JSON log line."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    print(json.dumps(record), flush=True)


def quarantine_invalid_output(error_type: str) -> None:
    """Record diagnostic metadata without storing raw model output."""
    QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_type": error_type,
    }

    with QUARANTINE_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    fields = [
        str(error["loc"][-1])
        for error in exc.errors()
        if error.get("loc")
    ]

    return JSONResponse(
        status_code=400,
        content={
            "error": "Invalid request",
            "fields": fields,
            "details": exc.errors(),
        },
    )


class Category(str, Enum):
    billing = "billing"
    technical = "technical"
    account = "account"
    other = "other"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ClassifyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class ClassifyResponse(BaseModel):
    category: Category
    priority: Priority
    needs_human: bool


def get_retry_delay(exc, attempt: int) -> float:
    """Respect Retry-After when available; otherwise use backoff with jitter."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}

    retry_after_ms = headers.get("retry-after-ms")

    if retry_after_ms is not None:
        try:
            return max(0.0, float(retry_after_ms) / 1000)
        except (TypeError, ValueError):
            pass

    retry_after = headers.get("retry-after")

    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass

    backoff = min(2 ** (attempt - 1), 4)
    return backoff + random.uniform(0, 0.25)


def is_retryable(exc) -> bool:
    """Retry timeouts, HTTP 429, and HTTP 5xx errors only."""
    if isinstance(exc, APITimeoutError):
        return True

    if isinstance(exc, APIStatusError):
        return (
            exc.status_code == 429
            or 500 <= exc.status_code <= 599
        )

    return False


def raise_llm_http_error(exc, phase: str):
    """Translate model-call failures into HTTP errors."""
    if isinstance(exc, APITimeoutError):
        status_code = 504
        detail = f"LLM {phase} timed out."
    elif isinstance(exc, APIStatusError) and exc.status_code == 429:
        status_code = 502
        detail = f"LLM {phase} failed after rate limiting."
    else:
        status_code = 502
        detail = f"LLM {phase} failed: {type(exc).__name__}"

    raise HTTPException(
        status_code=status_code,
        detail=detail,
    ) from None


def classify_with_llm(message: str) -> ClassifyResponse:
    # Kill switch: do not initialize or call the model when disabled.
    if os.getenv("LLM_ENABLED", "true").strip().lower() == "false":
        raise HTTPException(
            status_code=503,
            detail="LLM classification is temporarily disabled.",
        )

    if os.getenv("LLM_STUB", "0") == "1":
        return ClassifyResponse(
            category=Category.technical,
            priority=Priority.medium,
            needs_human=False,
        )

    prompt_path = BASE_DIR / "prompts" / "support-classifier-v1.md"

    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The classifier prompt file could not be loaded.",
        ) from exc

    prompt_version = prompt_path.stem.rsplit("-", 1)[-1]
    model = os.getenv("LLM_MODEL", "llama3.2:latest")

    client = OpenAI(
        base_url=os.getenv(
            "LLM_BASE_URL",
            "http://localhost:11434/v1",
        ),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
    )

    def request_model(messages: list[dict], repair: bool = False) -> str:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            input_tokens = None
            output_tokens = None

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )

                usage = getattr(response, "usage", None)

                if usage is not None:
                    input_tokens = getattr(
                        usage,
                        "prompt_tokens",
                        None,
                    )
                    output_tokens = getattr(
                        usage,
                        "completion_tokens",
                        None,
                    )

                content = response.choices[0].message.content

                if not content:
                    raise ValueError("empty_output")

                log_event(
                    event="llm_call",
                    prompt_version=prompt_version,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=round(
                        (time.perf_counter() - started) * 1000
                    ),
                    repair=repair,
                    attempt=attempt,
                    success=True,
                )

                return content

            except Exception as exc:
                log_event(
                    event="llm_call",
                    prompt_version=prompt_version,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=round(
                        (time.perf_counter() - started) * 1000
                    ),
                    repair=repair,
                    attempt=attempt,
                    success=False,
                    error_type=type(exc).__name__,
                    status_code=getattr(exc, "status_code", None),
                )

                if not is_retryable(exc) or attempt >= MAX_ATTEMPTS:
                    raise

                delay = get_retry_delay(exc, attempt)

                log_event(
                    event="llm_retry",
                    prompt_version=prompt_version,
                    model=model,
                    repair=repair,
                    attempt=attempt,
                    delay_seconds=round(delay, 3),
                    error_type=type(exc).__name__,
                )

                time.sleep(delay)

        raise RuntimeError("LLM request attempts exhausted.")

    def validate_output(content: str) -> ClassifyResponse:
        return ClassifyResponse.model_validate_json(content)

    try:
        content = request_model(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ]
        )
    except Exception as exc:
        raise_llm_http_error(exc, "classification")

    try:
        return validate_output(content)
    except Exception as exc:
        first_error_type = type(exc).__name__

    repair_messages = [
        {
            "role": "system",
            "content": (
                "Repair the previous assistant response. Return exactly "
                "one valid JSON object with these fields: category, priority, "
                "needs_human. category must be billing, technical, account, "
                "or other. priority must be low, medium, or high. "
                "needs_human must be a JSON boolean: true or false. "
                "Do not include markdown or additional text."
            ),
        },
        {
            "role": "user",
            "content": (
                "Classify the following customer message according to "
                "the required schema:\n"
                f"{message}\n"
                "The previous response was invalid. Return corrected JSON."
            ),
        },
        {
            "role": "assistant",
            "content": content,
        },
    ]

    try:
        repaired_content = request_model(
            repair_messages,
            repair=True,
        )
    except Exception as exc:
        raise_llm_http_error(exc, "repair request")

    try:
        return validate_output(repaired_content)
    except Exception as repair_error:
        error_details = (
            f"initial={first_error_type};"
            f"repair={type(repair_error).__name__}"
        )

        try:
            quarantine_invalid_output(error_details)
        except OSError:
            pass

        raise HTTPException(
            status_code=422,
            detail=(
                "The model returned an invalid classification "
                "after one repair attempt."
            ),
        ) from None


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest):
    return classify_with_llm(request.message)