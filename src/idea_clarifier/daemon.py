import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

SESSIONS_DIR = Path.home() / ".idea-clarifier" / "sessions"


def _save_session_file(session: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    fp = SESSIONS_DIR / f"{session['session_id']}.json"
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=SESSIONS_DIR, encoding="utf-8"
    )
    try:
        json.dump(session, tmp, indent=2, ensure_ascii=False, default=str)
        tmp.close()
        os.replace(tmp.name, fp)
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise


def _load_session_file(session_id: str) -> dict | None:
    fp = SESSIONS_DIR / f"{session_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _auth_enabled() -> bool:
    return not os.environ.get("CODEX_CLARIFIER_NO_AUTH")


def create_app(sessions: dict) -> FastAPI:
    app = FastAPI(title="Idea Clarifier Daemon")
    static_dir = Path(__file__).parent / "static"
    submit_events: dict[str, asyncio.Event] = {}

    # ── Auth middleware ─────────────────────────────────────────────────

    class SessionAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if not _auth_enabled():
                return await call_next(request)

            if not request.url.path.startswith("/api/"):
                return await call_next(request)

            parts = request.url.path.split("/")
            try:
                session_id = parts[3]
            except IndexError:
                return await call_next(request)

            session = sessions.get(session_id)
            if not session:
                session = _load_session_file(session_id)
                if session:
                    sessions[session_id] = session

            if session and session.get("session_token"):
                auth = request.headers.get("Authorization", "")
                expected = session["session_token"]
                if not auth.startswith("Bearer ") or auth[7:] != expected:
                    return JSONResponse(
                        {"error": "Missing or invalid session token"},
                        status_code=401,
                    )

            return await call_next(request)

    app.add_middleware(SessionAuthMiddleware)

    # ── Static files (locales) ──────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Page ──────────────────────────────────────────────────────────

    @app.get("/session/{session_id}", response_class=HTMLResponse)
    async def serve_session(session_id: str):
        session = sessions.get(session_id)
        if not session:
            session = _load_session_file(session_id)
            if session:
                sessions[session_id] = session
        if not session:
            return HTMLResponse(
                "<h1 style='font-family:sans-serif;padding:40px'>Session not found or already completed.</h1>",
                status_code=404,
            )
        return HTMLResponse(
            (static_dir / "index.html").read_text(encoding="utf-8")
        )

    # ── Session info ──────────────────────────────────────────────────

    @app.get("/api/session/{session_id}")
    async def get_session(session_id: str):
        session = sessions.get(session_id)
        if not session:
            session = _load_session_file(session_id)
            if session:
                sessions[session_id] = session
        if not session:
            return JSONResponse(
                {"error": "Session not found or already finalized. The decisions have been saved to the project directory."},
                status_code=404,
            )
        return JSONResponse({
            "idea": session.get("idea") or session.get("context", ""),
            "mode": session.get("mode", "clarification"),
            "questions": session["questions"],
            "glossary": session.get("glossary", []),
            "glossary_complete": session.get("glossary_complete", False),
            "status": session["status"],
            "session_token": session.get("session_token"),
        })

    # ── Submit all answers ────────────────────────────────────────────

    @app.post("/api/session/{session_id}/answers")
    async def submit_answers(session_id: str, request: Request):
        session = sessions.get(session_id)
        if not session:
            session = _load_session_file(session_id)
            if session:
                sessions[session_id] = session
        if not session:
            return JSONResponse(
                {"error": "Session not found or already finalized. The decisions have been saved to the project directory."},
                status_code=404,
            )

        body = await request.json()
        session["answers"] = body.get("answers", {})
        session["status"] = "completed"
        session["last_updated"] = datetime.now().isoformat()
        session["version"] = session.get("version", 1) + 1
        _save_session_file(session)

        event = submit_events.pop(session_id, None)
        if event:
            event.set()

        return JSONResponse({"success": True})

    # ── Long-poll answers ─────────────────────────────────────────────

    @app.get("/api/session/{session_id}/answers")
    async def long_poll_answers(session_id: str, wait: int = Query(0, ge=0, le=120)):
        """Long-poll: wait up to `wait` seconds for submission, then return status."""
        session = sessions.get(session_id)
        if not session:
            session = _load_session_file(session_id)
            if session:
                sessions[session_id] = session
        if not session:
            return JSONResponse(
                {"error": "Session not found or already finalized. The decisions have been saved to the project directory."},
                status_code=404,
            )

        if session["status"] == "completed" or wait <= 0:
            return JSONResponse({
                "session_id": session_id,
                "status": session["status"],
            })

        event = submit_events.setdefault(session_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            submit_events.pop(session_id, None)
            return JSONResponse({
                "session_id": session_id,
                "status": "pending",
                "timeout": True,
            })

        return JSONResponse({
            "session_id": session_id,
            "status": "completed",
        })

    return app
