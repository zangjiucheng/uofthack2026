import os
__all__ = []

if os.environ.get("APP_MODE", "").lower() == "raspi":
    from .pi import PiStateWSService, CamStreamingService

    __all__.extend(
        [
            "PiStateWSService",
            "CamStreamingService",
        ]
    )

if os.environ.get("APP_MODE", "").lower() == "backend":
    from .backend import (
        BackendTeleopService,
        PS2ListenerService,
        RestApiService,
        StreamService,
        VideoMode,
        WebsocketService,
    )

    __all__.extend(
        [
            "BackendTeleopService",
            "PS2ListenerService",
            "RestApiService",
            "StreamService",
            "VideoMode",
            "WebsocketService",
        ]
    )
