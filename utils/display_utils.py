import cv2
import numpy as np
from typing import Iterable, Optional, Tuple


def tile_frames(
    frames: Iterable[Optional[np.ndarray]],
    grid: Tuple[int, int] = (2, 2),
    cell_size: Optional[Tuple[int, int]] = None,
    labels: Optional[Iterable[str]] = None,
) -> np.ndarray:
    """
    Arrange frames into a grid (rows, cols) and return a single tiled image.
    Missing frames are filled with black. Frames are resized to cell_size, or
    to the size of the first non-None frame if cell_size is not provided.
    """
    rows, cols = grid
    frames_list = list(frames)
    frames_list += [None] * max(0, rows * cols - len(frames_list))
    labels_list = list(labels) if labels is not None else [None] * len(frames_list)
    labels_list += [None] * max(0, rows * cols - len(labels_list))

    # Decide cell size
    if cell_size is None:
        for f in frames_list:
            if f is not None:
                cell_size = (f.shape[1], f.shape[0])  # (w, h)
                break
    if cell_size is None:  # all None
        return np.zeros((rows * 100, cols * 100, 3), dtype=np.uint8)

    w, h = cell_size
    tiles = []
    for f, label in zip(frames_list[: rows * cols], labels_list[: rows * cols]):
        if f is None:
            tile = np.zeros((h, w, 3), dtype=np.uint8)
        else:
            tile = cv2.resize(f, (w, h))
            if tile.ndim == 2:
                tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        if label:
            _draw_label(tile, label)
        tiles.append(tile)

    row_imgs = []
    for r in range(rows):
        row_tiles = tiles[r * cols : (r + 1) * cols]
        row_imgs.append(np.hstack(row_tiles))

    return np.vstack(row_imgs)


def _draw_label(img: np.ndarray, text: str) -> None:
    """Draw a small label at top-left of the image."""
    cv2.rectangle(img, (0, 0), (140, 26), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
