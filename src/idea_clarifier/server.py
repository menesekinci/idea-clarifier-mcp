import json
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP

from .daemon import create_app

mcp = FastMCP(
    "idea-clarifier",
    instructions=(
        "Two tools are available depending on the situation:\n\n"
        "1. start_clarification — NEW project idea (60-70 questions, categorised, writes decisions.json):\n"
        "   a. Layer 1 — project_vision FIRST (7 questions): purpose, audience, platform, "
        "user actions, scale, revenue, differentiator.\n"
        "   b. Layer 2 — product layer SECOND (5+ each): core_flows, feature_scope, content_model, ui_ux.\n"
        "      core_flows: happy path, reject/undo, deadline trigger, concurrent edit, onboarding.\n"
        "      feature_scope: MVP must-haves, out-of-scope, priority rule, success metric, paid tier boundary.\n"
        "      content_model: entity hierarchy, state machine, assignment rules, required fields, custom fields.\n"
        "      ui_ux: navigation model, dashboard/home, view types, empty states, mobile-vs-desktop priority.\n"
        "   c. Layer 3 — technical layer LAST (5+ each): tech_stack, architecture, database, security, "
        "performance, api, deployment, business_logic.\n"
        "   c. Every question MUST include 'option_descriptions' (4 plain-language explanations).\n\n"
        "2. start_plan_clarification — EXISTING project, before writing a plan (5-15 questions, "
        "no categories, writes plan_notes.json):\n"
        "   Use after exploring the codebase when you need user decisions before you can plan.\n"
        "   Every question must have exactly 4 options and 4 option_descriptions — same rule as tool 1.\n\n"
        "SHARED WORKFLOW (both tools):\n"
        "   - Browser opens automatically after the tool call.\n"
        "   - Poll get_answers every 5 seconds until status=='completed'.\n"
        "   - When completed: for each item in undecided_questions, discuss with the user HERE\n"
        "     in the IDE — do NOT open a new browser session for them.\n"
        "   - Fill ai_decisions for every id in ai_decision_needed.\n"
        "   - Call write_decisions.\n\n"
        "See this repository's README.md and AGENT_GUIDE.md for full examples."
    ),
)

# Shared in-process state between MCP tools and the HTTP daemon thread.
sessions: dict[str, dict] = {}
_daemon_started = False
DAEMON_PORT = 7532


def _start_daemon_once() -> None:
    global _daemon_started
    if _daemon_started:
        return
    _daemon_started = True

    app = create_app(sessions)

    def run() -> None:
        uvicorn.run(app, host="127.0.0.1", port=DAEMON_PORT, log_level="error")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.8)


def _persist_session(session: dict) -> None:
    """Write session state to project_path/.clarifier/session.json for crash recovery."""
    try:
        clarifier_dir = Path(session["project_path"]) / ".clarifier"
        clarifier_dir.mkdir(parents=True, exist_ok=True)
        out = {
            "session_id": session["session_id"],
            "idea": session["idea"],
            "status": session["status"],
            "questions": session["questions"],
            "answers": session["answers"],
            "saved_at": datetime.now().isoformat(),
        }
        (clarifier_dir / "session.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass  # Non-critical; don't crash the MCP on persistence errors


@mcp.tool()
def start_clarification(
    idea: str,
    project_path: str,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Open a browser Q&A session to clarify a project idea before planning.

    Question schema (each item in the list):
        {
            "id":                  str,       # unique, e.g. "q_vision_01"
            "category":            str,       # Layer 1: project_vision
                                              # Layer 2: core_flows | feature_scope | content_model | ui_ux
                                              # Layer 3: tech_stack | architecture | database | security |
                                              #          performance | api | deployment | business_logic
            "question":            str,       # question text shown to the user
            "options":             list[str], # exactly 4 option strings (A, B, C, D)
            "option_descriptions": list[str]  # exactly 4 plain-language descriptions,
                                              # one per option. Explain what happens if
                                              # this option is chosen and clarify any jargon.
        }

    IMPORTANT: Always start with 'project_vision' questions (at least 7) to understand
    the idea itself before asking any technical questions.

    Immediately creates project_path/.clarifier/session.json for crash recovery.
    Returns session_id and the URL opened in the browser.
    """
    if not questions:
        return {"error": "questions list cannot be empty"}

    _start_daemon_once()

    session_id = str(uuid.uuid4())
    session: dict[str, Any] = {
        "session_id": session_id,
        "idea": idea,
        "project_path": project_path,
        "questions": questions,
        "answers": {},
        "status": "pending",
    }
    sessions[session_id] = session
    _persist_session(session)

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}"
    webbrowser.open(url)

    return {
        "session_id": session_id,
        "url": url,
        "question_count": len(questions),
        "message": (
            "Browser opened. Poll get_answers(session_id) every 5 seconds. "
            "When completed, discuss undecided_questions with the user in the IDE."
        ),
    }


@mcp.tool()
def get_answers(session_id: str) -> dict[str, Any]:
    """Poll this tool after start_clarification or start_plan_clarification.

    Returns:
        status='pending'   — user is still answering. Keep polling every 5 seconds.
        status='completed' — all questions submitted.
            answers              — {question_id: {answer, ai_decides, custom, undecided, undecided_note}}
            ai_decision_needed   — [question_ids where user clicked 'AI KARAR VERSİN']
            undecided_questions  — [questions user marked as undecided; discuss HERE in the IDE]
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}

    if session["status"] != "completed":
        return {
            "status": "pending",
            "message": "User is still answering. Try again in 5 seconds.",
        }

    answers = session["answers"]
    ai_needed = [qid for qid, ans in answers.items() if ans.get("ai_decides")]
    undecided = [
        {
            "question_id": qid,
            "question_text": next(
                (q["question"] for q in session["questions"] if q["id"] == qid), qid
            ),
            "note": ans.get("undecided_note", ""),
        }
        for qid, ans in answers.items()
        if ans.get("undecided")
    ]

    parts = []
    if ai_needed:
        parts.append(f"{len(ai_needed)} question(s) need your AI decision.")
    if undecided:
        parts.append(
            f"{len(undecided)} question(s) marked undecided — discuss with the user "
            "in the IDE, then include your conclusions in ai_decisions."
        )
    if not parts:
        parts.append("All questions answered.")
    parts.append("Call write_decisions now.")

    return {
        "status": "completed",
        "answers": answers,
        "ai_decision_needed": ai_needed,
        "undecided_questions": undecided,
        "message": " ".join(parts),
    }



@mcp.tool()
def write_decisions(
    session_id: str,
    ai_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write final decisions.json to the project directory.

    Call after get_answers returns status=='completed'.

    Args:
        session_id:   From start_clarification.
        ai_decisions: {question_id: "your decision text"} for every id
                      in ai_decision_needed. Pass {} or omit if none.

    Writes to: project_path/decisions.json
    Cleans up: project_path/.clarifier/session.json (removes temp state)
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}
    if session["status"] != "completed":
        return {"error": "Session not completed yet. Wait for user to submit."}

    if ai_decisions is None:
        ai_decisions = {}

    answers = {**session["answers"]}

    # Merge AI decisions
    for qid, decision_text in ai_decisions.items():
        answers[qid] = {"answer": decision_text, "ai_decides": True, "custom": True}

    project_path = Path(session["project_path"])
    project_path.mkdir(parents=True, exist_ok=True)

    mode = session.get("mode", "clarification")

    if mode == "plan":
        # Flat list — no category grouping
        notes = []
        for q in session["questions"]:
            qid = q["id"]
            ans = answers.get(qid, {})
            entry: dict[str, Any] = {
                "question": q["question"],
                "answer": ans.get("answer", "— not answered —"),
                "ai_decided": bool(ans.get("ai_decides")),
                "user_custom": bool(ans.get("custom") and not ans.get("ai_decides")),
                "undecided": bool(ans.get("undecided")),
            }
            if ans.get("undecided_note"):
                entry["undecided_note"] = ans["undecided_note"]
            notes.append(entry)

        output = {
            "planning_context": session.get("context", session.get("idea", "")),
            "generated_at": datetime.now().isoformat(),
            "notes": notes,
        }
        out_file = project_path / "plan_notes.json"

    else:
        # Category-grouped output (clarification mode)
        categories: dict[str, list[dict]] = {}
        for q in session["questions"]:
            qid = q["id"]
            cat = q.get("category", "other")
            ans = answers.get(qid, {})

            entry = {
                "question": q["question"],
                "answer": ans.get("answer", "— not answered —"),
                "ai_decided": bool(ans.get("ai_decides")),
                "user_custom": bool(ans.get("custom") and not ans.get("ai_decides")),
                "undecided": bool(ans.get("undecided")),
            }
            if ans.get("undecided_note"):
                entry["undecided_note"] = ans["undecided_note"]

            categories.setdefault(cat, []).append(entry)

        output = {
            "project_idea": session["idea"],
            "generated_at": datetime.now().isoformat(),
            "decisions": categories,
        }
        out_file = project_path / "decisions.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Remove temp session file
    try:
        (project_path / ".clarifier" / "session.json").unlink(missing_ok=True)
    except Exception:
        pass

    del sessions[session_id]

    if mode == "plan":
        return {
            "success": True,
            "path": str(out_file),
            "total_notes": len(output["notes"]),
        }
    else:
        return {
            "success": True,
            "path": str(out_file),
            "categories": list(output["decisions"].keys()),
            "total_decisions": sum(len(v) for v in output["decisions"].values()),
        }


@mcp.tool()
def start_plan_clarification(
    context: str,
    project_path: str,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pre-plan Q&A for an EXISTING project before writing an implementation plan.

    Use after exploring the codebase. Ask 5–15 targeted questions that you need
    answered before you can write a reliable plan.

    Question schema:
        {
            "id":                  str,        # unique, e.g. "p_01"
            "question":            str,        # the question text
            "options":             list[str],  # exactly 4 option strings (A, B, C, D)
            "option_descriptions": list[str],  # exactly 4 plain-language descriptions
        }

    No "category" field needed. All questions must have exactly 4 options — same rule as
    start_clarification.
    Writes plan_notes.json (not decisions.json) to project_path.
    """
    if not questions:
        return {"error": "questions list cannot be empty"}

    _start_daemon_once()

    session_id = str(uuid.uuid4())
    session: dict[str, Any] = {
        "session_id": session_id,
        "mode": "plan",
        "context": context,
        "idea": context,          # UI compatibility — both fields point to same value
        "project_path": project_path,
        "questions": questions,
        "answers": {},
        "status": "pending",
    }
    sessions[session_id] = session
    _persist_session(session)

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}"
    webbrowser.open(url)

    return {
        "session_id": session_id,
        "url": url,
        "question_count": len(questions),
        "message": (
            "Browser opened for pre-plan clarification. "
            "Poll get_answers(session_id) every 5 seconds. "
            "When completed, discuss undecided_questions with the user in the IDE."
        ),
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
