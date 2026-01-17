"""
LLM agent wrapper with pluggable providers.
Supports: Ollama, Gemini, ChatGPT (OpenAI), Deepseek, and a stub fallback.
Configure with env vars: LLM_PROVIDER, *_API_KEY, *_MODEL, *_BASE_URL.
"""
from dataclasses import dataclass
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Protocol


@dataclass
class AgentResponse:
    text: str
    command: str | None = None
    params: Dict[str, Any] | None = None


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        ...


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float = 30.0) -> Dict[str, Any]:
    """
    Minimal HTTP JSON POST helper to avoid external deps.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode("utf-8", errors="ignore")
        raise LLMError(f"HTTP {exc.code} for {url}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise LLMError(f"Request failed for {url}: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:  # pragma: no cover - network path
        snippet = body[:200]
        raise LLMError(f"Bad JSON from {url}: {snippet}") from exc


class OllamaClient:
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3")
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    def complete(self, prompt: str, *, system_prompt: str | None = None, temperature: float | None = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        data = _post_json(url, payload, headers={"Content-Type": "application/json"})
        try:
            message = data.get("message") or data["messages"][-1]
            return str(message["content"]).strip()
        except Exception as exc:
            raise LLMError(f"Unexpected Ollama response: {data}") from exc


class OpenAIChatClient:
    """
    ChatGPT-compatible client (OpenAI endpoint).
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is required for provider=openai/chatgpt")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")).rstrip("/")

    def complete(self, prompt: str, *, system_prompt: str | None = None, temperature: float | None = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        url = f"{self.base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {"model": self.model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = _post_json(url, payload, headers=headers)
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise LLMError(f"Unexpected OpenAI response: {data}") from exc


class DeepSeekClient:
    """
    Deepseek client (OpenAI-compatible surface).
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise LLMError("DEEPSEEK_API_KEY is required for provider=deepseek")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")

    def complete(self, prompt: str, *, system_prompt: str | None = None, temperature: float | None = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {"model": self.model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = _post_json(url, payload, headers=headers)
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise LLMError(f"Unexpected Deepseek response: {data}") from exc


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is required for provider=gemini")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-pro")
        self.base_url = (base_url or os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")

    def complete(self, prompt: str, *, system_prompt: str | None = None, temperature: float | None = None) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}
        if temperature is not None:
            payload["generationConfig"] = {"temperature": temperature}

        data = _post_json(url, payload, headers={"Content-Type": "application/json"})
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return str(parts[0]["text"]).strip()
        except Exception as exc:
            raise LLMError(f"Unexpected Gemini response: {data}") from exc


class StubClient:
    def __init__(self, provider_name: str):
        self.provider_name = provider_name

    def complete(self, prompt: str, *, system_prompt: str | None = None, temperature: float | None = None) -> str:
        prefix = f"[stub:{self.provider_name}] "
        if system_prompt:
            return f"{prefix}{system_prompt} :: {prompt}"
        return f"{prefix}{prompt}"


class Agent:
    def __init__(self, provider: str | None = None):
        self.provider_name = (provider or os.environ.get("LLM_PROVIDER", "stub")).lower()
        self.client = self._build_client(self.provider_name)

    def _build_client(self, provider: str) -> LLMClient:
        if provider in {"ollama"}:
            return OllamaClient()
        if provider in {"openai", "chatgpt"}:
            return OpenAIChatClient()
        if provider in {"deepseek", "deepseek-chat"}:
            return DeepSeekClient()
        if provider in {"gemini", "google"}:
            return GeminiClient()
        return StubClient(provider)

    def respond(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> AgentResponse:
        try:
            text = self.client.complete(prompt, system_prompt=system_prompt, temperature=temperature)
            return AgentResponse(text=text, command=None, params=None)
        except LLMError as exc:
            # Do not raise to keep caller simple; surface error in the response text.
            return AgentResponse(text=f"[llm:{self.provider_name} error] {exc}", command=None, params=None)
