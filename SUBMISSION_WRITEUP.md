# Submission Write-Up: Dev Study Planner

## Problem Statement

Every developer learning DSA or a new tech stack faces the same problem: they start strong, then lose momentum because they have no structured system. Striver's A-Z DSA sheet contains 455 problems. Modern fullstack development requires mastery of 10+ technologies. Without a personal AI coach to plan, schedule, and track your sessions—most learners give up.

**Dev Study Planner** solves this by acting as an always-available AI study coach that knows exactly what you need to learn, breaks it into manageable Pomodoro-sized sessions, and confirms your commitment before scheduling each block.

---

## Solution Architecture

```
                      ┌─────────────────────────────┐
                      │  dev_study_planner_workflow  │
                      └─────────────────────────────┘
                                    │
                              ┌─────▼──────┐
                              │  security  │  ← PII scrub, injection detect,
                              │ checkpoint │    structured audit log
                              └─────┬──────┘
                    ┌───────────────┴────────────────┐
              SECURITY_EVENT                        CLEAN
                    │                                │
          ┌─────────▼──────────┐        ┌───────────▼────────────┐
          │  security_failure  │        │      orchestrator       │
          │  (access denied)   │        │  AgentTool → dsa_agent  │
          └────────────────────┘        │  AgentTool → tech_agent │
                                        └───────────┬────────────┘
                                                    │
                                        ┌───────────▼────────────┐
                                        │    schedule_study       │ ← HITL ✋
                                        │    (human approval)    │
                                        └───────────┬────────────┘
                                       ┌────────────┴───────────┐
                                   approved                  rejected
                                       │                        │
                              ┌────────▼──────┐      ┌─────────▼──────┐
                              │  save_plan    │      │  reject_plan   │
                              │  (MCP tools) │      │  (ask again)   │
                              └───────────────┘      └────────────────┘
```

---

## Concepts Used

| Concept | Implementation | File |
|---------|---------------|------|
| **ADK Workflow** | Graph-based `Workflow` with function nodes + dict-routed edges | `app/agent.py` |
| **LlmAgent** | `dsa_agent` and `tech_agent` as specialized sub-agents with domain-specific instructions | `app/agent.py` |
| **AgentTool** | Orchestrator delegates to `dsa_agent` and `tech_agent` via `AgentTool()` | `app/agent.py` |
| **MCP Server** | `mcp_server.py` exposes 4 tools via FastMCP / stdio transport | `app/mcp_server.py` |
| **Security Checkpoint** | Function node with PII regex, injection detection, audit logging | `app/agent.py` |
| **HITL (Human-in-the-loop)** | `schedule_study` uses `RequestInput` to pause and await human approval | `app/agent.py` |
| **ctx.state** | State sharing between nodes via `Event(state={...})` | `app/agent.py` |
| **Agents CLI** | `agents-cli scaffold create`, `agents-cli info`, `make playground` | `Makefile`, `agents-cli-manifest.yaml` |

---

## Security Design

| Control | Detail | Why It Matters |
|---------|--------|----------------|
| **PII Redaction** | Regex strips emails (`john@example.com` → `[EMAIL_REDACTED]`) and phone numbers | Prevents personal data from leaking into LLM context or logs |
| **Prompt Injection Detection** | Keyword scan: `ignore previous instructions`, `system prompt`, `override rules`, `bypass security` | Prevents jailbreak attacks from hijacking agent behavior |
| **Domain Restriction** | Blocks queries containing `exploit`, `hack`, `crack`, `torrent` | Keeps the agent on-topic and prevents misuse |
| **Structured Audit Log** | Every request is logged with `timestamp`, `session_id`, `severity: INFO/WARNING/CRITICAL` | Full traceability for compliance and debugging |

All security controls run **before any LLM is called**, making this a zero-trust gate.

---

## MCP Server Design

| Tool | Purpose | Used By |
|------|---------|---------|
| `get_study_todos()` | Fetches all pending and completed study tasks | `orchestrator` |
| `add_study_todo(task, category, estimation_pomodoros)` | Adds a DSA problem or tech topic to the local database | `save_plan`, `dsa_agent`, `tech_agent` |
| `complete_study_todo(task_id)` | Marks a task as complete when the user finishes it | `orchestrator` |
| `start_pomodoro_session(minutes)` | Registers a timed Pomodoro focus session (default: 25 min) | `orchestrator` |

The MCP server runs as a local subprocess (stdio transport), with no network exposure needed for local dev.

---

## HITL Flow

The `schedule_study` node implements a two-pass human-in-the-loop pattern:

1. **First pass**: Node generates the full Markdown plan (topics, categories, Pomodoro estimates) and yields a `RequestInput` with `interrupt_id="approved"`. Execution pauses.
2. **User sees the plan** in the playground UI and types `yes` or `no`.
3. **Second pass**: Node resumes, reads `ctx.resume_inputs["approved"]`, and routes:
   - `yes` → `save_plan` (writes to database via MCP)
   - `no` → `reject_plan` (asks user to refine the request)

This pattern ensures no study data is written without explicit human consent.

---

## Demo Walkthrough

Refer to the 3 sample test cases in `README.md`:

1. **Case 1** — Normal DSA + Tech plan → HITL approval → tasks saved
2. **Case 2** — PII in input → WARNING audit log → cleaned query continues
3. **Case 3** — Prompt injection attempt → CRITICAL audit → access denied, no LLM called

---

## Impact / Value Statement

**Who benefits**: Every self-taught developer, boot camp student, coding interview preparer, and career switcher who needs structure but can't afford a tutor.

**Why it matters**: Combining AI-driven personalization (knowing Striver's sheet, knowing what Docker or Kubernetes entails) with behavioral accountability (HITL confirmation, Pomodoro tracking) creates a uniquely effective study system. The security layer ensures it can be used safely even in shared or institutional environments.

**The result**: Developers study smarter — with AI that knows what to learn, when to pause, and how to stay on track.
