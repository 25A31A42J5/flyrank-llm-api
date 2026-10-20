import os
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


# Convert request validation errors to HTTP 400.
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


# Allowed output values.
class Category(str, Enum):
    billing = "billing"
    technical = "technical"
    account = "account"
    other = "other"


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# Request and response schemas.
class ClassifyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class ClassifyResponse(BaseModel):
    category: Category
    priority: Priority
    needs_human: bool


def classify_with_llm(message: str) -> ClassifyResponse:
    # Deterministic stub for development and evaluation.
    if os.getenv("LLM_STUB", "0") == "1":
        return ClassifyResponse(
            category=Category.technical,
            priority=Priority.medium,
            needs_human=False,
        )

    # Load the versioned prompt from its file.
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

    try:
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "llama3.2:latest"),
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("The model returned an empty response")

        # Parse and validate the model output against our schema.
        return ClassifyResponse.model_validate_json(content)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM classification failed: {type(exc).__name__}",
        ) from exc


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest):
    return classify_with_llm(request.message)
