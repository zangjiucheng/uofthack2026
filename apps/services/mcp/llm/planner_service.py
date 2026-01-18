from __future__ import annotations

import json
import os
import threading
import base64
import subprocess
import tempfile
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from vosk import Model, KaldiRecognizer  # type: ignore

from .agent import Agent
from .json_utils import try_parse_json
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .validate import validate_plan
from ..planner.mcp_tools import DEFAULT_PLANNER_TOOLS


_vosk_model: Model | None = None


def _load_vosk_model() -> Model:
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    default_model = Path(__file__).resolve().parent.parent / "stt" / "model"
    model_path = os.environ.get("VOSK_MODEL_PATH", str(default_model))
    _vosk_model = Model(model_path)
    return _vosk_model


def _looks_like_plan(text: str) -> bool:
    """
    Heuristic to decide if the LLM attempted to emit a plan JSON.
    Used to decide whether to reprompt for strict JSON vs treat as chat.
    """
    if not text:
        return False
    t = text.strip().lower()
    if t.startswith("{") or "goal_type" in t or "mcp.plan.v1" in t:
        return True
    return False


def _transcribe_audio_file(path: str) -> str:
    model = _load_vosk_model()
    with wave.open(path, "rb") as wf:
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(False)
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)
        res = json.loads(rec.FinalResult() or "{}")
        return (res.get("text") or "").strip()


def _is_mp3_bytes(raw: bytes) -> bool:
    """
    Lightweight MP3 detection:
    - ID3 tag (ID3 header)
    - MPEG frame sync (0xFF 0xFB / 0xF3 / 0xF2)
    """
    if len(raw) < 4:
        return False
    if raw[:3] == b"ID3":
        return True
    b0, b1 = raw[0], raw[1]
    return b0 == 0xFF and b1 in (0xFB, 0xF3, 0xF2)


def _convert_to_wav(src_path: str) -> tuple[bool, str, str]:
    """
    Convert audio file at src_path to a temporary WAV (16k mono).
    Returns (ok, wav_path, error).
    """
    dst = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    dst_path = dst.name
    dst.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "wav",
        dst_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")[:200]
        try:
            os.remove(dst_path)
        except Exception:
            pass
        return False, "", f"ffmpeg convert failed: {err or 'unknown error'}"
    return True, dst_path, ""


def _transcribe_from_payload(payload: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Returns (ok, transcript, error)
    Accepts:
      - audio_b64 / audio_base64: base64-encoded wav/pcm audio
      - audio_path: filesystem path to a wav file
      - audio_path pointing to mp3 will be converted to wav (requires ffmpeg)
    """
    audio_b64 = (payload or {}).get("audio_b64") or (payload or {}).get("audio_base64")
    audio_path = (payload or {}).get("audio_path")

    if audio_b64:
        try:
            raw = base64.b64decode(audio_b64, validate=True)
        except Exception as exc:
            return False, "", f"invalid audio_b64: {exc}"
        suffix = ".mp3" if _is_mp3_bytes(raw) else ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        wav_path = tmp_path
        cleanup_paths = [tmp_path]
        try:
            if suffix == ".mp3":
                ok_conv, wav_path, err = _convert_to_wav(tmp_path)
                if not ok_conv:
                    return False, "", err
                cleanup_paths.append(wav_path)

            text = _transcribe_audio_file(wav_path)
            return (bool(text), text, "no speech detected" if not text else "")
        except Exception as exc:  # pragma: no cover - decoding errors
            return False, "", f"transcription failed: {exc}"
        finally:
            for p in cleanup_paths:
                try:
                    os.remove(p)
                except Exception:
                    pass

    if audio_path:
        try:
            path = audio_path
            cleanup_paths = []
            if str(audio_path).lower().endswith(".mp3"):
                ok_conv, wav_path, err = _convert_to_wav(audio_path)
                if not ok_conv:
                    return False, "", err
                path = wav_path
                cleanup_paths.append(wav_path)

            text = _transcribe_audio_file(path)
            # remove temp conversion if any
            for p in cleanup_paths:
                try:
                    os.remove(p)
                except Exception:
                    pass
            return (bool(text), text, "no speech detected" if not text else "")
        except Exception as exc:
            return False, "", f"transcription failed: {exc}"

    return False, "", "no audio provided"


def start_planner_service(host: str = "0.0.0.0", port: int = 8091) -> HTTPServer:
    agent = Agent()  
    temperature = float(os.environ.get("PLANNER_TEMPERATURE", "0.0"))

    class Handler(BaseHTTPRequestHandler):
        def _set_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Planner-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self): 
            self.send_response(200)
            self._set_cors()
            self.end_headers()

        def _json(self, code: int, obj: Dict[str, Any]):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._set_cors()
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  
            if self.path.rstrip("/") != "/plan":
                return self._json(404, {"ok": False, "error": "not found"})


            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                payload = {}

            transcript = (payload.get("transcript") or "").strip()
            context = payload.get("context") or {}

            # Always use MCP-defined tools; ignore caller-provided tools to avoid drift.
            tool_defs = DEFAULT_PLANNER_TOOLS
            tool_names = [t.get("name") for t in tool_defs if isinstance(t, dict) and t.get("name")]

            if not transcript:
                ok, transcript, terr = _transcribe_from_payload(payload)
                if not ok or not transcript:
                    return self._json(400, {"ok": False, "error": terr or "transcript required"})

            allowed_tools: Set[str] = set(tool_names)

            user_prompt = build_user_prompt(
                transcript,
                context if isinstance(context, dict) else {},
                tool_defs, 
            )

            # 1) call LLM
            llm_resp = agent.respond(user_prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)
            if llm_resp.text.startswith("[llm:") and "error]" in llm_resp.text:
                return self._json(502, {"ok": False, "error": "llm error", "detail": llm_resp.text})

            llm_text = (llm_resp.text or "").strip()
            if not llm_text:
                return self._json(502, {"ok": False, "error": "empty llm response"})

            # 2) parse JSON or fall back to chat
            plan_obj = try_parse_json(llm_text)
            if plan_obj is None:
                if _looks_like_plan(llm_text):
                    strict_prompt = (
                        f"{user_prompt}\n\n"
                        "Return ONLY valid MCP Plan JSON v1. No code fences, no Markdown, no commentary. "
                        "Keep it to a single JSON object with goal_type/tool/payload (no steps array). "
                        "Example format:\n"
                        "{\"version\":\"mcp.plan.v1\",\"goal_type\":\"FIND_OBJECT\",\"tool\":\"approach_object\",\"payload\":{\"object\":\"bottle\"}}"
                    )
                    llm_resp = agent.respond(strict_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
                    llm_text = (llm_resp.text or "").strip()
                    plan_obj = try_parse_json(llm_text)
                    if plan_obj is None:
                        return self._json(
                            200,
                            {
                                "ok": False,
                                "error": "planner returned non-json",
                                "raw": llm_resp.text[:800],
                            },
                        )
                else:
                    # Treat as a normal chat reply for out-of-scope requests.
                    return self._json(200, {"ok": True, "mode": "chat", "reply": llm_text})

            # 3) validate plan
            ok, err = validate_plan(plan_obj, allowed_tools)
            if not ok:
                repair_prompt = (
                    "Your previous output failed validation.\n"
                    f"Error: {err}\n\n"
                    "Return ONLY corrected MCP Plan JSON v1 that passes validation. No extra text.\n\n"
                    f"Previous JSON:\n{json.dumps(plan_obj)}"
                )
                llm2 = agent.respond(repair_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
                plan2 = try_parse_json(llm2.text) or plan_obj
                ok2, err2 = validate_plan(plan2, allowed_tools)
                if not ok2:
                    return self._json(200, {"ok": False, "error": f"invalid plan: {err2}", "plan": plan2})

                return self._json(200, {"ok": True, "mode": "plan", "plan": plan2})

            return self._json(200, {"ok": True, "mode": "plan", "plan": plan_obj})

        def log_message(self, fmt, *args):  # noqa: ANN001
            return  # silence

    server = HTTPServer((host, port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[planner] HTTP POST on http://{host}:{port}/plan")
    return server
