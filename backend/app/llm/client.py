import json
import re
import time
from contextlib import suppress
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LLMCall

JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMNotConfigured(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


class JSONCompleter(Protocol):
    model: str

    def complete_json(self, system: str, user: str, purpose: str) -> dict[str, Any]: ...


def parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = JSON_BLOCK.search(text or "")
        if not match:
            raise LLMResponseError("Model did not return JSON") from None
        return json.loads(match.group(0))


class LiteLLMCompleter:
    def __init__(self, db: Session, model: str | None = None):
        settings = get_settings()
        self.db = db
        self.model = model or settings.llm_model
        self.api_key = settings.llm_api_key if model is None else ""
        self.timeout = settings.llm_timeout_seconds
        if not self.api_key and settings.llm_provider != "ollama":
            raise LLMNotConfigured(f"Set {settings.llm_provider.upper()}_API_KEY in .env for {self.model}")

    def complete_json(self, system: str, user: str, purpose: str) -> dict[str, Any]:
        import litellm

        started = time.monotonic()
        call = LLMCall(model=self.model, purpose=purpose, success=False)
        try:
            response = litellm.completion(
                model=self.model,
                api_key=self.api_key or None,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                timeout=self.timeout,
                num_retries=2,
            )
            usage = getattr(response, "usage", None)
            call.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            call.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            call.cost_usd = 0
            with suppress(Exception):
                call.cost_usd = litellm.completion_cost(completion_response=response) or 0
            payload = parse_json(response.choices[0].message.content or "")
            call.success = True
            return payload
        finally:
            call.latency_ms = int((time.monotonic() - started) * 1000)
            self.db.add(call)
            self.db.commit()
