import json
import os
import re
import tempfile
import threading
import time
import uuid
import webbrowser
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP

from .daemon import create_app, SESSIONS_DIR, _load_session_file

mcp = FastMCP(
    "idea-clarifier",
    instructions=(
        "Three tools are available depending on the situation:\n\n"
        "1. start_intent_clarification — REQUIRED FIRST for NEW project ideas (7 fixed questions):\n"
        "   Use before start_clarification. The goal is to understand user intent, target outcome,\n"
        "   conceptual product logic, success criteria, and explicit non-goals before any technical decisions.\n"
        "   This tool uses a fixed option-based question set, writes no decisions file, and returns raw answers via get_answers.\n"
        "   The user can select provided options and optionally add a custom answer. Some intent questions\n"
        "   are single_choice, some are multi_choice.\n"
        "   After get_answers returns completed, internally summarize an intent brief for yourself, then create\n"
        "   the second-stage questions. Do not write the intent brief to disk.\n\n"
        "2. start_clarification — NEW project idea AFTER intent clarification (12-25 targeted questions, categorised, writes decisions.json):\n"
        "   a. Every question MUST include one unique decision_axis. The MCP validates this contract\n"
        "      and rejects duplicate axes or near-duplicate question text before opening a session.\n"
        "   b. Layer 1 — project_vision FIRST: purpose, audience, platform, "
        "user actions, scale, revenue, differentiator.\n"
        "   c. Layer 2 — product layer SECOND as needed: core_flows, feature_scope, content_model, ui_ux.\n"
        "      core_flows: happy path, reject/undo, deadline trigger, concurrent edit, onboarding.\n"
        "      feature_scope: MVP must-haves, out-of-scope, priority rule, success metric, paid tier boundary.\n"
        "      content_model: entity hierarchy, state machine, assignment rules, required fields, custom fields.\n"
        "      ui_ux: navigation model, dashboard/home, view types, empty states, mobile-vs-desktop priority.\n"
        "   d. Layer 3 — technical layer LAST only when needed: tech_stack, architecture, database, security, "
        "performance, api, deployment, business_logic.\n"
        "      Ask technical questions only when the intent answers make those decisions necessary now.\n"
        "   e. Questions support 4 types via the 'type' field. For choice questions, explicitly set\n"
        "      type to single_choice or multi_choice; do not rely on the default in new prompts.\n"
        "      - single_choice (default for backward compatibility): user picks ONE option, 2-5 options.\n"
        "      - multi_choice: user may pick multiple options. Use when multiple valid answers are natural.\n"
        "        Only resolve contradictions\n"
        "        during the IDE discussion phase.\n"
        "      - open_text: free-text textarea, no options grid. Set 'max_length'.\n"
        "      - yes_no: two-button binary. options auto-filled if missing.\n"
        "      'option_descriptions' is optional for all types. 'options' is 2-5 items\n"
        "      (not forced 4).\n"
        "   f. When technical questions use jargon, supply a 'glossary' list: "
        "{\"term\": \"...\", \"explanation\": \"...\"} for each term.\n"
        "   g. PREFERRED FLOW: call start_* first (browser opens instantly), "
        "then call add_glossary(session_id, terms) one or more times — the browser "
        "polls and updates the glossary card live while the user reads questions.\n\n"
        "3. start_plan_clarification — EXISTING project, before writing a plan (5-15 questions, "
        "no categories, writes plan_notes.json):\n"
        "   Use after exploring the codebase when you need user decisions before you can plan.\n"
        "   Every question must have exactly 4 options and 4 option_descriptions — same rule as tool 1.\n\n"
        "SHARED WORKFLOW (both tools):\n"
        "   - Browser opens automatically after the tool call.\n"
        "   - Call add_glossary(session_id, terms) one or more times to add technical terms.\n"
        "     The browser polls and rebuilds the glossary card live. After all terms are sent,\n"
        "     call add_glossary(session_id, []) once to mark the glossary complete and stop polling.\n"
        "   - Questions have 4 types (set via 'type' field). Only multi_choice allows\n"
        "     multiple selections. If multi_choice selections conflict, resolve during\n"
        "     the IDE discussion phase — no new browser session needed.\n"
        "   - DO NOT poll get_answers in a loop. Instead, WAIT for the user to explicitly\n"
        "     say they have finished (e.g. \"cevapladım\", \"bitti\", \"tamam\"). Then call\n"
        "     get_answers ONCE.\n"
        "   - get_answers accepts wait_seconds (0-120): use wait_seconds=60 to block\n"
        "     until the user submits instead of returning 'pending' immediately.\n"
        "   - write_decisions ai_decisions supports optional 'confidence' (0.0-1.0)\n"
        "     and 'reasoning' fields per decision.\n"
        "   - When get_answers returns status=='completed': for each item in undecided_questions,\n"
        "     discuss with the user HERE in the IDE — do NOT open a new browser session for them.\n"
        "   - Fill ai_decisions for every id in ai_decision_needed.\n"
        "   - If undecided questions remain unresolved, call suggest_followups(session_id)\n"
        "     to get structured context for each — discuss with the user in the IDE.\n"
        "   - Call write_decisions. Use commit=true to auto git-add and commit the output.\n\n"
        "See this repository's README.md and AGENT_GUIDE.md for full examples."
    ),
)

# Shared in-process state between MCP tools and the HTTP daemon thread.
sessions: dict[str, dict] = {}
_daemon_started = False
DEFAULT_HOST = "127.0.0.1"
DAEMON_PORT = 7532

INTENT_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "intent_goal",
        "type": "single_choice",
        "question": "Bu fikirle asıl neyi başarmak istiyorsunuz?",
        "options": [
            "Fikri doğrulamak",
            "İş/verimlilik problemi çözmek",
            "Gelir üreten ürün yapmak",
            "Mevcut hizmeti dijitalleştirmek",
        ],
        "option_descriptions": [
            "Önce fikrin kullanıcıda karşılığı olup olmadığını test ederiz.",
            "Somut bir operasyon, takip veya zaman kaybı problemini azaltmaya odaklanırız.",
            "Ürünü gelir modeli ve ödeme isteği etrafında şekillendiririz.",
            "Var olan manuel ya da offline hizmeti yazılıma taşırız.",
        ],
    },
    {
        "id": "intent_problem_context",
        "type": "multi_choice",
        "question": "Proje hangi problemi, hangi bağlamda çözecek?",
        "options": [
            "Dağınık takip",
            "İletişim/koordinasyon",
            "Karar/analiz eksikliği",
            "Manuel iş yükü",
        ],
        "option_descriptions": [
            "Bilgi, görev veya kayıtlar farklı yerlerde kaldığı için kontrol zorlaşıyor.",
            "İnsanlar veya ekipler arasında net sahiplik ve güncel durum görünmüyor.",
            "Kullanıcı doğru kararı vermek için yeterli özet, metrik veya öneri bulamıyor.",
            "Tekrarlanan işler elle yapıldığı için zaman kaybı ve hata oluşuyor.",
        ],
    },
    {
        "id": "intent_target_user",
        "type": "multi_choice",
        "question": "Hedef kullanıcı kim ve bu ürünü neden kullanacak?",
        "options": [
            "Bireysel kullanıcı",
            "Küçük ekip",
            "KOBİ/operasyon ekibi",
            "Kurumsal kullanıcı",
        ],
        "option_descriptions": [
            "Tek kişinin kendi işini, bilgisini veya alışkanlığını yönetmesine odaklanır.",
            "2-10 kişilik ekiplerde ortak takip ve sorumluluk paylaşımı gerekir.",
            "Departman veya operasyon akışlarında süreç, rol ve raporlama ihtiyacı artar.",
            "Güvenlik, yetki, denetim kaydı ve entegrasyon beklentisi yüksek olur.",
        ],
    },
    {
        "id": "intent_conceptual_model",
        "type": "single_choice",
        "question": "Ürünün kavramsal çalışma mantığı nasıl olmalı?",
        "options": [
            "Kayıt/takip sistemi",
            "İş akışı/onay sistemi",
            "Analiz/öneri sistemi",
            "Otomasyon/tetikleyici sistemi",
        ],
        "option_descriptions": [
            "Kullanıcı kayıt oluşturur, günceller, durumunu takip eder.",
            "Bir iş belirli adımlardan, rollerden ve onaylardan geçer.",
            "Sistem veriyi yorumlar, özetler veya öneri üretir.",
            "Belirli koşullar oluşunca otomatik aksiyonlar çalışır.",
        ],
    },
    {
        "id": "intent_success_criteria",
        "type": "multi_choice",
        "question": "İlk sürümün başarılı olduğunu neye bakarak anlayacağız?",
        "options": [
            "Düzenli kullanım",
            "Zaman/iş yükü azalması",
            "Daha az hata/gecikme",
            "Gelir veya dönüşüm",
        ],
        "option_descriptions": [
            "Kullanıcılar ürüne tekrar dönüyor ve temel akışı kullanıyor.",
            "Aynı iş daha kısa sürede veya daha az manuel adımla tamamlanıyor.",
            "Kaçan işler, yanlış kayıtlar veya gecikmeler ölçülebilir şekilde azalıyor.",
            "Kullanıcı ödeme yapıyor, deneme başlatıyor veya satış hunisinde ilerliyor.",
        ],
    },
    {
        "id": "intent_non_goals",
        "type": "multi_choice",
        "question": "İlk versiyonda kesinlikle kapsam dışında kalması gereken şeyler neler?",
        "options": [
            "Ağır raporlama",
            "Gelişmiş entegrasyonlar",
            "Mobil öncelik",
            "Faturalandırma/ödeme",
        ],
        "option_descriptions": [
            "İlk sürümde karmaşık dashboard, BI veya detaylı rapor üretimi yapılmaz.",
            "Harici sistemlerle kapsamlı çift yönlü entegrasyonlar sonraya bırakılır.",
            "İlk deneyim mobil-first değil, web/desktop öncelikli tasarlanır.",
            "Ödeme alma, abonelik ve fatura süreçleri ilk sürüme girmez.",
        ],
    },
    {
        "id": "intent_open_assumption",
        "type": "single_choice",
        "question": "Şu an en belirsiz kalan ana varsayım nedir?",
        "options": [
            "Kullanıcı ihtiyacı",
            "Doğru hedef kitle",
            "Teknik yapılabilirlik",
            "Sürdürülebilir iş modeli",
        ],
        "option_descriptions": [
            "Problem yeterince acil mi ve kullanıcı bunu çözmek için ürün kullanır mı?",
            "Bu problemi en güçlü yaşayan kullanıcı segmenti henüz net değil.",
            "İstenen deneyimin mevcut kaynaklarla yapılabilirliği belirsiz.",
            "Ürünün nasıl gelir üreteceği veya sürdürüleceği net değil.",
        ],
    },
]


def _write_markdown(session: dict, output: dict, mode: str, project_path: Path) -> Path:
    idea = session.get("idea") or session.get("context", "")
    lines = [
        f"# {idea}",
        "",
        f"*Generated at: {output['generated_at']}*",
        "",
    ]

    # Glossary table
    glossary = session.get("glossary", [])
    if glossary:
        lines.append("## Glossary")
        lines.append("")
        lines.append("| Term | Explanation |")
        lines.append("|------|-------------|")
        for g in glossary:
            lines.append(f"| **{g['term']}** | {g['explanation']} |")
        lines.append("")

    if mode == "plan":
        lines.append("## Planning Notes")
        lines.append("")
        lines.append("| # | Question | Answer | Decided By |")
        lines.append("|---|----------|--------|------------|")
        for i, n in enumerate(output.get("notes", []), 1):
            decider = _decider_label(n)
            lines.append(f"| {i} | {n['question']} | {n['answer']} | {decider} |")
        lines.append("")
    else:
        for cat, decisions in output.get("decisions", {}).items():
            cat_label = cat.replace("_", " ").title()
            lines.append(f"## {cat_label}")
            lines.append("")
            lines.append("| # | Question | Answer | Decided By |")
            lines.append("|---|----------|--------|------------|")
            for i, d in enumerate(decisions, 1):
                decider = _decider_label(d)
                lines.append(f"| {i} | {d['question']} | {d['answer']} | {decider} |")
            lines.append("")

    md_file = project_path / ("PLAN_NOTES.md" if mode == "plan" else "DECISIONS.md")
    md_file.write_text("\n".join(lines), encoding="utf-8")
    return md_file


def _decider_label(entry: dict) -> str:
    if entry.get("undecided"):
        return "⚠ Undecided"
    if entry.get("ai_decided"):
        conf = entry.get("confidence", 1.0)
        pct = f" ({int(conf * 100)}%)" if conf < 1.0 else ""
        return f"✦ AI{pct}"
    if entry.get("user_custom"):
        return "✏ User (custom)"
    return "✓ User"


def _start_daemon_once() -> None:
    global _daemon_started
    if _daemon_started:
        return

    # Check if port is already in use (another daemon instance running)
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", DAEMON_PORT))
            s.close()
        except OSError:
            # Port already in use — assume another daemon is running
            _daemon_started = True
            return

    _daemon_started = True

    app = create_app(sessions)

    def run() -> None:
        uvicorn.run(app, host="127.0.0.1", port=DAEMON_PORT, log_level="error")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.8)


def _persist_session(session: dict) -> None:
    """Write session state to central storage and project_path for crash recovery."""
    session["last_updated"] = datetime.now().isoformat()
    session["version"] = session.get("version", 1)

    out = {
        "session_id": session["session_id"],
        "idea": session.get("idea") or session.get("context", ""),
        "mode": session.get("mode", "clarification"),
        "project_path": session.get("project_path", ""),
        "status": session["status"],
        "questions": session["questions"],
        "glossary": session.get("glossary", []),
        "answers": session["answers"],
        "session_token": session.get("session_token"),
        "version": session["version"],
        "last_updated": session["last_updated"],
        "saved_at": datetime.now().isoformat(),
    }

    # Central atomic storage (for daemon resume)
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        fp = SESSIONS_DIR / f"{session['session_id']}.json"
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=SESSIONS_DIR, encoding="utf-8"
        )
        try:
            json.dump(out, tmp, indent=2, ensure_ascii=False)
            tmp.close()
            os.replace(tmp.name, fp)
        except Exception:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            raise
    except Exception:
        pass

    # Project-path copy
    try:
        project_path = Path(session["project_path"]) if session.get("project_path") else None
        if project_path:
            clarifier_dir = project_path / ".clarifier"
            clarifier_dir.mkdir(parents=True, exist_ok=True)
            (clarifier_dir / "session.json").write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    except Exception:
        pass


def _cleanup_session(session_id: str, session: dict) -> None:
    """Remove temporary session files after a session has been finalized."""
    try:
        project_path = Path(session["project_path"]) if session.get("project_path") else None
        if project_path:
            (project_path / ".clarifier" / "session.json").unlink(missing_ok=True)
    except Exception:
        pass
    try:
        (SESSIONS_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass
    sessions.pop(session_id, None)


def _open_browser_session(session: dict) -> dict[str, Any]:
    sessions[session["session_id"]] = session
    _persist_session(session)

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session['session_id']}?token={session['session_token']}"
    webbrowser.open(url)

    return {
        "session_id": session["session_id"],
        "session_token": session["session_token"],
        "url": url,
        "question_count": len(session["questions"]),
    }


SIMILAR_QUESTION_THRESHOLD = 0.86
DUPLICATE_FIX_HINT = (
    "Merge these into one question or assign genuinely different decision_axis values."
)


def _normalize_for_duplicate_check(value: Any) -> str:
    text = str(value or "").casefold().strip()
    return re.sub(r"[\W_]+", " ", text).strip()


def _validate_question_uniqueness(
    questions: list[dict[str, Any]],
    *,
    require_decision_axis: bool,
    compare_within_category: bool,
) -> dict[str, str] | None:
    ids: dict[str, str] = {}
    axes: dict[str, tuple[str, str]] = {}
    seen_texts: list[tuple[str, str, str, str]] = []

    for index, q in enumerate(questions, 1):
        qid = str(q.get("id") or "").strip()
        label = qid or f"#{index}"
        if not qid:
            return {"error": f"Question {label}: missing required id. {DUPLICATE_FIX_HINT}"}

        normalized_id = _normalize_for_duplicate_check(qid)
        if not normalized_id:
            return {"error": f"Question '{qid}': id must contain letters or numbers. {DUPLICATE_FIX_HINT}"}
        if normalized_id in ids:
            return {
                "error": (
                    f"Duplicate question id '{qid}' conflicts with '{ids[normalized_id]}'. "
                    f"{DUPLICATE_FIX_HINT}"
                )
            }
        ids[normalized_id] = qid

        question_text = str(q.get("question") or "").strip()
        if not question_text:
            return {"error": f"Question '{qid}': missing required question text. {DUPLICATE_FIX_HINT}"}

        normalized_axis = ""
        if require_decision_axis:
            axis = str(q.get("decision_axis") or "").strip()
            if not axis:
                return {
                    "error": (
                        f"Question '{qid}': missing required decision_axis. "
                        f"{DUPLICATE_FIX_HINT}"
                    )
                }
            normalized_axis = _normalize_for_duplicate_check(axis)
            if not normalized_axis:
                return {
                    "error": (
                        f"Question '{qid}': decision_axis must contain letters or numbers. "
                        f"{DUPLICATE_FIX_HINT}"
                    )
                }
            if normalized_axis in axes:
                other_id, other_axis = axes[normalized_axis]
                return {
                    "error": (
                        f"Duplicate decision_axis '{axis}' on question '{qid}' conflicts with "
                        f"question '{other_id}' using '{other_axis}'. {DUPLICATE_FIX_HINT}"
                    )
                }
            axes[normalized_axis] = (qid, axis)

        normalized_text = _normalize_for_duplicate_check(question_text)
        category = str(q.get("category") or "") if compare_within_category else "__all__"
        for other_id, other_category, other_text, other_raw_text in seen_texts:
            if other_category != category:
                continue
            similarity = SequenceMatcher(None, normalized_text, other_text).ratio()
            if similarity >= SIMILAR_QUESTION_THRESHOLD:
                scope = f" in category '{category}'" if compare_within_category else ""
                return {
                    "error": (
                        f"Near-duplicate question text{scope}: question '{qid}' is too similar "
                        f"to question '{other_id}' ({similarity:.2f}). "
                        f"Current: '{question_text}'. Existing: '{other_raw_text}'. "
                        f"{DUPLICATE_FIX_HINT}"
                    )
                }
        seen_texts.append((qid, category, normalized_text, question_text))

    return None


@mcp.tool()
def start_intent_clarification(idea: str, project_path: str) -> dict[str, Any]:
    """Open the required first-stage intent clarification session for a new project idea.

    Use this before start_clarification. The browser shows a fixed set of option-based
    questions designed to clarify the user's goal, target user, conceptual product logic,
    success criteria, non-goals, and unresolved assumptions. Users can add a custom
    answer alongside the provided options.

    This session writes no decisions file. After the user submits, call get_answers once,
    build your own short intent brief internally, then generate the second-stage
    start_clarification questions from that brief. Do not persist the intent brief.
    """
    _start_daemon_once()

    session_id = str(uuid.uuid4())
    session_token = str(uuid.uuid4())
    session: dict[str, Any] = {
        "session_id": session_id,
        "session_token": session_token,
        "mode": "intent",
        "idea": idea,
        "project_path": project_path,
        "questions": [dict(q) for q in INTENT_QUESTIONS],
        "glossary": [],
        "glossary_complete": True,
        "answers": {},
        "status": "pending",
        "version": 1,
        "last_updated": datetime.now().isoformat(),
    }
    result = _open_browser_session(session)
    result["message"] = (
        "Browser opened for intent clarification. Wait for the user to say they are done, "
        "then call get_answers(session_id) ONCE. Use the raw answers to build an internal "
        "intent brief before creating start_clarification questions. Do not call write_decisions "
        "for this session."
    )
    return result


@mcp.tool()
def start_clarification(
    idea: str,
    project_path: str,
    questions: list[dict[str, Any]],
    glossary: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Open a browser Q&A session to clarify a project idea before planning.

    Question schema (each item in the list):
        {
            "id":                  str,       # unique, e.g. "q_vision_01"
            "category":            str,       # Layer 1: project_vision
                                              # Layer 2: core_flows | feature_scope | content_model | ui_ux
                                              # Layer 3: tech_stack | architecture | database | security |
                                              #          performance | api | deployment | business_logic
            "type":                str,       # explicitly set "single_choice" | "multi_choice" |
                                              # "open_text" | "yes_no"; default single_choice exists
                                              # only for backward compatibility
            "question":            str,       # question text shown to the user
            "decision_axis":       str,       # required by agent policy; one unique decision being made
            "options":             list[str], # 2-5 option strings for single_choice / multi_choice;
                                              # auto-filled for yes_no; omitted for open_text
            "option_descriptions": list[str]  # plain-language descriptions (optional for all types);
                                              # one per option. Explain what happens if chosen.
            "max_length":          int,       # open_text only, max character count (default 500)
        }

    Question types:
    - single_choice: user picks exactly one option. Default if "type" is omitted
      only for backward compatibility; agents should set it explicitly.
    - multi_choice:  user may pick multiple options. Toggle behavior.
    - open_text:     free-text textarea, no options grid. Use max_length to limit.
    - yes_no:        two-button binary choice. options auto-filled with ["Evet","Hayır"] if missing.

    IMPORTANT: For new project ideas, first run start_intent_clarification and use
    those answers to form an internal intent brief. Then create these questions.
    Start with the needed 'project_vision' questions before asking any technical
    questions. Each question must map to one unique decision_axis; duplicate axes
    or near-duplicate question text are rejected before the browser session opens.
    When technical questions include jargon, supply a glossary so the user
    can look up unfamiliar terms during the session.

    Immediately creates project_path/.clarifier/session.json for crash recovery.
    Returns session_id, session_token and the URL opened in the browser.
    """
    if not questions:
        return {"error": "questions list cannot be empty"}

    uniqueness_error = _validate_question_uniqueness(
        questions,
        require_decision_axis=True,
        compare_within_category=True,
    )
    if uniqueness_error:
        return uniqueness_error

    # Normalize question types for backward compat + defaults
    for q in questions:
        q.setdefault("type", "single_choice")
        qtype = q["type"]
        if qtype in ("single_choice", "multi_choice"):
            if "options" not in q or len(q.get("options", [])) < 2:
                return {"error": f"Question '{q.get('id','?')}' type={qtype} requires at least 2 options"}
            if len(q["options"]) > 5:
                q["options"] = q["options"][:5]
                if "option_descriptions" in q:
                    q["option_descriptions"] = q["option_descriptions"][:5]
        elif qtype == "yes_no":
            if "options" not in q or len(q.get("options", [])) < 2:
                q["options"] = ["Evet", "Hayır"]
                q["option_descriptions"] = q.get("option_descriptions") or ["", ""]
        elif qtype == "open_text":
            q.setdefault("max_length", 500)
            q.pop("options", None)
            q.pop("option_descriptions", None)
        else:
            return {"error": f"Question '{q.get('id','?')}': unknown type '{qtype}'"}

    _start_daemon_once()

    session_id = str(uuid.uuid4())
    session_token = str(uuid.uuid4())
    session: dict[str, Any] = {
        "session_id": session_id,
        "session_token": session_token,
        "idea": idea,
        "project_path": project_path,
        "questions": questions,
        "glossary": glossary or [],
        "glossary_complete": bool(glossary),
        "answers": {},
        "status": "pending",
        "version": 1,
        "last_updated": datetime.now().isoformat(),
    }
    sessions[session_id] = session
    _persist_session(session)

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}?token={session_token}"
    webbrowser.open(url)

    return {
        "session_id": session_id,
        "session_token": session_token,
        "url": url,
        "question_count": len(questions),
        "message": (
            "Browser opened for second-stage clarification. This should only be used after "
            "start_intent_clarification for new project ideas. Call add_glossary(session_id, terms) "
            "to add technical terms. "
            "Wait for the user to say they are done, then call get_answers(session_id) ONCE. "
            "When completed, discuss undecided_questions with the user in the IDE."
        ),
    }


@mcp.tool()
def get_answers(session_id: str, wait_seconds: int = 0) -> dict[str, Any]:
    """Get answers after the user has submitted them in the browser.

    Call this ONCE after the user says they are done. Do NOT poll in a loop.
    Use wait_seconds to block until submission (long-poll, max 120s).

    Args:
        session_id:    From start_clarification or start_plan_clarification.
        wait_seconds:  If > 0, block up to N seconds waiting for user submission.
                       Returns immediately with status='pending' on timeout.

    Returns:
        status='pending'   — user has not submitted yet. Wait for user signal.
        status='completed' — all questions submitted.
            answers              — {question_id: {answer, ai_decides, custom, undecided, undecided_note}}
            ai_decision_needed   — [question_ids where user clicked 'AI KARAR VERSİN']
            undecided_questions  — [questions user marked as undecided; discuss HERE in the IDE]
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}

    if session["status"] != "completed":
        if wait_seconds > 0:
            token = session.get("session_token", "")
            try:
                from urllib.request import Request, urlopen
                import json as _json
                url = f"http://{DEFAULT_HOST}:{DAEMON_PORT}/api/session/{session_id}/answers?wait={wait_seconds}"
                req = Request(url)
                if token:
                    req.add_header("Authorization", f"Bearer {token}")
                with urlopen(req, timeout=wait_seconds + 5) as resp:
                    data = _json.loads(resp.read())
                if data.get("status") == "completed":
                    refreshed = _load_session_file(session_id)
                    if refreshed:
                        sessions[session_id] = refreshed
                        session = refreshed
                else:
                    return {
                        "status": "pending",
                        "message": f"Still waiting (long-poll timed out after {wait_seconds}s). User has not submitted yet.",
                    }
            except Exception:
                return {
                    "status": "pending",
                    "message": "User has not submitted yet (long-poll request failed). Wait for user signal.",
                }
        else:
            return {
                "status": "pending",
                "message": "User has not submitted yet. Wait for the user to say they are done, then try again.",
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

    mode = session.get("mode", "clarification")
    parts = []
    if ai_needed:
        parts.append(f"{len(ai_needed)} question(s) need your AI decision.")
    if undecided:
        parts.append(
            f"{len(undecided)} question(s) marked undecided — discuss with the user "
            "in the IDE, then include your conclusions in ai_decisions."
        )
    if mode == "intent":
        if not parts:
            parts.append("Intent answers received.")
        parts.append(
            "Build an internal intent brief from these raw answers, then create the "
            "second-stage start_clarification questions. Do not call write_decisions for this session."
        )
    else:
        if not parts:
            parts.append("All questions answered.")
        parts.append("Call write_decisions now.")

    response = {
        "status": "completed",
        "answers": answers,
        "ai_decision_needed": ai_needed,
        "undecided_questions": undecided,
        "message": " ".join(parts),
    }
    if mode == "intent":
        _cleanup_session(session_id, session)
    return response



@mcp.tool()
def write_decisions(
    session_id: str,
    ai_decisions: dict[str, str] | list[dict[str, Any]] | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Write final decisions.json to the project directory.

    Call after get_answers returns status=='completed'.

    Args:
        session_id:   From start_clarification.
        ai_decisions: Can be dict {question_id: "decision text"} (legacy),
                      or list of {id, answer, confidence (0.0-1.0), reasoning (optional)}.
                      Pass {} or omit if none.
        commit:       If True, run 'git add decisions.json DECISIONS.md && git commit'
                      in the project directory.

    Writes to: project_path/decisions.json (or plan_notes.json) + DECISIONS.md
    Cleans up: project_path/.clarifier/session.json and central session file.
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}
    if session.get("mode") == "intent":
        return {"error": "Intent sessions do not write decisions. Call get_answers and use the raw answers to build the second-stage clarification questions."}
    if session["status"] != "completed":
        return {"error": "Session not completed yet. Wait for user to submit."}

    if ai_decisions is None:
        ai_decisions = {}

    answers = {**session["answers"]}

    # Normalize ai_decisions — support both legacy dict and rich list format
    confidence_map: dict[str, float] = {}
    reasoning_map: dict[str, str] = {}
    if isinstance(ai_decisions, list):
        for entry in ai_decisions:
            qid = entry["id"]
            answers[qid] = {
                "answer": entry["answer"],
                "ai_decides": True,
                "custom": True,
            }
            if "confidence" in entry:
                confidence_map[qid] = float(entry["confidence"])
            if "reasoning" in entry:
                reasoning_map[qid] = str(entry["reasoning"])
    else:
        # Legacy dict format
        for qid, decision_text in ai_decisions.items():
            answers[qid] = {"answer": decision_text, "ai_decides": True, "custom": True}
            confidence_map[qid] = 1.0

    project_path = Path(session["project_path"])
    project_path.mkdir(parents=True, exist_ok=True)

    mode = session.get("mode", "clarification")

    # Helper to enrich entry with confidence & reasoning
    def _enrich_entry(entry: dict, qid: str) -> dict:
        if qid in confidence_map:
            entry["confidence"] = confidence_map[qid]
        if qid in reasoning_map:
            entry["reasoning"] = reasoning_map[qid]
        return entry

    glossary_entries = session.get("glossary", [])
    if mode == "plan":
        # Flat list — no category grouping
        notes = []
        for q in session["questions"]:
            qid = q["id"]
            ans = answers.get(qid, {})
            entry: dict[str, Any] = _enrich_entry({
                "question": q["question"],
                "answer": ans.get("answer", "— not answered —"),
                "ai_decided": bool(ans.get("ai_decides")),
                "user_custom": bool(ans.get("custom") and not ans.get("ai_decides")),
                "undecided": bool(ans.get("undecided")),
            }, qid)
            if ans.get("undecided_note"):
                entry["undecided_note"] = ans["undecided_note"]
            notes.append(entry)

        output: dict[str, Any] = {
            "planning_context": session.get("context", session.get("idea", "")),
            "generated_at": datetime.now().isoformat(),
            "notes": notes,
        }
        if glossary_entries:
            output["glossary"] = glossary_entries
        out_file = project_path / "plan_notes.json"

    else:
        # Category-grouped output (clarification mode)
        categories: dict[str, list[dict]] = {}
        for q in session["questions"]:
            qid = q["id"]
            cat = q.get("category", "other")
            ans = answers.get(qid, {})

            entry = _enrich_entry({
                "question": q["question"],
                "answer": ans.get("answer", "— not answered —"),
                "ai_decided": bool(ans.get("ai_decides")),
                "user_custom": bool(ans.get("custom") and not ans.get("ai_decides")),
                "undecided": bool(ans.get("undecided")),
            }, qid)
            if ans.get("undecided_note"):
                entry["undecided_note"] = ans["undecided_note"]

            categories.setdefault(cat, []).append(entry)

        output = {
            "project_idea": session["idea"],
            "generated_at": datetime.now().isoformat(),
            "decisions": categories,
        }
        if glossary_entries:
            output["glossary"] = glossary_entries
        out_file = project_path / "decisions.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate human-readable markdown
    md_path = _write_markdown(session, output, mode, project_path)

    # Optional git commit
    commit_error = None
    if commit:
        try:
            import subprocess
            subprocess.run(
                ["git", "add", str(out_file.name), str(md_path.name)],
                cwd=str(project_path), capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"chore: clarify decisions [idea-clarifier]"],
                cwd=str(project_path), capture_output=True, check=True,
            )
        except Exception as e:
            commit_error = str(e)

    # Remove session files
    try:
        (project_path / ".clarifier" / "session.json").unlink(missing_ok=True)
    except Exception:
        pass
    try:
        (SESSIONS_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass

    del sessions[session_id]

    base = {
        "success": True,
        "path": str(out_file),
        "markdown_path": str(md_path),
    }
    if commit:
        base["committed"] = commit_error is None
        if commit_error:
            base["commit_error"] = commit_error
    if mode == "plan":
        base["total_notes"] = len(output["notes"])
    else:
        base["categories"] = list(output["decisions"].keys())
        base["total_decisions"] = sum(len(v) for v in output["decisions"].values())
    return base


@mcp.tool()
def start_plan_clarification(
    context: str,
    project_path: str,
    questions: list[dict[str, Any]],
    glossary: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Pre-plan Q&A for an EXISTING project before writing an implementation plan.

    Use after exploring the codebase. Ask 5–15 targeted questions that you need
    answered before you can write a reliable plan.

    Question schema:
        {
            "id":                  str,        # unique, e.g. "p_01"
            "question":            str,        # the question text
            "type":                str,        # explicitly set "single_choice" | "multi_choice" |
                                               # "open_text" | "yes_no"; default single_choice exists
                                               # only for backward compatibility
            "options":             list[str],  # 2-5 options; auto-filled for yes_no; omitted for open_text
            "option_descriptions": list[str],  # optional plain-language descriptions
        }

    No "category" field needed.

    Writes plan_notes.json (not decisions.json) to project_path.
    """
    if not questions:
        return {"error": "questions list cannot be empty"}

    uniqueness_error = _validate_question_uniqueness(
        questions,
        require_decision_axis=False,
        compare_within_category=False,
    )
    if uniqueness_error:
        return uniqueness_error

    for q in questions:
        q.setdefault("type", "single_choice")
        qtype = q["type"]
        if qtype in ("single_choice", "multi_choice"):
            if "options" not in q or len(q.get("options", [])) < 2:
                return {"error": f"Question '{q.get('id','?')}' type={qtype} requires at least 2 options"}
            if len(q["options"]) > 5:
                q["options"] = q["options"][:5]
                if "option_descriptions" in q:
                    q["option_descriptions"] = q["option_descriptions"][:5]
        elif qtype == "yes_no":
            if "options" not in q or len(q.get("options", [])) < 2:
                q["options"] = ["Evet", "Hayır"]
                q["option_descriptions"] = q.get("option_descriptions") or ["", ""]
        elif qtype == "open_text":
            q.setdefault("max_length", 500)
            q.pop("options", None)
            q.pop("option_descriptions", None)
        else:
            return {"error": f"Question '{q.get('id','?')}': unknown type '{qtype}'"}

    _start_daemon_once()

    session_id = str(uuid.uuid4())
    session_token = str(uuid.uuid4())
    session: dict[str, Any] = {
        "session_id": session_id,
        "session_token": session_token,
        "mode": "plan",
        "context": context,
        "idea": context,
        "project_path": project_path,
        "questions": questions,
        "glossary": glossary or [],
        "glossary_complete": bool(glossary),
        "answers": {},
        "status": "pending",
        "version": 1,
        "last_updated": datetime.now().isoformat(),
    }
    sessions[session_id] = session
    _persist_session(session)

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}?token={session_token}"
    webbrowser.open(url)

    return {
        "session_id": session_id,
        "session_token": session_token,
        "url": url,
        "question_count": len(questions),
        "message": (
            "Browser opened for pre-plan clarification. "
            "Call add_glossary(session_id, terms) to add technical terms. "
            "Wait for the user to say they are done, then call get_answers(session_id) ONCE. "
            "When completed, discuss undecided_questions with the user in the IDE."
        ),
    }


@mcp.tool()
def add_glossary(
    session_id: str,
    terms: list[dict[str, str]],
) -> dict[str, Any]:
    """Add technical glossary terms to an active session so the browser UI
    updates live as the agent prepares them.

    Call this one or more times after start_clarification / start_plan_clarification.
    Send an empty terms list once all glossary terms have been added; this marks the
    glossary as complete so the browser can stop polling.
    Each call appends to the existing glossary list. The browser polls the session
    API and rebuilds the glossary card automatically when the term count changes.

    Args:
        session_id: From start_clarification or start_plan_clarification.
        terms:      List of {term, explanation}. Same schema as the glossary
                    parameter on the start_* tools.
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}
    if session["status"] == "completed":
        return {"error": "Session already completed. Cannot add terms."}

    existing: list[dict[str, str]] = session.setdefault("glossary", [])
    if not terms:
        session["glossary_complete"] = True
        _persist_session(session)
        return {
            "success": True,
            "total_terms": len(existing),
            "added": 0,
            "message": "Glossary marked as complete. Browser will stop polling.",
        }
    existing.extend(terms)
    session["glossary_complete"] = False
    _persist_session(session)
    return {
        "success": True,
        "total_terms": len(existing),
        "added": len(terms),
    }


@mcp.tool()
def suggest_followups(session_id: str) -> dict[str, Any]:
    """Return undecided questions with their context so the agent can
    discuss them with the user or create follow-up sessions.

    Call after get_answers returns status='completed', before write_decisions.

    Args:
        session_id: From start_clarification or start_plan_clarification.

    Returns:
        undecided: list of {question_id, question_text, category, note,
                   suggestions: [2 parçalanmış alt-soru önerisi]}
    """
    session = sessions.get(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found or already finalized."}
    if session["status"] != "completed":
        return {"error": "Session not completed yet. Wait for user to submit."}

    undecided = []
    for q in session["questions"]:
        qid = q["id"]
        ans = session["answers"].get(qid, {})
        if not ans.get("undecided"):
            continue
        note = ans.get("undecided_note", "")
        undecided.append({
            "question_id": qid,
            "question_text": q["question"],
            "category": q.get("category", ""),
            "original_options": q.get("options", []),
            "undecided_note": note,
            "suggestions": [
                {"focus": "scope", "prompt": f"Narrow the scope of: {q['question']}"},
                {"focus": "criteria", "prompt": f"What criteria would help decide: {q['question']}"},
            ],
        })

    if not undecided:
        return {"message": "No undecided questions found.", "undecided": []}

    return {
        "undecided": undecided,
        "count": len(undecided),
        "message": (
            f"{len(undecided)} undecided question(s). "
            "Discuss each with the user in the IDE, then include conclusions in ai_decisions "
            "when calling write_decisions."
        ),
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
