from __future__ import annotations

import os
import time
from typing import Any, Optional

from core.services import Service

from routes.rest_api import CommandRegistry, start_rest_server
from states.visual_states import VisualStateStore

from apps.services.mcp.config import McpAppConfig
from apps.services.mcp.runtime import start_runtime_loops, RuntimeLoops

from apps.services.mcp.stt.stt_service import SttService

from apps.services.mcp.embeddings.sqlite_cache import SqliteEmbeddingCache
from apps.services.mcp.embeddings.gemini_embedder import GeminiEmbedder

from apps.services.mcp.kb.kb_store import KbStore
from apps.services.mcp.kb.kb_service import KbService
from apps.services.mcp.kb.kb_ingest_service import KbIngestService

from apps.services.mcp.planner.planner_client import PlannerClient
from apps.services.mcp.llm.planner_service import start_planner_service

from apps.services.mcp.mcp.run_store import McpRunStore
from apps.services.mcp.mcp.executor import McpExecutor
from apps.services.mcp.mcp.mcp_service import McpService

from apps.services.mcp.api.routes import register_routes
from apps.services.mcp.api.tool_bridge import register_tool_handlers
from apps.services.mcp.api.safety import ToolSafetyPolicy, make_safe_tool_invoker, compute_allow_tools_from_registry


class HostMcpService(Service):
    name = "host_mcp"

    def __init__(self, ctx):
        self.ctx = ctx

        self.cfg = McpAppConfig.from_env()

        self.registry = CommandRegistry()
        self._rest_server: Optional[Any] = None
        self._runtime: Optional[RuntimeLoops] = None
        self._planner_server: Optional[Any] = None

        # services
        self.stt: Optional[SttService] = None
        self.embed_cache: Optional[SqliteEmbeddingCache] = None
        self.embedder: Optional[GeminiEmbedder] = None

        self.kb_store: Optional[KbStore] = None
        self.kb: Optional[KbService] = None
        self.kb_ingest: Optional[KbIngestService] = None

        self.planner_client: Optional[PlannerClient] = None
        self.mcp_store: Optional[McpRunStore] = None
        self.mcp_executor: Optional[McpExecutor] = None
        self.mcp_service: Optional[McpService] = None

    def _build(self) -> None:
        os.environ.setdefault("APP_BACKEND_REST_URL", self.cfg.bridges.backend_rest_url)
        os.environ.setdefault("APP_PI_REST_URL", self.cfg.bridges.pi_rest_url)

        if self.cfg.stt.enabled:
            self.stt = SttService(
                model_path=self.cfg.stt.model_path or None,
                sample_rate=self.cfg.stt.sample_rate,
                device=self.cfg.stt.device,
                phrase_timeout_s=self.cfg.stt.phrase_timeout_s,
            )

        if self.cfg.embeddings.enabled:
            self.embed_cache = SqliteEmbeddingCache(self.cfg.embeddings.sqlite_path)
            self.embedder = GeminiEmbedder(self.embed_cache)

        if self.cfg.kb.enabled:
            self.kb_store = KbStore(db_path=self.cfg.kb.sqlite_path)
            self.kb = KbService(store=self.kb_store, embedder=self.embedder)

            self.kb_ingest = KbIngestService(
                kb_service=self.kb,
                snapshot_provider=VisualStateStore.snapshot,
                interval_s=self.cfg.kb.ingest_interval_s,
            )

        self.planner_client = PlannerClient()

        register_tool_handlers(self.registry)

        self.mcp_store = McpRunStore()
        self.mcp_executor = McpExecutor(
            store=self.mcp_store,
            tool_invoker=make_safe_tool_invoker(self.registry, policy=ToolSafetyPolicy(allow_tools=None)),
            allow_tools=None,
            max_steps=20,
            per_step_timeout_s=20.0,
        )
        self.mcp_service = McpService(store=self.mcp_store, executor=self.mcp_executor, planner=self.planner_client)

        register_routes(
            self.registry,
            stt_service=self.stt,
            kb_service=self.kb,
            kb_ingest=self.kb_ingest,
            planner_client=self.planner_client,
            mcp_service=self.mcp_service,
            mcp_store=self.mcp_store,
            mcp_executor=self.mcp_executor,
            event_state=None,
        )

        allow_tools = compute_allow_tools_from_registry(self.registry)
        policy = ToolSafetyPolicy(allow_tools=allow_tools)
        safe_invoker = make_safe_tool_invoker(self.registry, policy=policy)
        self.mcp_executor.allow_tools = allow_tools
        self.mcp_executor.tool_invoker = safe_invoker

    def start(self) -> None:
        self._build()

        if self.cfg.rest.enabled:
            self._rest_server = start_rest_server(self.registry, host=self.cfg.rest.host, port=self.cfg.rest.port)
            print(f"[mcp] REST on http://{self.cfg.rest.host}:{self.cfg.rest.port}")

        if self.cfg.planner.enabled:
            self._planner_server = start_planner_service(host=self.cfg.planner.host, port=self.cfg.planner.port)

        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._runtime:
            self._runtime.stop()
            self._runtime = None

        if self._rest_server:
            try:
                self._rest_server.shutdown()
                self._rest_server.server_close()
            except Exception:
                pass
            self._rest_server = None

        if self._planner_server:
            try:
                self._planner_server.shutdown()
                self._planner_server.server_close()
            except Exception:
                pass
            self._planner_server = None

        if self.stt:
            try:
                self.stt.stop_listening()
            except Exception:
                pass
