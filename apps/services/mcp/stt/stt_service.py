from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Callable

from vosk import Model, KaldiRecognizer # type: ignore


@dataclass
class SttSnapshot:
    ts: float
    is_listening: bool
    partial: str
    final: str
    error: Optional[str] = None


class SttService:

    def __init__(
        self,
        *,
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        device: Optional[int] = None,
        phrase_timeout_s: float = 1.0,
    ):
        default_model = str(Path(__file__).resolve().parent / "model")
        self.model_path = model_path or os.environ.get("VOSK_MODEL_PATH", default_model)
        self.sample_rate = int(sample_rate)
        self.device = device
        self.phrase_timeout_s = float(phrase_timeout_s)

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._partial = ""
        self._final = ""
        self._ts = 0.0
        self._error: Optional[str] = None

        self._audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=50)

        self._model: Optional[Model] = None
        self._rec: Optional[KaldiRecognizer] = None

        # Callback hook for events (set by caller)
        self.on_final: Optional[Callable[[str], None]] = None

    # APIs

    def start_listening(self) -> Dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": True, "msg": "already listening"}

            self._stop.clear()
            self._partial = ""
            self._final = ""
            self._error = None
            self._ts = time.time()

            try:
                self._ensure_model()
            except Exception as exc:
                self._error = str(exc)
                return {"ok": False, "error": self._error}

            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            return {"ok": True, "msg": "listening started"}

    def stop_listening(self) -> Dict[str, Any]:
        self._stop.set()
        t = None
        with self._lock:
            t = self._thread
        if t:
            t.join(timeout=2)
        with self._lock:
            self._thread = None
        return {"ok": True, "msg": "listening stopped"}

    def latest(self) -> Dict[str, Any]:
        with self._lock:
            alive = bool(self._thread and self._thread.is_alive())
            snap = SttSnapshot(
                ts=self._ts,
                is_listening=alive and not self._stop.is_set(),
                partial=self._partial,
                final=self._final,
                error=self._error,
            )
        return {
            "ok": True,
            "ts": snap.ts,
            "is_listening": snap.is_listening,
            "partial": snap.partial,
            "final": snap.final,
            "error": snap.error,
        }

    def push_text(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "text required"}
        with self._lock:
            self._final = text
            self._partial = ""
            self._ts = time.time()
        # fire hook
        try:
            if callable(self.on_final):
                self.on_final(text)
        except Exception:
            pass
        return {"ok": True, "final": text}

    # Helper functions

    def _ensure_model(self):
        if self._model is None:
            if not os.path.isdir(self.model_path):
                raise RuntimeError(f"Vosk model path not found: {self.model_path}")
            self._model = Model(self.model_path)
        if self._rec is None:
            self._rec = KaldiRecognizer(self._model, self.sample_rate)
            self._rec.SetWords(False)

    def _run_loop(self):
        try:
            with self._lock:
                self._error = None
                self._ts = time.time()

            self._start_audio_capture()

            last_voice_ts = time.time()
            while not self._stop.is_set():
                try:
                    chunk = self._audio_q.get(timeout=0.2)
                except queue.Empty:
                    # Timeout - check for phrase timeout
                    if time.time() - last_voice_ts > self.phrase_timeout_s:
                        with self._lock:
                            self._partial = ""
                    continue

                if not chunk:
                    continue

                last_voice_ts = time.time()
                rec = self._rec
                if rec is None:
                    continue

                if rec.AcceptWaveform(chunk):
                    res = json.loads(rec.Result() or "{}")
                    text = (res.get("text") or "").strip()
                    if text:
                        with self._lock:
                            self._final = text
                            self._partial = ""
                            self._ts = time.time()
                        try:
                            if callable(self.on_final):
                                self.on_final(text)
                        except Exception:
                            pass
                else:
                    pres = json.loads(rec.PartialResult() or "{}")
                    ptxt = (pres.get("partial") or "").strip()
                    with self._lock:
                        self._partial = ptxt
                        self._ts = time.time()

        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._ts = time.time()
        finally:
            try:
                self._stop_audio_capture()
            except Exception:
                pass

    # Audio capture helpers
    def _start_audio_capture(self):
        self._audio_backend = None
        self._sd_stream = None
        self._pa = None
        self._pa_stream = None
        self._pa_thread = None

        try:
            import sounddevice as sd  # type: ignore

            def callback(indata, frames, time_info, status):  
                if self._stop.is_set():
                    return
                try:
                    self._audio_q.put_nowait(bytes(indata))
                except queue.Full:
                    pass

            self._audio_backend = "sounddevice"
            self._sd = sd
            self._sd_stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=8000,
                device=self.device,
                dtype="int16",
                channels=1,
                callback=callback,
            )
            self._sd_stream.start()
            return
        except ImportError:
            pass  
        except Exception as exc:
            raise RuntimeError(f"sounddevice init failed: {exc}") from exc

        try:
            import pyaudio  # type: ignore

            self._audio_backend = "pyaudio"
            self._pa = pyaudio.PyAudio()
            self._pa_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=8000,
                input_device_index=self.device,
            )

            def pa_loop():
                while not self._stop.is_set():
                    try:
                        data = self._pa_stream.read(8000, exception_on_overflow=False)
                    except Exception:
                        continue
                    try:
                        self._audio_q.put_nowait(data)
                    except queue.Full:
                        pass

            self._pa_thread = threading.Thread(target=pa_loop, daemon=True)
            self._pa_thread.start()
            return
        except ImportError as exc:
            raise RuntimeError(
                "No audio backend available. Install sounddevice or pyaudio."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"pyaudio init failed: {exc}") from exc

    def _stop_audio_capture(self):
        if getattr(self, "_audio_backend", None) == "sounddevice":
            try:
                if self._sd_stream:
                    self._sd_stream.stop()
                    self._sd_stream.close()
            finally:
                self._sd_stream = None
        elif getattr(self, "_audio_backend", None) == "pyaudio":
            try:
                # Stop thread first
                t = getattr(self, "_pa_thread", None)
                if t and t.is_alive():
                    t.join(timeout=1.0)

                if self._pa_stream:
                    self._pa_stream.stop_stream()
                    self._pa_stream.close()
                if self._pa:
                    self._pa.terminate()
            finally:
                self._pa_stream = None
                self._pa = None
                self._pa_thread = None
