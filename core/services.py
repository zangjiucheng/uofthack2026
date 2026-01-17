from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Callable, Dict, Iterator
import threading

from core.config import AppConfig


@dataclass
class ServiceContext:
    config: AppConfig


ServiceFactory = Callable[[ServiceContext], "Service"]


class ThreadManager:
    """Lightweight helper to start and track named daemon threads."""

    def __init__(self):
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, name: str, target: Callable, *, daemon: bool = True) -> threading.Thread:
        with self._lock:
            existing = self._threads.get(name)
            if existing and existing.is_alive():
                return existing
            thread = threading.Thread(target=target, daemon=daemon, name=name)
            self._threads[name] = thread
        thread.start()
        return thread

    def register(self, name: str, thread: threading.Thread) -> None:
        with self._lock:
            self._threads[name] = thread

    def get(self, name: str) -> threading.Thread | None:
        with self._lock:
            return self._threads.get(name)

    def is_running(self, name: str) -> bool:
        thread = self.get(name)
        return bool(thread and thread.is_alive())

    def join(self, name: str, timeout: float | None = 1.0) -> None:
        thread = self.get(name)
        if thread:
            thread.join(timeout=timeout)

    def join_all(self, timeout: float | None = 1.0) -> None:
        for name in list(self._threads.keys()):
            self.join(name, timeout)


class Service:
    name: str
    _thread_manager: ThreadManager | None = None

    @property
    def threads(self) -> ThreadManager:
        if self._thread_manager is None:
            self._thread_manager = ThreadManager()
        return self._thread_manager

    def start(self) -> None:  # pragma: no cover - interactive/long-running
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - optional clean-up hook
        """Optional hook for long-running services to shut down gracefully."""
        return


class ServiceRegistry:
    def __init__(self):
        self._factories: Dict[str, ServiceFactory] = {}

    def register(self, name: str, factory: ServiceFactory, *, overwrite: bool = False) -> None:
        if not overwrite and name in self._factories:
            raise ValueError(f"Service '{name}' already registered.")
        self._factories[name] = factory

    def create(self, name: str, ctx: ServiceContext) -> Service:
        if name not in self._factories:
            raise KeyError(f"Service '{name}' not registered.")
        return self._factories[name](ctx)

    def list(self) -> list[str]:
        return sorted(self._factories.keys())

    @contextmanager
    def started(self, name: str, ctx: ServiceContext) -> Iterator[Service]:
        """
        Convenience context manager: create + start + ensure stop().
        Useful in scripts/tests to avoid leaking background threads.
        """
        service = self.create(name, ctx)
        service.start()
        try:
            yield service
        finally:
            try:
                service.stop()
            except Exception:
                # Best-effort cleanup; callers can inspect/log separately.
                pass
