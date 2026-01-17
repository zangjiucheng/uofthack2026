from dataclasses import dataclass, field
from pathlib import Path
import time
import os
import numpy as np
import cv2
import insightface
import warnings

# Silence deprecated estimate() warning from insightface/face_align.
warnings.filterwarnings(
    "ignore",
    message="`estimate` is deprecated since version 0.26",
    category=FutureWarning,
)

DISPLAY_SIM_THRESHOLD = 6  # Only render/deliver matches above this similarity


@dataclass
class FaceIDConfig:
    insight_model: str = "buffalo_sc"  # buffalo_sc / buffalo_s / buffalo_l / antelopev2
    db_path: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "faces_db.npz")
    cam: int = 0
    width: int = 640
    height: int = 480
    det_size: tuple[int, int] = (640, 640)
    sim_th: float = 0.65
    enroll_samples: int = 25
    enroll_delay: float = 0.03
    min_interval: float = 1.0  # seconds between detections to save CPU


def l2_normalize(x: np.ndarray, axis: int = 1, eps: float = 1e-12) -> np.ndarray:
    n = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / (n + eps)


class FaceDB:
    def __init__(self, path: str):
        self.path = path
        self.ids: list[int] = []
        self.labels: list[str] = []
        self.embeddings = None  # shape: (N, D), normalized

        if os.path.exists(path):
            data = np.load(path, allow_pickle=True)
            self.labels = list(data.get("labels", []))
            self.embeddings = data["embeddings"].astype(np.float32)
            if "ids" in data:
                self.ids = [int(x) for x in data["ids"]]
            else:
                self.ids = list(range(len(self.labels)))
        else:
            self.ids = []
            self.embeddings = None

    def save(self):
        labels_arr = np.array(self.labels, dtype=object)
        ids_arr = np.array(self.ids, dtype=np.int32)
        emb = self.embeddings if self.embeddings is not None else np.zeros((0, 1), dtype=np.float32)
        np.savez(self.path, ids=ids_arr, labels=labels_arr, embeddings=emb)

    def next_id(self) -> int:
        return (max(self.ids) + 1) if self.ids else 0

    def get_label(self, person_id: int) -> str | None:
        """Return the stored label for a person id, if present."""
        if person_id in self.ids:
            return self.labels[self.ids.index(person_id)]
        return None

    def add_or_update(self, person_id: int, label: str, embedding: np.ndarray):
        if self.embeddings is None or self.embeddings.shape[0] == 0:
            self.ids = [person_id]
            self.labels = [label]
            self.embeddings = embedding.reshape(1, -1).astype(np.float32)
            return

        if person_id in self.ids:
            idx = self.ids.index(person_id)
            self.labels[idx] = label
            self.embeddings[idx] = embedding.astype(np.float32)
        else:
            self.ids.append(person_id)
            self.labels.append(label)
            self.embeddings = np.vstack([self.embeddings, embedding.reshape(1, -1).astype(np.float32)])

    def delete(self, person_id: int) -> bool:
        """Remove a face by id. Returns True if deleted."""
        if person_id not in self.ids:
            return False
        idx = self.ids.index(person_id)
        self.ids.pop(idx)
        self.labels.pop(idx)
        if self.embeddings is not None and self.embeddings.shape[0] > idx:
            mask = np.ones(self.embeddings.shape[0], dtype=bool)
            mask[idx] = False
            self.embeddings = self.embeddings[mask]
            if self.embeddings.shape[0] == 0:
                self.embeddings = None
        self.save()
        return True

    def list_faces(self) -> list[dict]:
        """Return lightweight metadata for all faces."""
        faces = []
        for pid, label in zip(self.ids, self.labels):
            faces.append({"id": int(pid), "label": str(label)})
        return faces

    def match(self, embedding: np.ndarray, sim_threshold: float) -> tuple[int, str, float]:
        if self.embeddings is None or self.embeddings.shape[0] == 0:
            return -1, "Unknown", 0.0

        sims = self.embeddings @ embedding.reshape(-1, 1)
        sims = sims.reshape(-1)
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        if best_sim >= sim_threshold:
            return self.ids[best_idx], self.labels[best_idx], best_sim
        return -1, "Unknown", best_sim

    def count(self) -> int:
        return len(self.ids)

    def reset(self):
        """Clear all enrolled faces and delete the DB file."""
        self.ids = []
        self.labels = []
        self.embeddings = None
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


class InsightFaceWrapper:
    def __init__(self, model_name: str, det_size: tuple[int, int]):
        self.app = insightface.app.FaceAnalysis(name=model_name)
        self.app.prepare(ctx_id=-1, det_size=det_size)  # CPU

    def detect_and_embed(self, frame_bgr: np.ndarray):
        faces = self.app.get(frame_bgr)
        if not faces:
            return None, []
        best = max(faces, key=lambda f: getattr(f, "det_score", 0.0))
        return best, faces


class FaceIDPipeline:
    def __init__(self, config: FaceIDConfig | None = None):
        import os

        self.cfg = config or FaceIDConfig(
            min_interval=float(os.environ.get("APP_FACE_MIN_INTERVAL", FaceIDConfig.min_interval))
        )
        self.db = FaceDB(str(self.cfg.db_path))
        self.model = InsightFaceWrapper(self.cfg.insight_model, self.cfg.det_size)
        self._last_matches = []
        self._last_ts = 0.0
        self._pending_enroll: dict[str, int | str | None] | None = None
        self._enroll_message = None

    def process_frame(self, frame_bgr: np.ndarray, draw: bool = True):
        """
        Process a single BGR frame and return (matches, annotated_frame).
        matches: list of dicts with bbox, id, label, sim.
        """
        now = time.time()
        annotated = frame_bgr.copy() if draw else frame_bgr

        if now - self._last_ts < self.cfg.min_interval and self._last_matches:
            # Reuse last matches; just redraw to current frame if needed.
            if draw:
                for m in self._last_matches:
                    bbox = m["bbox"]
                    pid, label, sim = m["id"], m["label"], m["sim"]
                    x1, y1, x2, y2 = bbox
                    color = (0, 255, 0) if label != "Unknown" else (0, 0, 255)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                    id_part = f"ID {pid}" if pid >= 0 else "Unknown"
                    text = f"{id_part} {label}  sim={sim:.2f}"
                    cv2.putText(
                        annotated,
                        text,
                        (x1, max(20, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        2,
                    )
            return self._last_matches, annotated

        matches = []
        _, faces = self.model.detect_and_embed(frame_bgr)
        for f in faces:
            emb = f.embedding.astype(np.float32)
            pid, label, sim = self.db.match(emb, self.cfg.sim_th)
            bbox = tuple(map(int, f.bbox))
            if sim < DISPLAY_SIM_THRESHOLD:
                pid, label = -1, "Unknown"
            matches.append({"bbox": bbox, "id": pid, "label": label, "sim": sim})

            if draw:
                x1, y1, x2, y2 = bbox
                color = (0, 255, 0) if label != "Unknown" else (0, 0, 255)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                id_part = f"ID {pid}" if pid >= 0 else "Unknown"
                text = f"{id_part} {label}  sim={sim:.2f}"
                cv2.putText(annotated, text, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        self._last_matches = matches
        self._last_ts = now

        if self._pending_enroll and faces:
            # Take the first detected face to enroll or update
            face = faces[0]
            pending = self._pending_enroll
            self._pending_enroll = None
            name = pending.get("name")
            person_id = pending.get("id")
            if person_id is None:
                person_id = self.db.next_id()
            existing = person_id in self.db.ids
            if not name:
                name = self.db.get_label(person_id) or f"ID {person_id}"
            emb = face.embedding.astype(np.float32)
            emb = l2_normalize(emb.reshape(1, -1), axis=1)[0]
            self.db.add_or_update(person_id, str(name), emb)
            self.db.save()
            action = "Updated" if existing else "Enrolled"
            self._enroll_message = f"{action} {name} (ID {person_id})"
        if draw and self._enroll_message:
            cv2.putText(
                annotated,
                self._enroll_message,
                (10, annotated.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            self._enroll_message = None

        return matches, annotated

    def request_enroll(self, name: str, person_id: int | None = None):
        """Queue a new enrollment (or update if id exists)."""
        self._pending_enroll = {"name": name, "id": person_id}

    def request_reenroll(self, person_id: int, name: str | None = None):
        """Queue re-enrollment for an existing id, optionally changing the label."""
        self._pending_enroll = {"name": name or "", "id": person_id}

    def enroll_pending(self):
        """Return current pending enrollment request and clear it."""
        pending = self._pending_enroll
        self._pending_enroll = None
        return pending

    def is_enrolling(self) -> bool:
        return self._pending_enroll is not None

    def delete_face(self, person_id: int) -> bool:
        """Delete a face by id and clear cached state."""
        deleted = self.db.delete(person_id)
        if deleted:
            self._last_matches = []
            self._pending_enroll = None
            self._enroll_message = f"Deleted ID {person_id}"
        return deleted

    def list_faces(self) -> list[dict]:
        """Return metadata for all stored faces."""
        return self.db.list_faces()

    def reset_db(self):
        """Wipe all stored faces."""
        self.db.reset()
        self._last_matches = []
        self._pending_enroll = None
        self._enroll_message = "Face DB reset"


class FaceIDApp:
    def __init__(self, config: FaceIDConfig | None = None):
        self.pipeline = FaceIDPipeline(config)
        self.cfg = self.pipeline.cfg
        self.db = self.pipeline.db

    def _enroll(self, cap: cv2.VideoCapture, name: str | None = None, person_id: int | None = None):
        if not name:
            if person_id is not None:
                existing = self.db.get_label(person_id)
                if existing:
                    name = existing
        if not name:
            name = input("\nEnter name to enroll: ").strip()
            if not name:
                print("Empty name; cancelled.")
                return

        if person_id is None:
            pid_in = input("Enter numeric ID (blank = auto-assign): ").strip()
            if pid_in:
                try:
                    person_id = int(pid_in)
                except ValueError:
                    print("Invalid ID; cancelled.")
                    return
            else:
                person_id = self.db.next_id()

        samples = []
        print(f"Enrolling '{name}'... please look at camera. Capturing {self.cfg.enroll_samples} samples.")
        captured = 0

        while captured < self.cfg.enroll_samples:
            ok2, frame2 = cap.read()
            if not ok2:
                break

            best_face2, _ = self.pipeline.model.detect_and_embed(frame2)
            if best_face2 is None:
                cv2.putText(frame2, "No face - hold still", (20, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                cv2.imshow("Face ID", frame2)
                cv2.waitKey(1)
                continue

            ax1, ay1, ax2, ay2 = map(int, best_face2.bbox)
            emb2 = best_face2.embedding.astype(np.float32)
            samples.append(emb2)
            captured += 1

            cv2.rectangle(frame2, (ax1, ay1), (ax2, ay2), (255, 255, 0), 2)
            cv2.putText(frame2, f"Enrolling {name}: {captured}/{self.cfg.enroll_samples}", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.imshow("Face ID", frame2)
            cv2.waitKey(1)
            time.sleep(self.cfg.enroll_delay)

        if len(samples) >= max(5, self.cfg.enroll_samples // 3):
            mean_emb = np.mean(np.stack(samples, axis=0), axis=0).astype(np.float32)
            mean_emb = l2_normalize(mean_emb.reshape(1, -1), axis=1)[0]
            self.db.add_or_update(person_id, name, mean_emb)
            self.db.save()
            print(f"Enrolled ID {person_id} '{name}' saved to {self.cfg.db_path}. Total identities: {self.db.count()}\n")
        else:
            print("Not enough samples captured; enrollment failed.\n")

    def run_camera(self, use_thread: bool = False, show: bool = True, throttle_sec: float = 0.0):
        cap = cv2.VideoCapture(self.cfg.cam)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)

        print("Controls: [e] enroll | [q] quit")
        print(f"Loaded DB: {self.db.count()} identities, sim_threshold={self.cfg.sim_th}")

        processor = FrameProcessorThread(self.pipeline) if use_thread else None
        if processor:
            processor.start()

        last_print = 0.0
        last_proc_time = 0.0
        last_submit_time = 0.0
        last_matches = []
        last_annotated = None

        while True:
            ok, frame = cap.read()
            if not ok:
                print("Camera read failed.")
                break

            pending = self.pipeline.enroll_pending()
            if pending:
                self._enroll(cap, name=str(pending.get("name") or ""), person_id=pending.get("id"))

            label_show = "NoFace"
            sim_show = 0.0

            now = time.time()
            if processor:
                if throttle_sec <= 0 or (now - last_submit_time) >= throttle_sec:
                    processor.submit(frame)
                    last_submit_time = now
                latest = processor.get_latest()
                if latest:
                    last_matches, last_annotated = latest
            else:
                if throttle_sec <= 0 or (now - last_proc_time) >= throttle_sec:
                    last_matches, last_annotated = self.pipeline.process_frame(frame, draw=True)
                    last_proc_time = now

            if last_matches:
                top = max(last_matches, key=lambda m: m["sim"])
                label_show = top["label"]
                sim_show = top["sim"]

            frame_to_show = last_annotated if last_annotated is not None else frame

            now = time.time()
            if now - last_print > 2.0:
                print(f"Detected: {label_show}, sim={sim_show:.2f}, DB={self.db.count()}")
                last_print = now

            if show:
                cv2.imshow("Face ID", frame_to_show)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("e"):
                    self._enroll(cap)

        cap.release()
        cv2.destroyAllWindows()
        if processor:
            processor.stop()


def main():
    # Default entrypoint: run live camera demo.
    FaceIDApp().run_camera()


if __name__ == "__main__":
    main()
