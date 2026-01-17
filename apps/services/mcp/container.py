from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from routes.rest_api import CommandRegistry, start_rest_server
from states.visual_states import VisualStateStore

from .config import McpAppConfig
from .runtime import RuntimeLoops, start_runtime_loops

from .stt.stt_service import SttService

from .embeddings.sqlite_cache import SqliteEmbeddingCache
from .embeddings.gemini_embedder import GeminiEmbedder

from .kb.kb_store import KbStore
from .kb.kb_service import KbService
from .kb.kb_ingest_service import KbIngestService

from .planner.planner_client import PlannerClient

from .mcp.run_store import McpRunStore
from .mcp.executor import McpExecutor
from .mcp.mcp_service import McpService

from .api.routes import register_routes
from .api.tool_bridge import register_tool_handlers
from .api.safety import ToolSafetyPolicy, make_safe_tool_invoker, compute_allow_tools_from_registry

from .llm.planner_service import start_planner_service


@dataclass
class McpContainer:
    cfg: McpAppConfig

    registry: CommandRegistry
    rest_server: Optional[Any] = None
    planner_http_server: Optional[Any] = None
    runtime: Optional[RuntimeLoops] = None

    stt: Optional[SttService] = None
    embed_cache: Optional[SqliteEmbeddingCache] = None
    embedder: Optional[GeminiEmbedder] = None

    kb_store: Optional[KbStore] = None
    kb: Optional[KbService] = None
    kb_ingest: Optional[KbIngestService] = None

    planner_client: Optional[PlannerClient] = None

    mcp_store: Optional[McpRunStore] = None
    mcp_executor: Optional[McpExecutor] = None
    mcp_service: Optional[McpService] = None

    @staticmethod
    def build(cfg: McpAppConfig) -> "McpContainer":
        os.environ.setdefault("APP_BACKEND_REST_URL", cfg.bridges.backend_rest_url)
        os.environ.setdefault("APP_PI_REST_URL", cfg.bridges.pi_rest_url)

        registry = CommandRegistry()
        c = McpContainer(cfg=cfg, registry=registry)

        if cfg.stt.enabled:
            c.stt = SttService(
                model_path=cfg.stt.model_path or None,
                sample_rate=cfg.stt.sample_rate,
                device=cfg.stt.device,
                phrase_timeout_s=cfg.stt.phrase_timeout_s,
            )

        if cfg.embeddings.enabled:
            c.embed_cache = SqliteEmbeddingCache(cfg.embeddings.sqlite_path)
            c.embedder = GeminiEmbedder(c.embed_cache)

        if cfg.kb.enabled:
            c.kb_store = KbStore(db_path=cfg.kb.sqlite_path)
            c.kb = KbService(store=c.kb_store, embedder=c.embedder)
            c.kb_ingest = KbIngestService(
                kb_service=c.kb,
                snapshot_provider=VisualStateStore.snapshot,
                interval_s=cfg.kb.ingest_interval_s,
            )

        c.planner_client = PlannerClient()

        register_tool_handlers(registry)

        c.mcp_store = McpRunStore()
        c.mcp_executor = McpExecutor(
            store=c.mcp_store,
            tool_invoker=make_safe_tool_invoker(registry, policy=ToolSafetyPolicy(allow_tools=None)),
            allow_tools=None,
            max_steps=20,
            per_step_timeout_s=20.0,
        )
        c.mcp_service = McpService(store=c.mcp_store, executor=c.mcp_executor, planner=c.planner_client)

        register_routes(
            registry,
            stt_service=c.stt,
            kb_service=c.kb,
            kb_ingest=c.kb_ingest,
            planner_client=c.planner_client,
            mcp_service=c.mcp_service,
            mcp_store=c.mcp_store,
            mcp_executor=c.mcp_executor,
            event_state=None,
        )

        allow_tools = compute_allow_tools_from_registry(registry)
        policy = ToolSafetyPolicy(allow_tools=allow_tools)
        safe_invoker = make_safe_tool_invoker(registry, policy=policy)
        c.mcp_executor.allow_tools = allow_tools
        c.mcp_executor.tool_invoker = safe_invoker

        return c

    def start(self) -> None:
        if self.cfg.planner.enabled:
            self.planner_http_server = start_planner_service(
                host=self.cfg.planner.host,
                port=self.cfg.planner.port,
            )

        # Start MCP REST
        if self.cfg.rest.enabled:
            self.rest_server = start_rest_server(self.registry, host=self.cfg.rest.host, port=self.cfg.rest.port)

    def stop(self) -> None:
        # Stop background loops first
        if self.runtime:
            try:
                self.runtime.stop()
            except Exception:
                pass
            self.runtime = None

        # Stop MCP REST
        if self.rest_server:
            try:
                self.rest_server.shutdown()
                self.rest_server.server_close()
            except Exception:
                pass
            self.rest_server = None

        # Stop planner_service
        if self.planner_http_server:
            try:
                self.planner_http_server.shutdown()
                self.planner_http_server.server_close()
            except Exception:
                pass
            self.planner_http_server = None

        # Stop STT
        if self.stt:
            try:
                self.stt.stop_listening()
            except Exception:
                pass
