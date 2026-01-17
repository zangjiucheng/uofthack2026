import os
import time
import threading
import queue
from enum import Enum

import cv2
from detectron2.utils.visualizer import Visualizer

from core.services import Service
from utils.display_utils import tile_frames
from visual.Face.face_id import FaceIDPipeline
from visual.Track.track import TrackerState, process_frame as track_process_frame, create_tracker, MIN_INTERVAL
from states.visual_states import (
    VisualStateStore,
    FaceState,
    FaceDetection,
    TrackState,
    DeticState,
    DeticDetection,
)
from states.video_stream import VideoFrameStore


class VideoMode(Enum):
    GRID = "grid"
    FACE_ONLY = "face_only"


class _DeticAsyncProcessor:
    """
    Background Detic processor that keeps the latest frame and runs inference
    without blocking the capture loop. Supports live vocabulary updates and
    manual trigger requests.
    """

    def __init__(self, show: bool, interval: float, stop_event: threading.Event):
        self._stop = stop_event
        self._interval = max(0.0, interval)
        self._show = show
        try:
            from visual.Detic.pipeline import DeticRunner
        except Exception as exc:
            # Raise a clear error so callers can gracefully fall back to a no-op pipeline.
            raise RuntimeError(f"Detic unavailable: {exc}") from exc

        self.runner = DeticRunner(object_list=None, visualize=False)
        self._frame_lock = threading.Lock()
        self._runner_lock = threading.Lock()
        self._latest_frame = None
        self._last_annotated = None
        self._last_run = 0.0
        self._force_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def submit(self, frame):
        with self._frame_lock:
            self._latest_frame = frame
            annotated = self._last_annotated
        return annotated if annotated is not None else frame

    def update_objects(self, object_list: list[str] | None, vocabulary: str, output_score_threshold: float):
        with self._runner_lock:
            self.runner.update_vocabulary(
                object_list=object_list,
                vocabulary=vocabulary,
                output_score_threshold=output_score_threshold,
            )
        with self._frame_lock:
            self._last_annotated = None
            self._force_event.set()

    def trigger_once(self) -> bool:
        with self._frame_lock:
            if self._latest_frame is None:
                return False
            self._force_event.set()
            return True

    def shutdown(self):
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _worker(self):
        while not self._stop.is_set():
            with self._frame_lock:
                frame = self._latest_frame
                last_run = self._last_run
                force = self._force_event.is_set()
            if frame is None:
                time.sleep(0.01)
                continue
            now = time.time()
            if not force and self._interval > 0 and now - last_run < self._interval:
                time.sleep(0.01)
                continue
            self._force_event.clear()
            try:
                with self._runner_lock:
                    outputs = self.runner._inference(self.runner.predictor, frame)  # type: ignore[attr-defined]
                    metadata = self.runner.metadata
                VisualStateStore.update(detic=_detic_state_from_outputs(outputs, metadata))
                annotated = frame
                if self._show:
                    v = Visualizer(frame[:, :, ::-1], metadata)
                    out = v.draw_instance_predictions(outputs["instances"].to("cpu"))
                    annotated = out.get_image()[:, :, ::-1]
                with self._frame_lock:
                    self._last_annotated = annotated
                    self._last_run = time.time()
            except Exception:
                time.sleep(0.1)


class StreamService(Service):
    """
    Handles the camera capture loop and CV pipelines (detic/face/track/all).
    """

    name = "stream"

    def __init__(self, event_state, stop_event: threading.Event | None = None):
        self.event_state = event_state
        self._stop = stop_event or threading.Event()
        self._face_pipeline = None
        self._face_record_only = False
        self._face_only_requested = False
        self._video_mode = VideoMode.GRID
        self._pending_track_roi: tuple[float, float, float, float] | None = None
        self._track_lock = threading.Lock()
        self._reset_track = False
        self._last_proc_ts = 0.0
        self._cleanup_source = None
        self._threads: list[threading.Thread] = []
        self._show = False
        self._detic_processor: _DeticAsyncProcessor | None = None

    @property
    def face_pipeline_available(self) -> bool:
        return self._face_pipeline is not None

    @property
    def video_mode(self) -> VideoMode:
        return self._video_mode

    def start(self):
        self._stop.clear()
        source = os.environ.get("APP_STREAM_SOURCE", "cap").lower()
        resize_factor = float(os.environ.get("APP_STREAM_RESIZE", "1.0"))
        resize_factor = min(1.0, max(0.2, resize_factor)) if resize_factor > 0 else 1.0
        max_fps = float(os.environ.get("APP_STREAM_MAX_FPS", "30"))
        min_proc_interval = 1.0 / max_fps if max_fps > 0 else 0.0

        get_frame, cleanup_source, source_desc = self._build_stream_source(source)
        process, pipeline_desc = self._build_stream_pipeline()
        self._cleanup_source = cleanup_source

        def run_process(frame):
            if (self._face_record_only or self._face_only_requested) and self._face_pipeline is not None:
                matches, annotated = self._face_pipeline.process_frame(frame, draw=True)
                VisualStateStore.update(face=_face_state_from_matches(matches))
                if self._face_record_only and not self._face_pipeline.is_enrolling():
                    self._face_record_only = False
                    if not self._face_only_requested:
                        self._video_mode = VideoMode.GRID
                return {"main": annotated, "face": annotated}
            return process(frame)

        print(f"[stream] Source: {source_desc}")
        print(f"[stream] Pipeline: {pipeline_desc}")
        print("[stream] Ctrl+C to stop.")

        frame_queue: queue.Queue = queue.Queue(maxsize=2)
        stop_flag = self._stop
        self._last_proc_ts = 0.0

        def capture_loop():
            while not stop_flag.is_set():
                frame = get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                if resize_factor != 1.0:
                    h, w = frame.shape[:2]
                    new_w = max(1, int(w * resize_factor))
                    new_h = max(1, int(h * resize_factor))
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                try:
                    frame_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                    frame_queue.put_nowait(frame)

        def process_loop():
            try:
                while not stop_flag.is_set():
                    try:
                        frame = frame_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if min_proc_interval > 0:
                        elapsed = time.time() - self._last_proc_ts
                        remaining = min_proc_interval - elapsed
                        if remaining > 0:
                            time.sleep(min(remaining, 0.02))
                            continue

                    result = run_process(frame)
                    views = result if isinstance(result, dict) else {"main": result}
                    views.setdefault("raw", frame)

                    if self._video_mode is VideoMode.FACE_ONLY:
                        face_view = views.get("face")
                        main_view = views.get("main")
                        single = face_view if face_view is not None else main_view if main_view is not None else frame
                        VideoFrameStore.set_frame(single)
                        grid = single
                    elif self._video_mode is VideoMode.GRID:
                        grid = tile_frames(
                            [
                                views.get("main"),
                                views.get("raw"),
                                views.get("face"),
                                views.get("track"),
                            ],
                            grid=(2, 2),
                            labels=["detic", "raw", "face", "track"],
                        )
                        VideoFrameStore.set_frame(grid)
                    else:
                        raise ValueError(f"Unknown video mode: {self._video_mode}")

                    if self._show:
                        cv2.imshow("backend_stream", grid)
                        if cv2.waitKey(1) & 0xFF == 27:
                            stop_flag.set()
                            break
                    self._last_proc_ts = time.time()
            except KeyboardInterrupt:
                stop_flag.set()

        capture_thread = threading.Thread(target=capture_loop, daemon=True)
        process_thread = threading.Thread(target=process_loop, daemon=True)
        self._threads = [capture_thread, process_thread]

        capture_thread.start()
        process_thread.start()

        try:
            while not stop_flag.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            stop_flag.set()
        finally:
            self._cleanup()

    def stop(self):
        self._stop.set()
        self._cleanup()

    def queue_face_enroll(self, name: str) -> bool:
        if not self._face_pipeline:
            return False
        self._face_pipeline.request_enroll(name)
        self._face_record_only = True
        self._face_only_requested = True
        self._video_mode = VideoMode.FACE_ONLY
        self.event_state.log_event("rest_face_record", name=name)
        return True

    def queue_face_update(self, person_id: int, name: str | None = None) -> bool:
        """Re-enroll a face with a specific id (optionally with a new label)."""
        if not self._face_pipeline:
            return False
        try:
            self._face_pipeline.request_reenroll(person_id, name)
            self._face_record_only = True
            self._face_only_requested = True
            self._video_mode = VideoMode.FACE_ONLY
            self.event_state.log_event("rest_face_update", id=person_id, name=name)
            return True
        except Exception:
            return False

    def delete_face(self, person_id: int) -> bool:
        if not self._face_pipeline:
            return False
        try:
            deleted = self._face_pipeline.delete_face(person_id)
            if deleted:
                self.event_state.log_event("rest_face_delete", id=person_id)
            return deleted
        except Exception:
            return False

    def list_faces(self) -> list[dict] | None:
        if not self._face_pipeline:
            return None
        try:
            return self._face_pipeline.list_faces()
        except Exception:
            return None

    def set_face_only(self, enabled: bool) -> bool:
        if enabled and not self._face_pipeline:
            return False
        self._face_only_requested = enabled
        self._video_mode = VideoMode.FACE_ONLY if enabled else VideoMode.GRID
        self.event_state.log_event("rest_face_only", enabled=enabled)
        return True

    def reset_face_db(self) -> bool:
        if not self._face_pipeline:
            return False
        try:
            self._face_pipeline.reset_db()
            self.event_state.log_event("rest_face_reset")
            return True
        except Exception:
            return False

    def set_track_roi(self, roi: tuple[float, float, float, float]):
        with self._track_lock:
            self._pending_track_roi = roi

    def request_track_reset(self):
        with self._track_lock:
            self._reset_track = True

    def _cleanup(self):
        stop_flag = self._stop
        stop_flag.set()
        if self._cleanup_source:
            try:
                self._cleanup_source()
            except Exception:
                pass
            self._cleanup_source = None
        if self._show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
            self._show = False
        for t in self._threads:
            t.join(timeout=1)
        self._threads = []
        self._video_mode = VideoMode.GRID
        self._face_record_only = False
        self._face_only_requested = False
        if self._detic_processor:
            self._detic_processor.shutdown()
            self._detic_processor = None

    def _build_stream_source(self, source: str):
        """
        Return (get_frame_fn, cleanup_fn, description).
        - cap: OpenCV camera capture (APP_STREAM_CAM_INDEX)
        - pi:  MJPEG stream from the Pi (APP_STREAM_URL, default http://127.0.0.1:9000/stream.mjpg)
        """
        if source == "cap":
            cam_index = int(os.environ.get("APP_STREAM_CAM_INDEX", 0))
            cap = cv2.VideoCapture(cam_index)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            def get_frame():
                ok, frame = cap.read()
                return frame if ok else None

            def cleanup():
                cap.release()

            return get_frame, cleanup, f"OpenCV camera index {cam_index}"

        if source == "pi":
            url = os.environ.get("APP_STREAM_URL", "http://127.0.0.1:9000/stream.mjpg")
            cap = cv2.VideoCapture(url)
            fail_count = 0
            retry_threshold = 10
            last_log = 0.0
            last_discover = 0.0
            discover_hosts = ["127.0.0.1", "localhost", "192.168.0.10", "192.168.1.10"]
            base_path = os.environ.get("APP_STREAM_PATH", "/stream.mjpg")

            def get_frame_url():
                nonlocal cap, fail_count, last_log, last_discover, url
                ok, frame = cap.read()
                if ok and frame is not None:
                    fail_count = 0
                    return frame
                fail_count += 1
                now = time.time()
                if now - last_discover >= 1.0:
                    last_discover = now
                    for host in discover_hosts:
                        candidate = f"http://{host}:9000{base_path}"
                        test = cv2.VideoCapture(candidate)
                        ok_test, frame_test = test.read()
                        if ok_test and frame_test is not None:
                            print(f"[stream] Switched Pi stream to {candidate}")
                            try:
                                cap.release()
                            except Exception:
                                pass
                            cap = test
                            url = candidate
                            fail_count = 0
                            return frame_test
                        test.release()
                if fail_count >= retry_threshold:
                    if now - last_log > 1.0:
                        print(f"[stream] Pi stream unavailable (failed {fail_count} reads); retrying open...")
                        last_log = now
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = cv2.VideoCapture(url)
                    fail_count = 0
                elif now - last_log > 5.0:
                    # Log occasional failures without spamming.
                    print(f"[stream] Waiting for Pi stream from {url}...")
                    last_log = now
                return None

            def cleanup_url():
                cap.release()

            return get_frame_url, cleanup_url, f"MJPEG stream {url}"

        raise ValueError(f"Unknown stream source: {source}")

    def _build_stream_pipeline(self):
        """
        Return (process_fn, description).
        process_fn(frame) -> annotated frame or None
        """
        face = FaceIDPipeline()
        self._face_pipeline = face
        state = TrackerState()
        tracker = create_tracker("CSRT")
        auto_roi = os.environ.get("APP_TRACK_AUTO_ROI", "0") == "1"
        track_min_interval = float(os.environ.get("APP_TRACK_MIN_INTERVAL", str(MIN_INTERVAL)))
        roi_set = False

        detic_interval = float(os.environ.get("APP_DETIC_INTERVAL", "4"))
        detic_submit = self._build_detic_async_processor(show=True, interval=detic_interval)

        if detic_submit is None:
            print("[stream] Detic unavailable; running face + track only.")

            def process(frame):
                nonlocal roi_set
                track_frame = frame.copy()
                pending = self._pop_track_roi()
                if pending:
                    tracker_local = create_tracker("CSRT")
                    ok = tracker_local.init(track_frame, pending)
                    state.tracker = tracker_local if ok else state.tracker
                    state.have_roi = bool(ok)
                    state.bbox = pending if ok else state.bbox
                    state.last_seen = time.time()
                with self._track_lock:
                    if self._reset_track:
                        state.tracker = None
                        state.have_roi = False
                        state.bbox = None
                        self._reset_track = False
                if auto_roi and not roi_set:
                    h, w = track_frame.shape[:2]
                    roi_w, roi_h = int(w * 0.4), int(h * 0.4)
                    x, y = (w - roi_w) // 2, (h - roi_h) // 2
                    roi = (float(x), float(y), float(roi_w), float(roi_h))
                    if tracker.init(track_frame, roi):
                        state.tracker = tracker
                        state.have_roi = True
                        state.bbox = roi
                        roi_set = True
                track_frame, _ = track_process_frame(track_frame, state, select_new_roi=False, min_interval=track_min_interval)
                VisualStateStore.update(track=_track_state_from_tracker(state))

                matches, face_frame = face.process_frame(frame, draw=True)
                VisualStateStore.update(face=_face_state_from_matches(matches))

                return {
                    "main": frame,
                    "face": face_frame,
                    "track": track_frame,
                }

            return process, "Face + Track pipeline (detic unavailable)"

        def process(frame):
            nonlocal roi_set
            track_frame = frame.copy()
            pending = self._pop_track_roi()
            if pending:
                tracker_local = create_tracker("CSRT")
                ok = tracker_local.init(track_frame, pending)
                state.tracker = tracker_local if ok else state.tracker
                state.have_roi = bool(ok)
                state.bbox = pending if ok else state.bbox
                state.last_seen = time.time()
            with self._track_lock:
                if self._reset_track:
                    state.tracker = None
                    state.have_roi = False
                    state.bbox = None
                    self._reset_track = False
            if auto_roi and not roi_set:
                h, w = track_frame.shape[:2]
                roi_w, roi_h = int(w * 0.4), int(h * 0.4)
                x, y = (w - roi_w) // 2, (h - roi_h) // 2
                roi = (float(x), float(y), float(roi_w), float(roi_h))
                if tracker.init(track_frame, roi):
                    state.tracker = tracker
                    state.have_roi = True
                    state.bbox = roi
                    roi_set = True
            track_frame, _ = track_process_frame(track_frame, state, select_new_roi=False, min_interval=track_min_interval)
            VisualStateStore.update(track=_track_state_from_tracker(state))

            matches, face_frame = face.process_frame(frame, draw=True)
            VisualStateStore.update(face=_face_state_from_matches(matches))

            detic_frame = detic_submit(frame)

            return {
                "main": detic_frame,
                "face": face_frame,
                "track": track_frame,
            }

        return process, "All pipelines (track + face + detic)"

    def _build_detic_async_processor(self, show: bool, interval: float):
        """
        Run Detic in a background thread so the capture loop never blocks.
        Returns a submit(frame) -> latest_annotated_frame function.
        """
        if self._detic_processor:
            self._detic_processor.shutdown()
        try:
            self._detic_processor = _DeticAsyncProcessor(show=show, interval=interval, stop_event=self._stop)
        except Exception as exc:
            print(f"[stream] Detic init failed; disabling detic pipeline. Error: {exc}")
            self._detic_processor = None
            return None

        def submit(frame):
            if not self._detic_processor:
                return frame
            return self._detic_processor.submit(frame)

        return submit

    def _pop_track_roi(self):
        with self._track_lock:
            roi = self._pending_track_roi
            self._pending_track_roi = None
            return roi

    def update_detic_object_list(
        self,
        object_list: list[str] | None,
        vocabulary: str = "lvis",
        output_score_threshold: float = 0.3,
    ) -> tuple[bool, str | None]:
        if not self._detic_processor:
            return False, "detic pipeline not active"
        try:
            self._detic_processor.update_objects(
                object_list=object_list,
                vocabulary=vocabulary,
                output_score_threshold=output_score_threshold,
            )
            self.event_state.log_event(
                "rest_detic_update",
                object_list=object_list,
                vocabulary=vocabulary,
                score_threshold=output_score_threshold,
            )
            return True, None
        except Exception as exc:
            return False, str(exc)

    def trigger_detic_once(self) -> tuple[bool, str | None]:
        if not self._detic_processor:
            return False, "detic pipeline not active"
        triggered = self._detic_processor.trigger_once()
        if not triggered:
            return False, "no frame available to run detic"
        self.event_state.log_event("rest_detic_trigger")
        return True, None


def _face_state_from_matches(matches):
    faces = []
    for m in matches or []:
        bbox = tuple(int(v) for v in m.get("bbox", (0, 0, 0, 0)))
        faces.append(FaceDetection(bbox=bbox, label=m.get("label", ""), sim=float(m.get("sim", 0.0))))
    return FaceState(ts=time.time(), faces=faces)


def _track_state_from_tracker(state: TrackerState):
    bbox = tuple(float(v) for v in state.bbox) if state.bbox is not None else None
    return TrackState(
        ts=time.time(),
        bbox=bbox,
        area=state.area_s,
        center_x=state.mx_s,
    )


def _detic_state_from_outputs(outputs, metadata):
    try:
        inst = outputs["instances"].to("cpu")
        classes = inst.pred_classes.tolist() if hasattr(inst, "pred_classes") else []
        scores = inst.scores.tolist() if hasattr(inst, "scores") else []
        boxes = inst.pred_boxes.tensor.tolist() if hasattr(inst, "pred_boxes") else []
        detections = []
        for idx, (cls_idx, score) in enumerate(zip(classes, scores)):
            label = metadata.thing_classes[cls_idx] if hasattr(metadata, "thing_classes") else str(cls_idx)
            bbox = None
            if boxes and idx < len(boxes):
                x1, y1, x2, y2 = boxes[idx]
                bbox = (float(x1), float(y1), float(x2), float(y2))
            detections.append(DeticDetection(label=label, score=float(score), bbox=bbox))
        return DeticState(ts=time.time(), detections=detections[:10])
    except Exception:
        return DeticState(ts=time.time(), detections=[])
