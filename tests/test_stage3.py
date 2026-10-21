import json

import pytest
from fastapi import HTTPException

import main


class FakeResponse:
    def __init__(self, content):
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Message",
                        (),
                        {"content": content},
                    )()
                },
            )()
        ]


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)

    def create(self, **kwargs):
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


class FakeClient:
    def __init__(self, responses):
        self.chat = type(
            "Chat",
            (),
            {
                "completions": FakeCompletions(responses)
            },
        )()


def setup_fake(monkeypatch, tmp_path, responses):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "support-classifier-v1.md").write_text(
        "Classify customer support messages.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        main,
        "QUARANTINE_PATH",
        tmp_path / "logs" / "quarantine.jsonl",
    )
    monkeypatch.setattr(
        main,
        "OpenAI",
        lambda **kwargs: FakeClient(responses),
    )
    monkeypatch.setenv("LLM_STUB", "0")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")


def test_valid_response(monkeypatch, tmp_path):
    setup_fake(
        monkeypatch,
        tmp_path,
        ['{"category":"billing","priority":"high","needs_human":false}'],
    )

    result = main.classify_with_llm("I was charged twice.")

    assert result.category == main.Category.billing
    assert result.priority == main.Priority.high
    assert result.needs_human is False


def test_invalid_response_repaired(monkeypatch, tmp_path):
    setup_fake(
        monkeypatch,
        tmp_path,
        [
            '{"category":"unknown","priority":"high","needs_human":false}',
            '{"category":"billing","priority":"high","needs_human":false}',
        ],
    )

    result = main.classify_with_llm("I was charged twice.")

    assert result.category == main.Category.billing
    assert result.priority == main.Priority.high
    assert result.needs_human is False


def test_invalid_response_quarantined(monkeypatch, tmp_path):
    setup_fake(
        monkeypatch,
        tmp_path,
        [
            '{"category":"unknown","priority":"high","needs_human":false}',
            '{"category":"unknown","priority":"urgent","needs_human":"no"}',
        ],
    )

    with pytest.raises(HTTPException) as error:
        main.classify_with_llm("I was charged twice.")

    assert error.value.status_code == 422

    quarantine_path = main.QUARANTINE_PATH
    assert quarantine_path.exists()

    record = json.loads(
        quarantine_path.read_text(encoding="utf-8").strip()
    )
    assert "timestamp" in record
    assert "error_type" in record
    assert "I was charged twice." not in quarantine_path.read_text(
        encoding="utf-8"
    )