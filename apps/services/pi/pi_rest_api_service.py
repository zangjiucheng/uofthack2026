from __future__ import annotations

import os

from core.services import Service
from routes.rest_api import CommandRegistry, start_rest_server
from states.raspi_states import TaskManager

class PiRestApiService(Service):
    """
    Minimal REST API for the Pi side to enqueue high-level tasks.
    Controlled by APP_PI_REST=1 (default: disabled).
    """

    name = "pi_rest_api"

    def __init__(self, task_manager: TaskManager):
        self._registry = CommandRegistry()
        self._server = None
        self.task_manager = task_manager

    def start(self):
        if self._server is not None:
            return
        if os.environ.get("PI_REST", "0") != "1":
            return

        def approach_object(payload):
            obj = (payload or {}).get("object")
            if not obj or not isinstance(obj, str):
                return {"ok": False, "error": "object (str) required"}
            task = {"kind": "approach", "target_type": "object", "target": obj}
            queued = self.task_manager.enqueue(task)
            print(f"[pi_rest_api] Enqueued approach_object task: {task}")
            return {"ok": queued, "task": task}

        def approach_person(payload):
            person = (payload or {}).get("name")
            if not person or not isinstance(person, str):
                return {"ok": False, "error": "name (str) required"}
            task = {"kind": "approach", "target_type": "person", "target": person}
            queued = self.task_manager.enqueue(task)
            print(f"[pi_rest_api] Enqueued approach_person task: {task}")
            return {"ok": queued, "task": task}

        self._registry.register("approach_object", approach_object)
        self._registry.register("approach_person", approach_person)

        host = os.environ.get("PI_REST_HOST", "0.0.0.0")
        port = int(os.environ.get("PI_REST_PORT", "8081"))
        self._server = start_rest_server(self._registry, host=host, port=port)

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
