import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(title="FlyRank LLM API")

QUARANTINE_PATH = Path(__file__).parent / "logs" / "quarantine.jsonl"


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


def classify_with_llm(message: str) -> ClassifyResponse:
    if os.getenv("LLM_STUB", "0") == "1":
        return ClassifyResponse(
            category=Category.technical,
            priority=Priority.medium,
            needs_human=False,
        )

    prompt_path = (
        Path(__file__).parent
        / "prompts"
        / "support-classifier-v1.md"
    )

    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="The classifier prompt file could not be loaded.",
        ) from exc

    client = OpenAI(
        base_url=os.getenv(
            "LLM_BASE_URL",
            "http://localhost:11434/v1",
        ),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
        timeout=30.0,
        max_retries=0,
    )

    model = os.getenv("LLM_MODEL", "llama3.2:latest")

    def request_model(messages: list[dict]) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("empty_output")

        return content

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
        raise HTTPException(
            status_code=502,
            detail=f"LLM classification failed: {type(exc).__name__}",
        ) from exc

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
        repaired_content = request_model(repair_messages)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM repair request failed: {type(exc).__name__}",
        ) from exc

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