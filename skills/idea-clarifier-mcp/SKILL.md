---
name: idea-clarifier-mcp
description: Use when an agent needs to operate the Idea Clarifier MCP for intent-first project clarification, choose the right MCP tool, generate non-duplicative decision questions, collect browser answers, resolve undecided or AI-delegated choices, and write decisions.json or plan_notes.json.
---

# Idea Clarifier MCP

## Core Rule

Use Idea Clarifier MCP to turn vague product ideas or blocked implementation plans into explicit user decisions before planning or coding.

For a new project idea, do not start with stack, database, architecture, UI details, or feature lists. First understand the user's intent: goal, target user, problem context, conceptual product model, success criteria, non-goals, and the main unresolved assumption. Technical questions come later and only when the intent answers make them necessary.

If the Idea Clarifier MCP tools are not available, ask the user to enable the MCP server. Do not fake a browser session or invent submitted answers.

## Tool Decision Tree

| Situation | Use | Result |
| --- | --- | --- |
| New project idea, first pass | `start_intent_clarification(idea, project_path)` | Opens the fixed 7-question intent browser session |
| User submitted intent answers | `get_answers(session_id)` once | Returns raw intent answers, then the intent session is cleaned up |
| New project idea, second pass | `start_clarification(idea, project_path, questions)` | Opens product/technical decision session |
| Existing project before planning | `start_plan_clarification(context, project_path, questions)` | Opens a shorter pre-plan session |
| User is reading a decision session | `add_glossary(session_id, terms)` | Adds live glossary terms to the browser |
| User says they submitted a decision session | `get_answers(session_id)` once | Returns answers, AI-delegated ids, and undecided items |
| Finalize non-intent session | `write_decisions(session_id, ai_decisions)` | Writes `decisions.json` or `plan_notes.json` plus Markdown output |
| Undecided answers need structure | `suggest_followups(session_id)` | Returns context for IDE discussion, not a new browser session |

## New Project Flow

1. Call `start_intent_clarification(idea, project_path)`.
2. Tell the user the browser questions are open and wait for a clear completion signal.
3. Call `get_answers(session_id)` once. Do not poll in a loop.
4. Build a private intent brief. Do not write this brief to disk.
5. Generate second-stage questions from the intent brief.
6. Call `start_clarification(idea, project_path, questions)`.
7. Add glossary terms with `add_glossary`; finish with `add_glossary(session_id, [])`.
8. Wait for the user to submit, then call `get_answers(session_id)` once.
9. Resolve `undecided_questions` and `ai_decision_needed` in the IDE conversation.
10. Call `write_decisions(session_id, ai_decisions)`.

Private intent brief shape:

```text
Goal:
Target user:
Problem context:
Conceptual model:
Success criteria:
Non-goals:
Open assumption:
```

Intent sessions never write decisions. Calling `write_decisions` on an intent session is a misuse.

## Existing Project Flow

Use `start_plan_clarification` only after inspecting the existing codebase enough to know what is blocked. Ask 5-15 targeted questions whose answers are required before writing an implementation plan.

Do not use the intent stage for a narrow existing-project change unless the user's product intent is genuinely unclear. Existing project output is `plan_notes.json`; new project output is `decisions.json`.

## Decision Question Policy

Keep a private `decision_axis` ledger before generating second-stage questions. The MCP validates this contract and rejects duplicate axes or near-duplicate question text before opening a browser session.

Rules:

- One question equals one decision axis.
- Never ask the same `decision_axis` twice, even with different wording; duplicate axes are rejected by the MCP.
- Ask product and workflow questions before technical questions.
- Ask technical questions only when the intent brief creates a real near-term decision.
- For choice questions, explicitly set `type` to `single_choice` or `multi_choice`.
- Use `single_choice` only when one answer must win.
- Use `multi_choice` when several answers can naturally be true at the same time.
- Use `open_text` when options would distort the answer.
- Use `yes_no` only for a real binary decision.
- If multi-select answers conflict, resolve it later in the IDE conversation; do not open a new browser session.
- If `start_clarification` returns duplicate `id`, duplicate `decision_axis`, or near-duplicate question text, revise the question set and call it again. Merge repeated decisions into one question; do not merely rename `decision_axis` to bypass the validator when the decision is the same.

Question schema for `start_clarification`:

```python
{
    "id": "q_scope_01",
    "category": "feature_scope",
    "type": "single_choice",
    "decision_axis": "mvp_scope_boundary",
    "question": "What should define the first usable version?",
    "options": [
        "Only the core tracking loop",
        "Core loop plus collaboration",
        "Core loop plus reporting",
        "A polished end-to-end workflow"
    ],
    "option_descriptions": [
        "Smallest build. Fast validation, limited feature depth.",
        "Adds team value early, but requires sharing and permissions.",
        "Prioritizes visibility, but delays collaboration mechanics.",
        "Best demo quality, highest first-release scope."
    ]
}
```

For `single_choice` and `multi_choice`, provide 2-5 clear options. Add `option_descriptions` when trade-offs matter; each description should explain what choosing that option changes.

## Category Order

For new project second-stage sessions, ask roughly 12-25 targeted questions and order them from concept to implementation:

1. `project_vision`: purpose, audience, platform, main user action, scale, sustainability, differentiation.
2. `core_flows`: happy path, reject/undo, deadline behavior, concurrent use, onboarding.
3. `feature_scope`: MVP must-haves, out-of-scope items, priority rule, success metric, paid/free boundary.
4. `content_model`: business entities, relationships, states, ownership, required fields, custom fields.
5. `ui_ux`: navigation, home screen, primary views, empty states, desktop/mobile priority.
6. Technical categories: `tech_stack`, `architecture`, `database`, `security`, `performance`, `api`, `deployment`, `business_logic`.

Skip technical categories that are not needed yet. A shorter, sharper session is better than asking speculative implementation questions.

## Glossary

Use glossary terms only for jargon that appears in the questions.

Preferred sequence:

```python
result = start_clarification(...)
session_id = result["session_id"]
add_glossary(session_id, [
    {"term": "MVP", "explanation": "Minimum viable product: the smallest version that can validate the core value."}
])
add_glossary(session_id, [])
```

Keep glossary explanations short and practical. Do not add unused terms.

## Answer Handling

After a browser session is open, wait for the user to say they submitted it. Accept signals such as "answered", "done", "submitted", "cevapladim", "bitti", or "tamam".

Then call `get_answers(session_id)` once. If the user says they are done but submission may still be in flight, use one long-poll call such as `get_answers(session_id, wait_seconds=60)`.

When `get_answers` returns:

- `status == "pending"`: tell the user the browser form has not been submitted yet.
- `ai_decision_needed`: decide those items yourself and pass them in `ai_decisions`.
- `undecided_questions`: discuss them in the IDE conversation. Use `suggest_followups` only for structure.
- `answers[*].answer`: handle either a string or an array. Multi-select and custom answers can produce arrays.

Before `write_decisions`, ensure every AI-delegated or resolved undecided item has a concrete answer.

## Anti-Patterns

Avoid these behaviors:

- Asking "Which framework/database/cloud?" before intent is clear.
- Rephrasing the same decision as multiple questions.
- Treating `decision_axis` as a display label instead of a uniqueness guard.
- Using `single_choice` because it is the backward-compatible default.
- Asking broad technical categories just because they exist.
- Polling `get_answers` repeatedly while the user is still answering.
- Opening a second browser session to resolve an undecided answer.
- Calling `write_decisions` for an intent session.
