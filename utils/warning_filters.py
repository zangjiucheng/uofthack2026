"""
Central place to silence noisy third-party warnings.
Call configure_warning_filters() early in entrypoints.
"""
from __future__ import annotations

import warnings


def configure_warning_filters():
    # TIMM deprecations for older detectron2 dependencies
    warnings.filterwarnings(
        "ignore",
        message="Importing from timm.models.layers is deprecated",
        category=FutureWarning,
        module="timm.models.layers",
    )
    warnings.filterwarnings(
        "ignore",
        message="Importing from timm.models.helpers is deprecated",
        category=FutureWarning,
        module="timm.models.helpers",
    )
    warnings.filterwarnings(
        "ignore",
        message="Importing from timm.models.registry is deprecated",
        category=FutureWarning,
        module="timm.models.registry",
    )
    warnings.filterwarnings(
        "ignore",
        module="timm.models",
        category=FutureWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message="Specified provider 'CUDAExecutionProvider' is not in available provider names",
        category=UserWarning,
        module="onnxruntime.capi.onnxruntime_inference_collection",
    )
    warnings.filterwarnings(
        "ignore",
        message="pkg_resources is deprecated as an API",
        category=UserWarning,
        module="detectron2.model_zoo.model_zoo",
    )
    warnings.filterwarnings(
        "ignore",
        message="torch.meshgrid: in an upcoming release, it will be required to pass the indexing argument",
        category=UserWarning,
        module="torch.functional",
    )
