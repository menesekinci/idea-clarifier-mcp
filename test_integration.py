#!/usr/bin/env python3
"""Integrated test for idea-clarifier-mcp: daemon + API + browser"""

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn
from idea_clarifier.daemon import SESSIONS_DIR, create_app
from idea_clarifier.server import (
    start_intent_clarification,
    start_clarification,
    start_plan_clarification,
    get_answers,
    write_decisions,
    add_glossary,
    suggest_followups,
    sessions,
)

# Test project path
TEST_PROJECT = Path(tempfile.gettempdir()) / "idea-clarifier-test-project"
DAEMON_PORT = 7532


def start_daemon():
    """Start FastAPI daemon in background thread."""
    app = create_app(sessions)
    def run():
        uvicorn.run(app, host="127.0.0.1", port=DAEMON_PORT, log_level="error")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(2)
    print("[TEST] Daemon started on port 7532")


def test_api_health():
    """Test API health check."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{DAEMON_PORT}/api/session/nonexistent")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert "error" in data
            print("[TEST] PASS API health check passed")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            data = json.loads(e.read())
            assert "error" in data
            print("[TEST] PASS API health check passed")
            return True
        print(f"[TEST] FAIL API health check failed: {e}")
        return False
    except Exception as e:
        print(f"[TEST] FAIL API health check failed: {e}")
        return False


def test_intent_clarification_flow():
    """Test fixed first-stage intent clarification flow."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[TEST] SKIP Playwright not installed, skipping intent browser test")
        return False

    result = start_intent_clarification(
        idea="Test projesi - görev takip uygulaması",
        project_path=str(TEST_PROJECT),
    )

    assert "error" not in result, f"start_intent_clarification failed: {result}"
    assert "session_id" in result
    assert "session_token" in result
    assert result.get("question_count") == 7

    session_id = result["session_id"]
    session_token = result["session_token"]
    project_session_file = TEST_PROJECT / ".clarifier" / "session.json"
    central_session_file = SESSIONS_DIR / f"{session_id}.json"
    assert project_session_file.exists()
    assert central_session_file.exists()

    write_result = write_decisions(session_id=session_id, ai_decisions={})
    assert "error" in write_result
    assert "Intent sessions do not write decisions" in write_result["error"]

    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}?token={session_token}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: page_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(url)
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{DAEMON_PORT}/api/session/{session_id}",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert data.get("mode") == "intent"
            assert len(data.get("questions", [])) == 7
            assert data["questions"][0]["type"] == "single_choice"
            assert data["questions"][1]["type"] == "multi_choice"
            assert all(len(q.get("options", [])) == 4 for q in data["questions"])

        page.locator("#c-intent_goal .opt").nth(0).click()
        page.locator("#c-intent_problem_context .opt").nth(0).click()
        page.locator("#c-intent_problem_context .opt").nth(3).click()
        page.locator("#c-intent_target_user .opt").nth(1).click()
        page.locator("#c-intent_target_user .act-custom").click()
        page.locator("#c-intent_target_user .custom-ta").fill("Ajans ekipleri")
        page.locator("#c-intent_target_user .btn-save").click()
        page.locator("#c-intent_conceptual_model .opt").nth(0).click()
        page.locator("#c-intent_success_criteria .opt").nth(0).click()
        page.locator("#c-intent_success_criteria .opt").nth(1).click()
        page.locator("#c-intent_non_goals .opt").nth(0).click()
        page.locator("#c-intent_non_goals .opt").nth(1).click()
        page.locator("#c-intent_open_assumption .opt").nth(0).click()
        assert page.locator("#btn-submit").is_enabled()
        page.locator("#btn-submit").click()
        page.locator("#success.visible").wait_for(timeout=5000)
        assert not page_errors, f"Browser console/page errors: {page_errors}"
        browser.close()

    result = get_answers(session_id=session_id)
    assert result.get("status") == "completed"
    answers = result.get("answers", {})
    assert len(answers) == 7
    assert answers["intent_goal"]["answer"] == "Fikri doğrulamak"
    assert answers["intent_problem_context"]["answer"] == ["Dağınık takip", "Manuel iş yükü"]
    assert answers["intent_target_user"]["answer"] == ["Küçük ekip", "Ajans ekipleri"]
    assert answers["intent_target_user"]["custom"] is True
    assert answers["intent_conceptual_model"]["answer"] == "Kayıt/takip sistemi"
    assert answers["intent_success_criteria"]["answer"] == ["Düzenli kullanım", "Zaman/iş yükü azalması"]
    assert answers["intent_non_goals"]["answer"] == ["Ağır raporlama", "Gelişmiş entegrasyonlar"]
    assert answers["intent_open_assumption"]["answer"] == "Kullanıcı ihtiyacı"
    assert "Do not call write_decisions" in result.get("message", "")
    assert session_id not in sessions
    assert not project_session_file.exists()
    assert not central_session_file.exists()
    assert not (TEST_PROJECT / "decisions.json").exists()
    assert not (TEST_PROJECT / "DECISIONS.md").exists()

    print("[TEST] PASS intent clarification flow passed")
    return True


def test_start_clarification():
    """Test start_clarification tool."""
    questions = [
        {
            "id": "q_vision_01",
            "category": "project_vision",
            "type": "single_choice",
            "decision_axis": "primary_problem_type",
            "question": "Bu proje hangi temel sorunu çözüyor?",
            "options": ["Bireysel verimlilik", "Ekip koordinasyonu", "Müşteri hizmeti", "Süreç otomasyonu"],
            "option_descriptions": [
                "Kişisel görev takibi, odak artırma.",
                "Ekip üyeleri arası görev dağıtımı.",
                "Müşteri talep ve şikayetleri takip edilir.",
                "Tekrarlayan süreçleri otomatikleştirir."
            ]
        },
        {
            "id": "q_tech_01",
            "category": "tech_stack",
            "type": "single_choice",
            "decision_axis": "frontend_framework_choice",
            "question": "Hangi framework kullanılsın?",
            "options": ["React", "Vue", "Svelte", "Angular"],
            "option_descriptions": [
                "En popüler, büyük ekosistem.",
                "Daha basit öğrenme eğrisi.",
                "Kompilasyon tabanlı, hızlı.",
                "Enterprise tercihi, tam çözüm."
            ]
        },
        {
            "id": "q_multi_01",
            "category": "feature_scope",
            "type": "multi_choice",
            "decision_axis": "mvp_feature_groups",
            "question": "MVP'de hangi özellik grupları kesinlikle olsun?",
            "options": ["Görev listesi", "Kanban görünümü", "Bildirimler", "Raporlama"],
            "option_descriptions": [
                "En basit takip yüzeyi.",
                "Durumlara göre sürükle-bırak görünüm.",
                "Kullanıcıları değişikliklerden haberdar eder.",
                "İlk metrik ve özet ekranları."
            ]
        },
        {
            "id": "q_open_01",
            "category": "project_vision",
            "type": "open_text",
            "decision_axis": "project_name",
            "question": "Projenin adı ne olsun?",
            "max_length": 100
        },
        {
            "id": "q_yesno_01",
            "category": "security",
            "type": "yes_no",
            "decision_axis": "two_factor_auth_requirement",
            "question": "Two-factor authentication gerekli mi?"
        }
    ]
    
    result = start_clarification(
        idea="Test projesi - görev takip uygulaması",
        project_path=str(TEST_PROJECT),
        questions=questions,
        glossary=[
            {"term": "MVP", "explanation": "Minimum Viable Product - temel özelliklerle çıkan ilk sürüm."},
            {"term": "SSR", "explanation": "Server-Side Rendering - HTML'in sunucuda oluşturulması."}
        ]
    )
    
    assert "error" not in result, f"start_clarification failed: {result}"
    assert "session_id" in result
    assert "url" in result
    print(f"[TEST] PASS start_clarification passed - session_id: {result['session_id']}")
    return result["session_id"], result["session_token"]


def _minimal_clarification_question(qid, axis, question, category="project_vision"):
    return {
        "id": qid,
        "category": category,
        "type": "single_choice",
        "decision_axis": axis,
        "question": question,
        "options": ["Minimal", "Standart", "Gelişmiş", "Özel"],
        "option_descriptions": ["Basit tutar.", "Dengeli ilerler.", "Kapsamı büyütür.", "Özel gereksinimlere göre şekillenir."],
    }


def _minimal_plan_question(qid, question):
    return {
        "id": qid,
        "type": "single_choice",
        "question": question,
        "options": ["Minimal", "Standart", "Gelişmiş", "Özel"],
        "option_descriptions": ["Basit tutar.", "Dengeli ilerler.", "Kapsamı büyütür.", "Özel gereksinimlere göre şekillenir."],
    }


def _cleanup_session_files(session_id):
    sessions.pop(session_id, None)
    (SESSIONS_DIR / f"{session_id}.json").unlink(missing_ok=True)
    (TEST_PROJECT / ".clarifier" / "session.json").unlink(missing_ok=True)


def test_question_uniqueness_validation():
    """Reject duplicate ids, duplicate axes, and near-duplicate question text."""
    duplicate_id = start_clarification(
        idea="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            _minimal_clarification_question("q_same", "axis_one", "İlk sürümde ana kullanıcı kim olacak?"),
            _minimal_clarification_question("q_same", "axis_two", "İlk sürümde hangi problemi çözeceğiz?"),
        ],
    )
    assert "error" in duplicate_id
    assert "Duplicate question id" in duplicate_id["error"]

    missing_axis = start_clarification(
        idea="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            {
                "id": "q_missing_axis",
                "category": "project_vision",
                "type": "single_choice",
                "question": "İlk sürümde ana kullanıcı kim olacak?",
                "options": ["A", "B"],
            }
        ],
    )
    assert "error" in missing_axis
    assert "missing required decision_axis" in missing_axis["error"]

    duplicate_axis = start_clarification(
        idea="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            _minimal_clarification_question("q_axis_1", "mvp_scope_boundary", "MVP kapsamını hangi sınır belirlesin?"),
            _minimal_clarification_question("q_axis_2", "MVP Scope Boundary", "İlk sürümün kapsam kararı neye göre verilsin?"),
        ],
    )
    assert "error" in duplicate_axis
    assert "Duplicate decision_axis" in duplicate_axis["error"]

    similar_text = start_clarification(
        idea="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            _minimal_clarification_question("q_text_1", "target_user_segment", "İlk sürümde ana kullanıcı segmenti kim olacak?"),
            _minimal_clarification_question("q_text_2", "primary_user_group", "İlk sürümde ana kullanıcı segmenti kim olmalı?"),
        ],
    )
    assert "error" in similar_text
    assert "Near-duplicate question text" in similar_text["error"]

    different_categories = start_clarification(
        idea="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            _minimal_clarification_question("q_cat_1", "project_user_priority", "İlk sürümde ana kullanıcı segmenti kim olacak?", "project_vision"),
            _minimal_clarification_question("q_cat_2", "onboarding_user_priority", "İlk sürümde ana kullanıcı segmenti kim olmalı?", "core_flows"),
        ],
    )
    assert "error" not in different_categories, different_categories
    _cleanup_session_files(different_categories["session_id"])

    duplicate_plan_text = start_plan_clarification(
        context="Validation test",
        project_path=str(TEST_PROJECT),
        questions=[
            _minimal_plan_question("p_1", "OAuth eklerken kullanıcı girişi nasıl çalışmalı?"),
            _minimal_plan_question("p_2", "OAuth eklerken kullanıcı girişi nasıl çalışmalı?"),
        ],
    )
    assert "error" in duplicate_plan_text
    assert "Near-duplicate question text" in duplicate_plan_text["error"]

    print("[TEST] PASS question uniqueness validation passed")


def test_add_glossary(session_id):
    """Test add_glossary tool."""
    result = add_glossary(
        session_id=session_id,
        terms=[
            {"term": "ORM", "explanation": "Object-Relational Mapping - veritabanı tablolarını kod nesnelerine dönüştürür."}
        ]
    )
    assert result.get("success") is True
    assert result.get("total_terms") == 3  # 2 initial + 1 new
    assert sessions[session_id].get("glossary_complete") is False

    result = add_glossary(
        session_id=session_id,
        terms=[
            {"term": "API", "explanation": "Application Programming Interface - sistemlerin birbirleriyle konuşmasını sağlar."}
        ]
    )
    assert result.get("success") is True
    assert result.get("total_terms") == 4
    assert sessions[session_id].get("glossary_complete") is False

    result = add_glossary(session_id=session_id, terms=[])
    assert result.get("success") is True
    assert result.get("total_terms") == 4
    assert sessions[session_id].get("glossary_complete") is True
    print("[TEST] PASS add_glossary passed")


def test_browser_ui(session_id, session_token):
    """Test browser UI using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[TEST] SKIP Playwright not installed, skipping browser test")
        return False
    
    url = f"http://127.0.0.1:{DAEMON_PORT}/session/{session_id}?token={session_token}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page_errors = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: page_errors.append(msg.text) if msg.type == "error" else None)
        
        # Navigate to session page
        page.goto(url)
        time.sleep(1)
        
        # Check page loaded
        title = page.title()
        print(f"[TEST] Browser page title: {title}")
        
        # Check session data loaded via API
        page_content = page.content()
        assert "Test projesi" in page_content or len(page_content) > 1000, "Page content too short"
        assert page.locator("#btn-submit").get_attribute("onclick") == "submitAnswers()"
        assert not page_errors, f"Browser console/page errors: {page_errors}"
        
        # Test API directly for session data
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{DAEMON_PORT}/api/session/{session_id}",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            assert data.get("mode") == "clarification"
            assert len(data.get("questions", [])) == 5
            assert len(data.get("glossary", [])) == 4
            assert data.get("glossary_complete") is True
            print("[TEST] PASS Session API data correct")

        # Exercise the real browser submit path through the header button.
        page.locator("#c-q_vision_01 .opt").nth(1).click()
        page.locator("#c-q_tech_01 .opt").first.click()
        page.locator("#c-q_tech_01 .act-custom").click()
        page.locator("#c-q_tech_01 .custom-ta").fill("Preact değerlendirmesi")
        page.locator("#c-q_tech_01 .btn-save").click()
        tech_answer = page.evaluate("answers['q_tech_01']")
        assert tech_answer["answer"] == ["React", "Preact değerlendirmesi"]
        assert tech_answer["custom"] is True
        assert page.locator("#c-q_tech_01 .opt.sel").count() == 1
        page.locator("#c-q_multi_01 .opt").nth(0).click()
        page.locator("#c-q_multi_01 .opt").nth(1).click()
        multi_answer = page.evaluate("answers['q_multi_01']")
        assert multi_answer["answer"] == ["Görev listesi", "Kanban görünümü"]
        page.locator("#c-q_open_01 textarea").fill("TaskMaster Pro")
        page.locator("#c-q_yesno_01 .opt").first.click()
        assert page.locator("#btn-submit").is_enabled()
        page.locator("#btn-submit").click()
        page.locator("#success.visible").wait_for(timeout=5000)
        
        browser.close()
        print("[TEST] PASS Browser UI test passed")
        return True


def test_submit_answers(session_id, session_token):
    """Test submitting answers via API."""
    import urllib.request
    
    answers = {
        "q_vision_01": {"answer": "Ekip koordinasyonu", "ai_decides": False, "custom": False, "undecided": False},
        "q_tech_01": {"answer": "React", "ai_decides": False, "custom": False, "undecided": False},
        "q_multi_01": {"answer": ["Görev listesi", "Kanban görünümü"], "ai_decides": False, "custom": False, "undecided": False},
        "q_open_01": {"answer": "TaskMaster Pro", "ai_decides": False, "custom": True, "undecided": False},
        "q_yesno_01": {"answer": "Evet", "ai_decides": False, "custom": False, "undecided": False}
    }
    
    req = urllib.request.Request(
        f"http://127.0.0.1:{DAEMON_PORT}/api/session/{session_id}/answers",
        data=json.dumps({"answers": answers}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {session_token}"
        },
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
        assert data.get("success") is True
        print("[TEST] PASS Submit answers passed")


def test_get_answers(session_id):
    """Test get_answers MCP tool."""
    result = get_answers(session_id=session_id)
    assert result.get("status") == "completed"
    assert "answers" in result
    assert len(result["answers"]) == 5
    print("[TEST] PASS get_answers passed")
    return result


def test_suggest_followups(session_id):
    """Test suggest_followups tool."""
    result = suggest_followups(session_id=session_id)
    assert "undecided" in result
    print(f"[TEST] PASS suggest_followups passed - {result.get('count', 0)} undecided questions")


def test_write_decisions(session_id):
    """Test write_decisions tool."""
    result = write_decisions(
        session_id=session_id,
        ai_decisions={},
        commit=False
    )
    assert result.get("success") is True
    assert "path" in result
    
    # Check output files exist
    decisions_file = TEST_PROJECT / "decisions.json"
    markdown_file = TEST_PROJECT / "DECISIONS.md"
    
    assert decisions_file.exists(), f"decisions.json not found at {decisions_file}"
    assert markdown_file.exists(), f"DECISIONS.md not found at {markdown_file}"
    
    # Validate JSON structure
    with open(decisions_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    assert "project_idea" in data
    assert "decisions" in data
    assert "generated_at" in data
    assert "glossary" in data
    
    print("[TEST] PASS write_decisions passed")
    print(f"[TEST] Output files: {decisions_file}, {markdown_file}")
    
    # Print sample output
    print("\n[TEST] Sample decisions.json output:")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:800] + "...")
    
    return result


def cleanup():
    """Clean up test files."""
    import shutil
    if TEST_PROJECT.exists():
        shutil.rmtree(TEST_PROJECT)
    print("[TEST] Cleanup complete")


def main():
    print("=" * 60)
    print("IDEA-CLARIFIER-MCP INTEGRATION TEST")
    print("=" * 60)
    
    # Clean up any previous test artifacts
    cleanup()
    TEST_PROJECT.mkdir(parents=True, exist_ok=True)
    
    # Start daemon
    start_daemon()
    
    # Run tests
    tests_passed = 0
    tests_failed = 0
    
    # Test 1: API Health
    if test_api_health():
        tests_passed += 1
    else:
        tests_failed += 1

    # Test 2: Question uniqueness validation
    try:
        test_question_uniqueness_validation()
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL question uniqueness validation failed: {e}")
        tests_failed += 1

    # Test 3: Intent clarification
    try:
        if test_intent_clarification_flow():
            tests_passed += 1
        else:
            tests_failed += 1
    except Exception as e:
        print(f"[TEST] FAIL intent clarification flow failed: {e}")
        tests_failed += 1
    
    # Test 4: Start clarification
    try:
        session_id, session_token = test_start_clarification()
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL start_clarification failed: {e}")
        tests_failed += 1
        return
    
    # Test 5: Add glossary
    try:
        test_add_glossary(session_id)
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] ✗ add_glossary failed: {e}")
        tests_failed += 1
    
    # Test 6: Browser UI
    try:
        if test_browser_ui(session_id, session_token):
            tests_passed += 1
        else:
            tests_failed += 1
    except Exception as e:
        print(f"[TEST] FAIL Browser UI test failed: {e}")
        tests_failed += 1
    
    # Test 7: Submit answers
    try:
        test_submit_answers(session_id, session_token)
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL Submit answers failed: {e}")
        tests_failed += 1
    
    # Test 8: Get answers
    try:
        test_get_answers(session_id)
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL get_answers failed: {e}")
        tests_failed += 1
    
    # Test 9: Suggest followups
    try:
        test_suggest_followups(session_id)
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL suggest_followups failed: {e}")
        tests_failed += 1
    
    # Test 10: Write decisions
    try:
        test_write_decisions(session_id)
        tests_passed += 1
    except Exception as e:
        print(f"[TEST] FAIL write_decisions failed: {e}")
        tests_failed += 1
    
    # Summary
    print("\n" + "=" * 60)
    print(f"TEST RESULTS: {tests_passed} passed, {tests_failed} failed")
    print("=" * 60)
    
    # Cleanup
    cleanup()
    
    return tests_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
