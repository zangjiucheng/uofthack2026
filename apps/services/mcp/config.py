from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _env(key: str, default: Optional[str] = None) -> str:
    v = os.environ.get(key)
    if v is None:
        return default if default is not None else ""
    return v


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except Exception:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except Exception:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class McpRestConfig:
    host: str = "0.0.0.0"
    port: int = 8090
    enabled: bool = True

    @staticmethod
    def from_env() -> "McpRestConfig":
        host = _env("APP_MCP_REST_HOST", _env("MCP_REST_HOST", "0.0.0.0"))
        port = _env_int("APP_MCP_REST_PORT", _env_int("MCP_REST_PORT", 8090))
        enabled = _env_bool("APP_MCP_REST", _env_bool("MCP_REST", True))
        return McpRestConfig(host=host, port=port, enabled=enabled)


@dataclass(frozen=True)
class PlannerServiceConfig:
    host: str = "0.0.0.0"
    port: int = 8091
    enabled: bool = True

    @staticmethod
    def from_env() -> "PlannerServiceConfig":
        host = _env("APP_PLANNER_HOST", "0.0.0.0")
        port = _env_int("APP_PLANNER_PORT", 8091)
        enabled = _env_bool("APP_PLANNER_SERVICE", _env_bool("PLANNER_SERVICE", True))
        return PlannerServiceConfig(host=host, port=port, enabled=enabled)


@dataclass(frozen=True)
class SttConfig:
    enabled: bool = True
    model_path: str = ""
    sample_rate: int = 16000
    device: Optional[int] = None
    phrase_timeout_s: float = 1.0

    @staticmethod
    def from_env() -> "SttConfig":
        enabled = _env_bool("APP_STT", _env_bool("STT", True))
        model_path = _env("VOSK_MODEL_PATH", _env("APP_VOSK_MODEL_PATH", ""))
        sample_rate = _env_int("APP_STT_SAMPLE_RATE", _env_int("STT_SAMPLE_RATE", 16000))
        phrase_timeout_s = _env_float("APP_STT_PHRASE_TIMEOUT_S", _env_float("STT_PHRASE_TIMEOUT_S", 1.0))

        dev_raw = _env("APP_STT_DEVICE", _env("STT_DEVICE", "")).strip()
        device = None
        if dev_raw:
            try:
                device = int(dev_raw)
            except Exception:
                device = None

        return SttConfig(
            enabled=enabled,
            model_path=model_path,
            sample_rate=sample_rate,
            device=device,
            phrase_timeout_s=phrase_timeout_s,
        )


@dataclass(frozen=True)
class EmbeddingsConfig:
    enabled: bool = True
    sqlite_path: str = "./.cache/embeddings.sqlite"

    @staticmethod
    def from_env() -> "EmbeddingsConfig":
        enabled = _env_bool("APP_EMBEDDINGS", _env_bool("EMBEDDINGS", True))
        sqlite_path = _env("APP_EMBED_CACHE_PATH", _env("EMBED_CACHE_PATH", "./.cache/embeddings.sqlite"))
        return EmbeddingsConfig(enabled=enabled, sqlite_path=sqlite_path)


@dataclass(frozen=True)
class KbConfig:
    enabled: bool = True
    sqlite_path: str = "./.cache/kb.sqlite"

    auto_ingest: bool = False
    ingest_interval_s: float = 0.5

    @staticmethod
    def from_env() -> "KbConfig":
        enabled = _env_bool("APP_KB", _env_bool("KB", True))
        sqlite_path = _env("APP_KB_PATH", _env("KB_PATH", "./.cache/kb.sqlite"))

        auto_ingest = _env_bool("APP_KB_AUTO_INGEST", _env_bool("KB_AUTO_INGEST", False))
        ingest_interval_s = _env_float("APP_KB_INGEST_INTERVAL_S", _env_float("KB_INGEST_INTERVAL_S", 0.5))

        return KbConfig(
            enabled=enabled,
            sqlite_path=sqlite_path,
            auto_ingest=auto_ingest,
            ingest_interval_s=ingest_interval_s,
        )


@dataclass(frozen=True)
class ExternalBridgesConfig:
    backend_rest_url: str = "http://127.0.0.1:8080"
    pi_rest_url: str = "http://127.0.0.1:8081"

    @staticmethod
    def from_env() -> "ExternalBridgesConfig":
        backend_rest_url = _env("APP_BACKEND_REST_URL", _env("BACKEND_REST_URL", "http://127.0.0.1:8080")).rstrip("/")
        pi_rest_url = _env("APP_PI_REST_URL", _env("PI_REST_URL", "http://127.0.0.1:8081")).rstrip("/")
        return ExternalBridgesConfig(backend_rest_url=backend_rest_url, pi_rest_url=pi_rest_url)


@dataclass(frozen=True)
class McpAppConfig:
    rest: McpRestConfig
    planner: PlannerServiceConfig
    stt: SttConfig
    embeddings: EmbeddingsConfig
    kb: KbConfig
    bridges: ExternalBridgesConfig

    @staticmethod
    def from_env() -> "McpAppConfig":
        return McpAppConfig(
            rest=McpRestConfig.from_env(),
            planner=PlannerServiceConfig.from_env(),
            stt=SttConfig.from_env(),
            embeddings=EmbeddingsConfig.from_env(),
            kb=KbConfig.from_env(),
            bridges=ExternalBridgesConfig.from_env(),
        )
