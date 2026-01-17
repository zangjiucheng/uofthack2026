from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class AppConfig:
    """
    Shared config: knows repo root, image dir, and platform role.
    APP_PLATFORM: "host" (laptop backend) or "pi" (Raspberry Pi pipeline) or "mcp" (MCP controller)
    """

    root: Path
    platform: str

    def __init__(self, platform: str | None = None):
        self.root = Path(__file__).resolve().parent.parent
        self.platform = platform or os.environ.get("APP_PLATFORM", "host").lower()

    def is_host(self) -> bool:
        return self.platform == "host"

    def is_pi(self) -> bool:
        return self.platform == "pi"

    def is_mcp(self) -> bool:
        return self.platform == "mcp"
