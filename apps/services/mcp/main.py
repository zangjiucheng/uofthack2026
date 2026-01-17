from __future__ import annotations

import time

from .config import McpAppConfig
from .container import McpContainer


def main() -> int:
    cfg = McpAppConfig.from_env()
    container = McpContainer.build(cfg)
    container.start()

    print("")
    print("[mcp] running")
    print(f"[mcp] MCP REST  : http://{cfg.rest.host}:{cfg.rest.port}")
    print(f"[mcp] Planner   : http://{cfg.planner.host}:{cfg.planner.port}/plan")
    print("")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        container.stop()

    print("[mcp] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
