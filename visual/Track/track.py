import cv2
import time

# -------- Settings --------
CAM_INDEX = 0
FRAME_W, FRAME_H = 320, 240
TRACKER_KIND = "CSRT"   # "CSRT" or "KCF"
TARGET_AREA = 12000
Kp_turn = 0.7
EMA_ALPHA = 0.3
MIN_AREA = 60
MIN_INTERVAL = 0.1  # seconds between tracking updates (max 10 FPS)

def clamp(x, lo, hi): return lo if x < lo else hi if x > hi else x

def create_tracker(kind: str):
    k = kind.upper()
    if k == "CSRT":
        return cv2.legacy.TrackerCSRT_create()
    elif k == "KCF":
        return cv2.legacy.TrackerKCF_create()
    elif k == "MOSSE":
        return cv2.legacy.TrackerMOSSE_create()
    else:
        raise ValueError("TRACKER_KIND must be 'CSRT' or 'KCF'.")

def select_roi(frame):
    box = cv2.selectROI("track", frame, fromCenter=False, showCrosshair=True)
    cv2.waitKey(1)
    return box

class TrackerState:
    """Container for tracker runtime state so frames can be processed externally."""
    def __init__(self):
        self.tracker = None
        self.have_roi = False
        self.bbox = None
        self.last_seen = 0.0
        self.last_proc_ts = 0.0
        self.mx_s = None
        self.area_s = None
        self.err_x = None
        self.last_frame = None

def process_frame(
    frame,
    state: TrackerState,
    tracker_kind: str = TRACKER_KIND,
    ema_alpha: float = EMA_ALPHA,
    min_area: int = MIN_AREA,
    min_interval: float = MIN_INTERVAL,
    select_new_roi: bool = False,
):
    """
    Process a single frame with persistent state. Returns (annotated_frame, state).
    If select_new_roi is True, prompts ROI selection on this frame.
    """
    text_y = frame.shape[0] - 10

    # throttle tracking updates to reduce CPU; if throttled, reuse last rendered frame
    if min_interval > 0 and (time.time() - state.last_proc_ts) < min_interval and not select_new_roi:
        if state.last_frame is not None:
            return state.last_frame.copy(), state
        return frame, state

        if select_new_roi:
            box = select_roi(frame)
            if box is not None and box[2] > 0 and box[3] > 0:
                state.tracker = create_tracker(tracker_kind)
                roi = tuple(float(v) for v in box)
                ok_init = state.tracker.init(frame, roi)
                state.have_roi = bool(ok_init)
                state.bbox = roi
                state.mx_s, state.area_s, state.err_x = None, None, None
                state.last_seen = time.time()
    elif state.have_roi and state.tracker is not None:
        ok, bbox = state.tracker.update(frame)
        if ok:
            x, y, w, h = [int(v) for v in bbox]
            area = w * h
            if area >= min_area:
                mx = x + w / 2
                state.mx_s = mx if state.mx_s is None else (1 - ema_alpha) * state.mx_s + ema_alpha * mx
                state.area_s = area if state.area_s is None else (1 - ema_alpha) * state.area_s + ema_alpha * area

                cx = frame.shape[1] / 2
                err_x = (state.mx_s - cx) / cx
                state.err_x = err_x
                cv2.rectangle(frame, (x, y), (x + w, y + h), (80, 220, 80), 2)
                cv2.circle(frame, (int(state.mx_s), int(y + h / 2)), 3, (80, 220, 80), -1)
                txt = f"{tracker_kind} area={int(state.area_s)} errX={err_x:+.2f}"
                cv2.putText(frame, txt, (6, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1, cv2.LINE_AA)

                state.last_seen = time.time()
            else:
                state.err_x = None
                ok = False  # treat tiny boxes as lost

        if not ok:
            state.err_x = None
            if time.time() - state.last_seen > 3.0:
                pass
            cv2.putText(frame, "Lost... press 's' to reselect", (6, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,255), 1, cv2.LINE_AA)
    else:
        cv2.putText(frame, "Press 's' and drag to select target", (6, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1, cv2.LINE_AA)

    state.last_proc_ts = time.time()
    state.last_frame = frame.copy()
    return frame, state

def run_tracker(
    cam_index: int = CAM_INDEX,
    frame_size = (FRAME_W, FRAME_H),
    tracker_kind: str = TRACKER_KIND,
    ema_alpha: float = EMA_ALPHA,
    min_area: int = MIN_AREA,
):
    """Main tracking loop using the camera; callable from other modules."""
    frame_w, frame_h = frame_size
    cap = cv2.VideoCapture(cam_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  frame_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_h)

    state = TrackerState()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            k = cv2.waitKey(1) & 0xFF
            select_new_roi = k == ord('s')
            frame, state = process_frame(
                frame,
                state,
                tracker_kind=tracker_kind,
                ema_alpha=ema_alpha,
                min_area=min_area,
                select_new_roi=select_new_roi,
            )
            cv2.imshow("track", frame)
            if k == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_tracker()
