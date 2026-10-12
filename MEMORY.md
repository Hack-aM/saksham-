# MEMORY.md: Saksham

> Persistent project memory. Update after every task. Statuses: DONE, IN PROGRESS, NEXT, BLOCKED, DECISIONS, KNOWN ISSUES.

## Project overview
Saksham is an AI agent that audits a project before GitHub push and deploy, proposes fixes as an approved diff, pushes to a new repo, deploys, and verifies the live URL. Built by a student team (2-4 people) for a hackathon with a 24-48 hour MVP window. Earlier placeholder name: DeploySafe. Language of conversation with the user: Hinglish.

## Current architecture (see ARCHITECTURE.md)
FastAPI pipeline: scanner, audit, fixer (LLM), github_push, deployer, with Pydantic schemas and SSE progress. UI is a sidebar app with a 4-step progress bar. No code exists yet.

## DECISIONS (made in conversation)
- D1: Do not train a model; use an LLM tool-calling agent (Google Gemini `gemini-2.5-flash`).
- D2: Differentiator is a safety layer: pre-push audit, approved auto-fix with diff, post-deploy verification, beginner-friendly explanations.
- D3: MVP niche: student FastAPI (+ React) projects; deploy platform: Render; do not support everything.
- D4: Rules first for detection; LLM only when rules fail. Templates for generated files; LLM fills blanks.
- D5: Human approval before any push; secret gate blocks push.
- D6: GitHub Personal Access Token for MVP (scopes `repo`, `workflow`), new repos only, never delete or force-push.
- D7: Keep MVP simple: no LangGraph, Redis, or Celery.
- D8: Stack: Python 3.11, FastAPI, Uvicorn, Pydantic v2, GitPython, PyGithub, gitleaks, SSE, SQLite, pytest, Google GenAI SDK.
- D9: Demo: planted API key and wrong port, score 40 to 95, 2 minutes; backup video; stat from scanning 20-30 public student repos.
- D10: PPT is 7 slides (structure in TASKS.md T34). Biggest shortlist factor: specific real problem plus proof it works.
- D11: Project name is Saksham.
- D12: Design: teal/white UI, Plus Jakarta Sans, English language throughout, cards & sidebar design.
- D13: Product form: Standalone Web Application with full pipeline (Pre-push audit -> diff approval -> GitHub push -> Render live deploy -> Verification) [NC-1 & NC-13].
- D14: UI Framework: React (Vite) with vanilla CSS matching DESIGN.md tokens [NC-2].
- D15: LLM Provider: Google Gemini API (`gemini-2.5-flash` via `google-genai` / `google-generativeai`) [NC-3].
- D16: Deploy Platform: Render API. No mock deployer in product flow; MOCK allowed only in tests [NC-4].
- D17: Persistence: SQLite database (`saksham.db`) for run and deploy history [NC-5].
- D18: Authentication: NC-6 REOPENED. Earlier decision was single-user, no login in MVP. User now wants a login page with GitHub login and email login. T35 implements Login screen (UI only; dark theme, login route only, no fake login, no credentials sent/stored). T36 (Auth backend) proposed and BLOCKED pending user decisions. [NC-6].
- D19: Readiness Score: Base 100; High severity -30, Medium -15, Low -5; bounded 0-100 [NC-7].
- D20: UI Language: English throughout the application [NC-8].
- D21: Upload method: ZIP upload (max 25MB, path-traversal validated); scan git history if `.git` is included, else report "history not available" [NC-10].
- D22: Environment: Python 3.11 with pinned dependencies [NC-11].

## DONE
- Idea shaping, differentiation and judge answer.
- Workflow, tech stack, 8-step build plan, risks list.
- Shareable guide page: https://claude.ai/artifact/Cg228MNb6QhbZHtmiifHcY
- UI design canvas (3 screens): https://claude.ai/artifact/GrZE6yjTnAsu47BtBKqarV
- Six documentation files created and synchronized.
- **T00: Resolved all blocking clarifications (NC-1 through NC-8, NC-10, NC-11, NC-13).**
- **T01: Repository and folder skeleton created matching ARCHITECTURE.md (backend modules, React Vite UI skeleton, .gitignore, README.md, test fixtures folder).**
- **T02: Dependencies pinned in requirements.txt, .env.example created, config.py typed validation implemented and verified via unit tests.**
- **T03: Test fixture projects created (`tests/fixtures/vulnerable-demo-app/` with high-entropy planted key on line 12 and `tests/fixtures/clean-app/`) with automated test suite in `tests/test_fixtures.py`.**
- **T04: Persistence for deploy history implemented in `db.py` (SQLite `saksham.db` with `analyses`, `issues`, `patches`, `deployments` tables, parameterized queries, and zero stored secrets) and verified via `tests/test_db.py`.**
- **T05: GitHub token validation implemented in `github_push.py` (verifying `repo` and `workflow` scopes, rejecting fine-grained tokens, no token leaks in errors/logs) and verified via `tests/test_github_token.py`.**
- **T07: Pydantic schemas implemented in `schemas.py` (`Issue`, `Patch`, `AnalysisResult`, `DeployResult`) with field validation (severity enums, score bounds 0-100) and documented mapping to `db.py`, verified via `tests/test_schemas.py`.**
- **T08: Safe upload extraction hardened and verified in `upload.py` and `main.py` (actual bytes written limit enforcement against spoofed headers, chunk-streaming body reading in upload route, backslash traversal prevention, .git sanitization deleting hooks and replacing config with minimal safe config), verified via `tests/test_upload.py`.**
- **T09: Scanner implemented in `scanner.py` (rule-based detection using `ast.parse` and regex fallback without executing untrusted code, FastAPI & Python detection, entry point & port extraction, package.json / Node unsupported message, empty/unknown handling, and `ScanResult` Pydantic model in `schemas.py` with T15 LLM fallback extension point) and verified via `tests/test_scanner.py` (11 unit tests).**
- **T10: Secret scan of files implemented in `audit.py` (Gitleaks CLI subprocess with safe arguments, timeout, `--no-git`, `--redact`, `--ignore-gitleaks-allow`, Saksham's own config in `templates/gitleaks.toml`, dummy `.gitleaksignore` override, and report written outside target project, converting findings to High severity `Issue` objects) and verified via `tests/test_audit.py` (4 unit tests).**
- **T11: Secret scan of git history implemented in `audit.py` (`scan_git_history` with git mode, safe.directory protection, commit hash reporting in explanation, de-duplication against working tree secrets, and 'history not available' fallback), verified via `tests/test_audit.py` (3 unit tests).**
- **T12: Configuration checks implemented in `audit.py` (`check_env_in_gitignore`, `check_hardcoded_localhost`, `check_debug_enabled`, `check_hardcoded_port`, `check_junk_files` using AST/regex static inspection with central `DEFAULT_CHECK_SEVERITIES` table), verified via `tests/test_audit.py` (6 unit tests).**
- **T13: Readiness score implemented in `audit.py` (`calculate_readiness_score` with score formula 100 - High*30 - Med*15 - Low*5 clamped 0..100, weights in `config.py` `ISSUE_SEVERITY_DEDUCTIONS`, returning score + line-by-line deduction reasons; `vulnerable-demo-app` fixture reduced to exactly 3 planted issues giving score 40, `extra-issues-app` created for debug/localhost/junk tests, and safe.directory subprocess-scoped without mutating global git config), verified via `tests/test_audit.py` (4 score tests passed).**
- **T14: Analyze endpoint implemented in `main.py` (`POST /analyze` safely streaming uploaded ZIP, creating isolated workspace in `tmp/runs/{run_id}`, executing full scan and audit pipeline, maintaining in-memory active runs registry `RUNS`, persisting redacted analysis records in SQLite `saksham.db`, cleaning up stale workspaces on startup and via TTL), verified via `tests/test_analyze.py` (8 unit & integration tests).**
- **T15: Gemini LLM Client implemented in `llm.py` (`GeminiLLMClient` with typed `generate_text` and `generate_structured` methods, `google-genai` SDK integration, explicit HTTP request timeouts, Pydantic model validation, automatic repair retry on malformed JSON, and zero secret logging), verified via `tests/test_llm.py` (9 unit tests using mocks).**
- **T16: Auto-fix Patch Proposal Layer implemented in `fixer.py` (`propose_patches_for_issues` combining deterministic templates for standard config issues with `GeminiLLMClient` structured generation, strict path boundary validation, no shell injection, zero raw secrets sent, and strictly read-only in-memory proposal generation), verified via `tests/test_fixer.py` (11 unit tests using mocks).**
- **T17: Patch Application & Unified Diff Layer implemented in `fixer.py` (`apply_patch`, `apply_patches`, `generate_unified_diff`, `generate_patch_diff` with mandatory `APPROVED` status enforcement, workspace path boundary containment, exact old-content matching, in-memory simulation for all-or-nothing batch application, atomic temporary replacement writes, and secret-masked diffs), verified via `tests/test_patch_apply.py` (12 unit tests).**
- **T18: Deterministic Starter Template Generation implemented in `templates/` and `fixer.py` (`Dockerfile.template`, `gitignore.template`, `ci.yml.template`, `README.md.template`, `env_example.template`, `render_template()`, `propose_missing_file_patches()` generating structured Patch proposals with status SUGGESTED without calling LLM or writing to disk), verified via `tests/test_templates.py` (7 unit tests).**
- **T19: Approve Endpoint & Secret Re-Scan Gate implemented in `main.py` (`POST /approve` accepting `ApproveRequest`, applying approved patches via `apply_patches()`, running mandatory secret re-scan gate via `audit_project()`, and returning typed `ApproveResponse` with score and remaining issues), verified via `tests/test_approve.py` (4 unit & integration tests).**
- **T20: GitHub Repository Creation & Push implemented in `github_push.py` (`validate_repo_name()`, `validate_github_token()`, `create_remote_repo()` with transient retry, `pre_push_secret_check()` blocking on High secrets, `commit_and_push_workspace()` with workspace-scoped safe.directory, forbidden file checks, .gitignore compliance, no force-push, immediate token sanitization from git config, and full `push_workspace_to_github()` pipeline), verified via `tests/test_github_push.py` (24 unit and mock tests).**
- **T21: Render Deployer implemented in `deployer.py` (`validate_service_name()`, `validate_render_api_key()`, `create_render_service()` with transient 5xx retry and fail-fast 4xx validation, `set_render_env_vars()`, `trigger_render_deploy()`, `poll_deploy_status()` lifecycle tracker, and `deploy_project_to_render()` returning typed `RenderDeployResult`), verified via `tests/test_deployer.py` (17 unit and mock tests).**
- **T22: Deployment Verification & Bounded Self-Fix Loop implemented in `deployer.py` (`verify_deployment()`, `diagnose_deployment_failure()`, `run_self_fix_loop()`, `VerificationResult`, `SelfFixAttempt`, `SelfFixResult`), verified via `tests/test_verify_selffix.py` (17 unit and mock tests).**
- **T23: SSE Progress Streaming implemented in `main.py` and `schemas.py` (`GET /events/{run_id}` streaming `ProgressEvent` payloads over Server-Sent Events, bounded history buffer, subscriber queue broadcast, safe disconnect handling, keep-alive heartbeat, zero secret leakage via `redact_text()`, and automatic stream termination on terminal events), verified via `tests/test_sse.py` (7 unit and integration tests).**
- **T24: React app skeleton and theme implemented in `frontend/` (full DESIGN.md design tokens in CSS variables, 224px Sidebar with Saksham branding and SVG nav icons, 4-step StepBar pill navigation, reusable Card, Button, Badge primitives, and responsive layout), verified via Vite build and full pytest regression suite (210 passed).**
- **T25: Upload screen implemented in `frontend/` (`UploadScreen.jsx` with drag-and-drop ZIP upload, 25MB validation, repository configuration fields, `POST /analyze` integration, loading states, error banners, and preserved `run_id` analysis state for Step 2), verified via Vite production build and full pytest regression suite (210 passed).**
- **T26: Audit screen implemented in `frontend/` (`AuditScreen.jsx` rendering real `AnalysisResult` data with 56px Deploy Readiness Score visualization, itemized deduction reasons, categorized security & config findings with severity filters, clean/empty state handling, and fix review summary), verified via Vite production build and full pytest regression suite (210 passed).**
- **T27: Live screen implemented in `frontend/` (`LiveScreen.jsx` connecting to `GET /events/{run_id}` via native EventSource with 5-stage deployment checklist, autoscrolling streaming terminal log, bounded reconnect handling, terminal success/error handling, and live service/repo URL links), verified via Vite production build and full pytest regression suite (210 passed).**
- **T28: History, Connections, Settings screens implemented in `frontend/` (`HistoryScreen.jsx`, `ConnectionsScreen.jsx`, `SettingsScreen.jsx`, `App.jsx`, `main.py`, `tests/test_history_settings.py`) with SQLite `/history` querying, safe integration status metadata `/connections`, operational parameters `/settings`, and functional sidebar navigation, verified via Vite production build and full pytest regression suite (214 passed).**
- **T29: End-to-end happy path implemented and verified across whole pipeline (`main.py`, `frontend/src/App.jsx`, `frontend/src/components/ConnectionsScreen.jsx`, `db.py`, `deployer.py`, `tests/test_e2e_happy_path.py`), orchestrating ZIP upload -> analyze -> audit -> patch approval -> secret gate -> mocked GitHub push -> mocked Render deploy -> live health verification & self-fix -> SQLite history persistence -> real-time SSE progress streaming -> terminal completion, verified via Vite build and full pytest regression suite (223 passed).**
- **T30: Final Integration Hardening and Demo Readiness verified across the complete application (`main.py`, `db.py`, `config.py`, `schemas.py`, `upload.py`, `scanner.py`, `audit.py`, `fixer.py`, `github_push.py`, `deployer.py`, `redact.py`, `frontend/src/*`, `README.md`, `tests/*`). Full codebase security audit passed with zero exposed credentials; human approval and secret gate verified; bounded self-fix and SSE resilience confirmed; API error responses sanitized; and README documentation completed, verified via clean Vite production build and full pytest regression suite (223 passed).**
- **T35: Login screen (UI only) implemented in `frontend/` (`LoginScreen.jsx`, `App.jsx`, `Sidebar.jsx`, `index.css`). Created two-column layout with scoped dark theme (#0E1418 page bg, #121A20 preview panel, #25313A border, #18232B cards, #E8EEF2 text, #9DB0BC muted, #33424D input border, #4FC4BB accent with #07211F button text, High badge bg #2C1A19 / text #FF8A80, Medium badge bg #2B2312 / text #F2C46B; Plus Jakarta Sans; min 44px control height; 2px accent focus ring; WCAG AA contrast). Form column contains logo, heading, subtitle, primary Continue with GitHub button with inline SVG mark, helper text, divider, email and password inputs with labels and autocomplete, forgot password link, secondary Sign in with email button, and Create an account footer. Right preview panel shows sample Deploy Readiness 40/100 card with Push blocked badge, 3 issue rows, and 2 sub-cards (Fixes and Deploy), hidden on <= 860px. Verified no fake authentication: buttons alert that backend auth is pending T36, no credentials sent or stored. Existing screens completely unstyled. Verified via clean Vite build (`npm run build` in 9.27s) and pytest regression suite (226 passed).**

## IN PROGRESS
- None.

## NEXT
- Waiting for user decisions on T36 Auth backend (BLOCKED) or next instruction.

## BLOCKED
- **T36: Auth backend** (needs user decision on GitHub OAuth, email auth method, and how the GitHub token for repo creation changes).

## PENDING DECISIONS (Needs clarification)
- NC-6 (REOPENED: User decision needed for T36 on GitHub OAuth, email auth method, and GitHub repo creation token changes).
- Non-blocking: NC-9 (Hackathon specifics: deadline, team size), NC-12 (Exact extra screens mockup details).

## KNOWN ISSUES
- None.

## KNOWN BUGS
- None (223 passed, 0 skipped, 0 failures).

## Important constraints
- Hackathon time: 24-48 hours; team 2-4; skills Python, FastAPI, React.
- Reliability in the niche beats breadth.
- Free-tier platform limits and cold starts; test tokens and accounts before the event.
- Idea must not be generic.

## Important user requirements
- Standalone web app with React + Vite and FastAPI.
- Real Render deployment with health check verification; MOCK deployer strictly isolated to tests.
- English UI copy with DESIGN.md color palette and layout.
- Documentation must be kept strictly updated.

## Changes made during development
- 2026-10-08: T00 completed. Resolved NC-1 to NC-8, NC-10, NC-11, NC-13. Updated PRD.md, ARCHITECTURE.md, DESIGN.md, TASKS.md, MEMORY.md.
- 2026-10-08: T01 & T02 completed. Created project structure, backend module skeletons, .gitignore, README.md, requirements.txt, .env.example, config.py, and unit tests (17 tests passing).
- 2026-10-08: React/Vite early scaffolding files created (`frontend/package.json`, `frontend/index.html`, `frontend/vite.config.js`, `frontend/src/index.css`, `frontend/src/main.jsx`, `frontend/src/App.jsx`). These belong to T24 and will not be extended until T24.
- 2026-10-08: Installed Python 3.11.9, created `.venv`, updated `requirements.txt` (`google-genai==2.29.0`, `pydantic==2.12.5`), added `GEMINI_MODEL=` to `.env.example`.
- 2026-10-08: T03 verified and completed. Planted high-entropy key on line 12 of `vulnerable-demo-app/config.py`, verified endpoints on both fixtures. Removed unverified default from `GEMINI_MODEL`.
- 2026-10-08: T04 completed & hardened. Added `redact.py` helper to mask secrets, applied sanitization in `db.py` before SQLite insertion, and added raw SQLite file binary verification test.
- 2026-10-08: T05 completed. Implemented `validate_github_token` in `github_push.py` with `repo` and `workflow` scope enforcement, fine-grained PAT rejection, and tests in `tests/test_github_token.py`.
- 2026-10-08: T07 completed. Added Pydantic schemas in `schemas.py`, enhanced `redact.py` with generic assignment & Bearer token masking, and added test suites `tests/test_redact.py` and `tests/test_schemas.py` (48 tests).
- 2026-10-08: T08 completed & hardened. Implemented `extract_project_zip` in `upload.py`, chunk-streaming `/upload` in `main.py`, actual bytes written accounting, backslash traversal checks, and `.git` hooks/config sanitization, verified via `tests/test_upload.py` (13 tests). Added workspace lifetime proposal to `ARCHITECTURE.md` section 7.1.
- 2026-10-08: T20 completed. Implemented GitHub repository creation and push pipeline in `github_push.py` with token verification, identity lookup, pre-push secret audit gate, workspace-scoped safe.directory, forbidden file checks (.env, saksham.db, private keys), no force-push, zero repo deletions, and token sanitization. Tested in `tests/test_github_push.py` (24 mock/unit tests). Full pytest suite passes (168 passed, 0 skipped).
- 2026-10-08: T21 completed. Implemented Render Deployer module in `deployer.py` (`validate_service_name`, `validate_render_api_key`, `create_render_service`, `set_render_env_vars`, `trigger_render_deploy`, `poll_deploy_status`, `deploy_project_to_render`) with full lifecycle handling, pre-deploy secret gate, 5xx retry backoff, fail-fast 4xx errors, and typed `RenderDeployResult`. Tested in `tests/test_deployer.py` (17 mock/unit tests). Full pytest suite passes (186 passed, 0 skipped).
- 2026-10-08: T22 completed. Implemented Deployment Verification & Bounded Self-Fix Loop in `deployer.py` (`verify_deployment`, `diagnose_deployment_failure`, `run_self_fix_loop`, `VerificationResult`, `SelfFixAttempt`, `SelfFixResult`) with max attempts bounding (<=3), early exit on success/repeated failure, pre-push secret audit gate, T17 patch safety validation, T20 git push, T21 Render redeploy, and zero local code execution. Tested in `tests/test_verify_selffix.py` (17 mock/unit tests). Full pytest suite passes (203 passed, 0 skipped).
- 2026-10-08: T23 completed. Implemented Server-Sent Events (SSE) progress streaming in `main.py` and `schemas.py` (`GET /events/{run_id}`, `StageEnum`, `ProgressEvent`, `publish_progress_event`) with bounded event history, per-subscriber broadcast queues, client disconnect handling, secret redaction, and terminal stream closure. Tested in `tests/test_sse.py` (7 unit and integration tests). Full pytest suite passes (210 passed, 0 skipped).
- 2026-10-08: T24 completed. Implemented React + Vite application shell and theme in `frontend/` (`index.css`, `App.jsx`, `components/Sidebar.jsx`, `components/Header.jsx`, `components/StepBar.jsx`, `components/Card.jsx`, `components/Button.jsx`, `components/Badge.jsx`) adhering strictly to DESIGN.md tokens and layout rules. Verified via Vite build and full pytest regression suite (210 passed, 0 skipped).
- 2026-10-08: T25 completed. Implemented Upload screen in `frontend/src/components/UploadScreen.jsx` with drag-and-drop ZIP upload, file validation (25MB limit), target repository/visibility form controls, multipart `POST /analyze` integration, error banners, loading indicators, and preserved `run_id` state in `App.jsx`. Verified via Vite build and full pytest regression suite (210 passed, 0 skipped).
- 2026-10-08: T26 completed. Implemented Audit screen in `frontend/src/components/AuditScreen.jsx` consuming real `AnalysisResult` data with 56px Deploy Readiness Score visualization, deduction reasons list, categorized findings with severity filtering (All, High, Medium, Low), clean/empty state handling, and suggested fix review CTA. Verified via Vite build and full pytest regression suite (210 passed, 0 skipped).
- 2026-10-08: T27 completed. Implemented Live screen in `frontend/src/components/LiveScreen.jsx` connecting to `GET /events/{run_id}` via native browser EventSource with 5-stage deployment checklist, autoscrolling monospace streaming log console, bounded reconnect handling, terminal success/error handling, and live service/repo URL links. Verified via Vite build and full pytest regression suite (210 passed, 0 skipped).
- 2026-10-08: T28 completed. Implemented History, Connections, and Settings screens (`HistoryScreen.jsx`, `ConnectionsScreen.jsx`, `SettingsScreen.jsx`) with backend endpoints `GET /history`, `GET /connections`, `GET /settings` in `main.py`, SQLite persistence querying, integration status without credential leakage, operational parameter review, and full sidebar navigation. Verified via Vite build and backend test suite (214 passed, 0 skipped).
- 2026-10-12: T35 completed. Recorded NC-6 REOPENED in PRD.md & MEMORY.md. Added T35 (UI only) and T36 (Auth backend, BLOCKED). Built dark-themed login screen in React (`frontend/src/components/LoginScreen.jsx`, `App.jsx`, `Sidebar.jsx`, `index.css`) matching two-column design and tokens (#0E1418, #121A20, #25313A, #18232B, #E8EEF2, #9DB0BC, #33424D, #4FC4BB, badges, Plus Jakarta Sans, min-height 44px, 2px focus ring, contrast >= 4.5:1). Right preview panel responsive hiding (<860px). Interactive actions display non-connected message without sending or storing credentials. Existing screens unstyled. Verified via Vite build (`npm run build` in 9.27s) and pytest regression suite (226 passed).

## Things the coding agent must remember
- Follow RULES.md. Ask before major architectural changes; do not touch unrelated files.
- Work on one task at a time in TASKS.md order.
- No fake functionality; no "done" without a test.
- Never log or send secrets to the LLM; push is blocked while any secret remains.
- Never delete repos or force-push.
- Update this file and TASKS.md status after every task.
