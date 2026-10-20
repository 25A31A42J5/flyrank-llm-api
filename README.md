# FlyRank LLM API

A FastAPI application that classifies customer support messages using a locally hosted LLM through Ollama.

## Endpoint

`POST /classify`

Accepts a support message and returns a JSON object containing:

* `category`: `billing`, `technical`, `account`, or `other`
* `priority`: `low`, `medium`, or `high`
* `needs_human`: `true` or `false`

## Requirements

* Python 3.10+
* Ollama installed and running
* An Ollama model, configured through `.env`

## Configuration

Create a `.env` file using `.env.example` as a reference:

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2:latest
LLM_STUB=0
```

Set `LLM_STUB=1` to use a deterministic stub response without calling the model. Set it to `0` for actual model calls.

## Run Locally

Install dependencies:

```powershell
pip install fastapi uvicorn openai python-dotenv
```

Start the API:

```powershell
uvicorn main:app --reload
```

Open `/docs` on the local server to explore and interact with the API.

## Valid Request

PowerShell example:

```powershell
$body = @{
    message = "I was charged twice for my subscription."
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/classify" -Method Post -ContentType "application/json" -Body $body
```

## Invalid Request

An empty message must be rejected with HTTP 400, identifying the invalid `message` field.

```powershell
$body = @{
    message = ""
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/classify" -Method Post -ContentType "application/json" -Body $body
```
