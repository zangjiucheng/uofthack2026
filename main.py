import os
from core.config import AppConfig
from core.services import ServiceContext, ServiceRegistry


def framework(mode: str) -> None:
    cfg = AppConfig(platform=mode if mode in {"host", "pi"} else None)
    ctx = ServiceContext(cfg)
    registry = ServiceRegistry()

    if cfg.is_host():
        from apps.host_backend import HostBackendService
        registry.register(HostBackendService.name, HostBackendService)
        target = HostBackendService.name
    else:
        from apps.host_pi import PiRobotService
        registry.register(PiRobotService.name, PiRobotService)
        target = PiRobotService.name

    service = registry.create(target, ctx)
    print(f"[framework] Running service '{service.name}' for platform='{cfg.platform}'")
    service.start()


if __name__ == "__main__":
    app_mode = os.environ.get("APP_MODE", "backend").lower()
    if app_mode == "backend":
        framework("host")
    elif app_mode == "raspi":
        framework("pi")
    else:
        print("Unknown APP_MODE. Use 'backend' or 'raspi'.")
