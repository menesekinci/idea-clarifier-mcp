from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse


def create_app(sessions: dict) -> FastAPI:
    app = FastAPI(title="Idea Clarifier Daemon")
    static_dir = Path(__file__).parent / "static"

    # ── Page ──────────────────────────────────────────────────────────────

    @app.get("/session/{session_id}", response_class=HTMLResponse)
    async def serve_session(session_id: str):
        if session_id not in sessions:
            return HTMLResponse(
                "<h1 style='font-family:sans-serif;padding:40px'>Session not found or already completed.</h1>",
                status_code=404,
            )
        return HTMLResponse((static_dir / "index.html").read_text(encoding="utf-8"))

    # ── Session info ───────────────────────────────────────────────────────

    @app.get("/api/session/{session_id}")
    async def get_session(session_id: str):
        session = sessions.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({
            "idea": session.get("idea") or session.get("context", ""),
            "mode": session.get("mode", "clarification"),
            "questions": session["questions"],
            "status": session["status"],
        })

    # ── Submit all answers ─────────────────────────────────────────────────

    @app.post("/api/session/{session_id}/answers")
    async def submit_answers(session_id: str, request: Request):
        session = sessions.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        body = await request.json()
        session["answers"] = body.get("answers", {})
        session["status"] = "completed"
        return JSONResponse({"success": True})

    return app
