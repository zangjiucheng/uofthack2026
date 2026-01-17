# import some common libraries
import sys
import os
import json
import random
import uuid
import time
from pathlib import Path
from typing import Tuple, Any

import cv2
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

import torch
import detectron2

# import some common detectron2 utilities
from detectron2 import model_zoo
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.utils.visualizer import Visualizer
from detectron2.data import MetadataCatalog, DatasetCatalog
from detectron2.data.catalog import Metadata

# Custom utilities
from importlib.machinery import SourceFileLoader


def initialize_detic():
    print("torch:", torch.__version__)
    print("cuda available:", torch.cuda.is_available())
    print("mps available:", torch.backends.mps.is_available())
    print("detectron2:", detectron2.__version__)

    # Setup detectron2 logger
    from detectron2.utils.logger import setup_logger
    setup_logger()

    # Running under the Detic repo
    SCRIPT_DIR = Path(__file__).resolve().parent
    os.chdir(SCRIPT_DIR)

    # Setup Detic PATHS
    sys.path.insert(0, str(SCRIPT_DIR))  # to import local detic package
    sys.path.insert(0, str(SCRIPT_DIR / 'third_party' / 'CenterNet2'))


initialize_detic()

# Detic libraries
try:
    from centernet.config import add_centernet_config
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "centernet package not found. Ensure third_party/CenterNet2 is cloned "
        "and on sys.path (git submodule update --init --recursive)."
    ) from exc

from detic.config import add_detic_config
from detic.modeling.utils import reset_cls_test
from detic.modeling.text.text_encoder import build_text_encoder


def cv2_imshow(a):
    """A replacement for cv2.imshow() for use in Jupyter notebooks."""
    if a.ndim == 2:
        plt.imshow(a, cmap="gray", vmin=0, vmax=255)
    else:
        plt.imshow(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))
    plt.axis("off")
    plt.show()


class DeticRunner:
    """Reusable, single-initialization Detic runner."""

    def __init__(
        self,
        object_list: list[str] | None = None,
        vocabulary: str = "lvis",
        visualize: bool = False,
        output_score_threshold: float = 0.3,
    ):
        self.visualize_default = visualize
        self._text_encoder = None
        self._custom_meta_name = "detic_custom_runtime"
        self.predictor = self._build_detic()
        self.predictor, self.metadata = self._configure_detic(
            self.predictor,
            object_list=object_list,
            vocabulary=vocabulary,
            output_score_threshold=output_score_threshold,
        )

    def run_image(
        self,
        image: Any,
        visualize: bool | None = None,
    ) -> Tuple[dict, Metadata, float]:
        vis = self.visualize_default if visualize is None else visualize
        start_time = time.time()
        outputs = self._inference(self.predictor, image)
        elapsed = time.time() - start_time
        if vis:
            self._visualize(image, outputs, self.metadata)
        return outputs, self.metadata, elapsed

    def run_image_path(
        self,
        image_path: str,
        visualize: bool | None = None,
    ) -> Tuple[dict, Metadata, float]:
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Unable to read image at {image_path}")
        return self.run_image(image, visualize=visualize)

    def update_vocabulary(
        self,
        object_list: list[str] | None = None,
        vocabulary: str = "lvis",
        output_score_threshold: float = 0.3,
    ) -> None:
        self.predictor, self.metadata = self._configure_detic(
            self.predictor,
            object_list=object_list,
            vocabulary=vocabulary,
            output_score_threshold=output_score_threshold,
        )

    def _build_detic(self):
        cfg = get_cfg()
        add_centernet_config(cfg)
        add_detic_config(cfg)
        cfg.merge_from_file("configs/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.yaml")
        cfg.MODEL.WEIGHTS = 'https://dl.fbaipublicfiles.com/detic/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth'
        cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.5
        cfg.MODEL.ROI_BOX_HEAD.ZEROSHOT_WEIGHT_PATH = 'rand'
        cfg.MODEL.ROI_HEADS.ONE_CLASS_PER_PROPOSAL = True
        cfg.MODEL.DEVICE = 'cpu'
        return DefaultPredictor(cfg)

    def _get_clip_embeddings(self, vocabulary, prompt='a '):
        if self._text_encoder is None:
            encoder = build_text_encoder(pretrain=True)
            encoder.eval()
            self._text_encoder = encoder
        texts = [prompt + x for x in vocabulary]
        with torch.no_grad():
            emb = self._text_encoder(texts).detach().permute(1, 0).contiguous().cpu()
        return emb

    def _configure_detic(
        self,
        predictor: DefaultPredictor,
        object_list: list[str] | None = None,
        vocabulary: str = 'lvis',
        output_score_threshold: float = 0.3,
    ) -> Tuple[DefaultPredictor, Metadata]:
        BUILDIN_CLASSIFIER = {
            'lvis': 'datasets/metadata/lvis_v1_clip_a+cname.npy',
            'objects365': 'datasets/metadata/o365_clip_a+cnamefix.npy',
            'openimages': 'datasets/metadata/oid_clip_a+cname.npy',
            'coco': 'datasets/metadata/coco_clip_a+cname.npy',
        }

        BUILDIN_METADATA_PATH = {
            'lvis': 'lvis_v1_val',
            'objects365': 'objects365_v2_val',
            'openimages': 'oid_val_expanded',
            'coco': 'coco_2017_val',
        }

        if object_list:
            metadata = self._build_metadata(object_list)
            classifier = self._get_clip_embeddings(metadata.thing_classes)
            num_classes = len(metadata.thing_classes)
            reset_cls_test(predictor.model, classifier, num_classes)
            for cascade_stages in range(len(predictor.model.roi_heads.box_predictor)):
                predictor.model.roi_heads.box_predictor[cascade_stages].test_score_thresh = output_score_threshold
        else:
            metadata = MetadataCatalog.get(BUILDIN_METADATA_PATH[vocabulary])
            classifier = BUILDIN_CLASSIFIER[vocabulary]
            num_classes = len(metadata.thing_classes)
            reset_cls_test(predictor.model, classifier, num_classes)

        return predictor, metadata

    def _build_metadata(self, object_list: list[str]) -> Metadata:
        metadata = MetadataCatalog.get(self._custom_meta_name)
        metadata.thing_classes = object_list
        return metadata

    def _inference(self, predictor: DefaultPredictor, image: Any):
        return predictor(image)

    def _visualize(self, im: Any, outputs: dict, metadata: Metadata):
        v = Visualizer(im[:, :, ::-1], metadata)
        out = v.draw_instance_predictions(outputs["instances"].to("cpu"))
        cv2_imshow(out.get_image()[:, :, ::-1])

    def _print_detic_results(self, outputs: dict, metadata: Metadata):
        print(outputs["instances"].pred_classes)
        print([metadata.thing_classes[x] for x in outputs["instances"].pred_classes.cpu().tolist()])
        print(outputs["instances"].scores)
        print(outputs["instances"].pred_boxes)


def run_detic_image(
    image_path: str,
    object_list: list[str] | None = None,
    vocabulary: str = "lvis",
    visualize: bool = False,
) -> Tuple[dict, Metadata, float]:
    """
    Convenience wrapper: loads an image, builds/sets up Detic, runs inference.
    Returns (outputs, metadata, inference_seconds).
    """
    runner = DeticRunner(object_list=object_list, vocabulary=vocabulary, visualize=visualize)
    outputs, metadata, elapsed = runner.run_image_path(image_path)
    runner._print_detic_results(outputs, metadata)
    print(f"Inference time: {elapsed:.2f} seconds")
    return outputs, metadata, elapsed


if __name__ == "__main__":
    # Example usage; adjust image path or vocabulary as needed.
    run_detic_image("image.png", visualize=True)
