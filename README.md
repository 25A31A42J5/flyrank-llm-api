# FlyRank LLM API

A FastAPI application that classifies customer support messages using a locally hosted LLM through Ollama. It returns a structured classification with a category, priority, and indication of whether human review is needed.

## Job Card

**Task:** Classify customer support messages.

**Input:** A customer message containing between 1 and 5,000 characters.

**Output:**

* `category`: `billing`, `technical`, `account`, or `other`
* `priority`: `low`, `medium`, or `high`
* `needs_human`: Boolean (`true` or `false`)

**Must never:**

* Return categories or priorities outside the allowed values.
* Return `needs_human` as a string instead of a Boolean.
* Return malformed JSON or extra fields in the classification.
* Treat ambiguous messages as certain when human review is needed.

## Technology

* Python
* FastAPI
* Pydantic
* OpenAI Python SDK
* Ollama
* Model: `llama3.2:latest`

The OpenAI SDK communicates with Ollama through its OpenAI-compatible API.

## Requirements

* Python 3.10+
* Ollama installed and running
* A model downloaded in Ollama

## Setup

Install the dependencies:

```powershell
pip install fastapi uvicorn openai python-dotenv pytest
```

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Configure the environment variables in `.env`:

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2:latest
LLM_STUB=0
LLM_ENABLED=true
LLM_TIMEOUT_SECONDS=30
LLM_MAX_ATTEMPTS=4
```

Keep `.env` private and do not commit it to Git.

## Run Locally

Make sure Ollama is running and the configured model is available.

Start the API:

```powershell
uvicorn main:app --reload
```

Interactive API documentation is available at:

`http://127.0.0.1:8000/docs`

## API Usage

### Endpoint

`POST /classify`

### Example request

```powershell
$body = @{
    message = "I was charged twice for my subscription."
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/classify" -Method POST -ContentType "application/json" -Body $body
```

Equivalent cURL request:

```bash
curl -X POST "http://127.0.0.1:8000/classify" -H "Content-Type: application/json" -d "{\"message\":\"I was charged twice for my subscription.\"}"
```

### Example response

```json
{
  "category": "billing",
  "priority": "high",
  "needs_human": false
}
```

The exact classification can vary depending on the model and message.

## Request Validation

Messages must contain between 1 and 5,000 characters.

An empty message should be rejected with HTTP 400 and identify the invalid `message` field.

Example:

```powershell
$body = @{
    message = ""
} | ConvertTo-Json

Inv
```

## Evaluation

**Evaluation date:** 2026-10-21
**Prompt version:** `v1`
**Model:** `llama3.2:latest` via Ollama

Eight manually labeled support-message cases were evaluated against the running API.

| Metric                    |        Result |
| ------------------------- | ------------: |
| Cases fully matched       |   5/8 (62.5%) |
| Field accuracy            | 21/24 (87.5%) |
| Fields evaluated per case |             3 |

Three cases had mismatches:

* Case 3: Priority was `medium` instead of `high`.
* Case 5: Priority was `high` instead of `medium`.
* Case 8: Category was `account` instead of `other`.

These results are an initial evaluation on a small, manually labeled dataset. They do not establish general classification accuracy. Future work should refine the prompt and evaluate it on a larger, representative dataset.

