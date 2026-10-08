# TASKS.md: Saksham

> Do tasks in order, one at a time. Status values: TODO, IN PROGRESS, DONE, BLOCKED. A task is DONE only after its testing requirements pass (RULES.md). NC-n references are in PRD.md section 17.
> Every task has: Objective, Files, Depends on, Implementation, Acceptance, Testing, Status.

## Phase 0: Decisions (must be settled first)
**T00 Resolve blocking clarifications**
- Objective: get the user's answers for NC-1, NC-2, NC-3, NC-4, NC-5, NC-6, NC-10, NC-11, NC-13 and record them in MEMORY.md.
- Files: MEMORY.md, PRD.md, ARCHITECTURE.md, DESIGN.md, TASKS.md.
- Depends on: none.
- Implementation: user confirmed all decisions: standalone React+Vite web app, Google Gemini API, Render API, SQLite persistence, score formula (High -30, Med -15, Low -5), English UI, ZIP upload (25MB max) with path-traversal check and git history scan, Python 3.11 with pinned dependencies & gitleaks.
- Acceptance: each listed NC is answered and documented.
- Testing: documentation verification.
- Status: DONE

## Phase 1: Project setup
**T01 Repository and folder skeleton**
- Objective: create the folder structure from ARCHITECTURE.md section 9.
- Files: backend modules, `frontend/`, `tests/`, `.gitignore`, `README.md`.
- Depends on: T00.
- Implementation: backend modules with docstrings, React frontend initialized, `.gitignore` covering `.env`, `venv`, `node_modules`, `saksham.db`.
- Acceptance: structure matches the document; app imports without error.
- Testing: import smoke test (`tests/test_smoke.py` - 11 module imports passed).
- Status: DONE

**T02 Dependencies and configuration**
- Objective: pinned dependencies and environment configuration.
- Files: `requirements.txt`, `.env.example`, `config.py`, `tests/test_config.py`.
- Depends on: T01.
- Implementation: Pinned dependencies in `requirements.txt`, created `.env.example` with variable names only, implemented typed `Settings` in `config.py` with `ConfigurationError` for missing variables.
- Acceptance: app starts; missing env vars give a clear error.
- Testing: unit tests in `tests/test_config.py` (6 tests passed).
- Status: DONE

**T03 Test fixture projects**
- Objective: reproducible projects for testing and the demo.
- Files: `tests/fixtures/vulnerable-demo-app/`, `tests/fixtures/clean-app/`, `tests/test_fixtures.py`.
- Depends on: T01.
- Implementation: FastAPI demo with hardcoded fake API key on line 12 of `config.py`, `.env` not ignored, hardcoded port 8000, plus a clean app. Uses fake key format only and no `.env` files.
- Acceptance: both fixtures are verified; planted issues are documented in fixture READMEs.
- Testing: unit tests in `tests/test_fixtures.py` (4 tests passed).
- Status: DONE

## Phase 2: Database
**T04 Persistence for deploy history**
- Objective: store runs for the History screen using SQLite.
- Files: `db.py`, `tests/test_db.py`.
- Depends on: T00, T02.
- Implementation: SQLite store (`saksham.db`) with `analyses`, `issues`, `patches`, `deployments` tables and parameterized CRUD functions. No tokens or secrets stored in tables.
- Acceptance: runs and deployments can be saved and listed with full relationship integrity.
- Testing: CRUD unit tests in `tests/test_db.py` (4 tests passed).
- Status: DONE

## Phase 3: Authentication and credentials
**T05 GitHub token handling**
- Objective: validate a Personal Access Token and its scopes.
- Files: `github_push.py`, `tests/test_github_token.py`.
- Depends on: T02.
- Implementation: Check scopes `repo` and `workflow` via PyGithub; reject fine-grained tokens with a clear error; sanitize and never log the token.
- Acceptance: valid token passes; missing scope, invalid credentials, or fine-grained token gives a plain message without leaking credentials.
- Testing: unit tests in `tests/test_github_token.py` (6 tests).
- Status: DONE (real-token test pending: needs GITHUB_TOKEN in .env)

**T06 Saksham user login**
- Objective: authentication for Saksham users.
- Files: N/A.
- Depends on: T00.
- Implementation: Decided in T00: single-user application without login for MVP.
- Acceptance: No login required.
- Testing: N/A.
- Status: Not required (NC-6: single-user, no login)

## Phase 4: Core backend
**T07 Schemas**
- Objective: Pydantic models.
- Files: `schemas.py`, `tests/test_schemas.py`.
- Depends on: T02.
- Implementation: `Issue` (severity enum High/Medium/Low, title, file, line, explanation), `Patch` (file, old, new, reason, status), `AnalysisResult` (stack, score 0-100, issues, patches), `DeployResult` (analysis_id, repo_url, live_url, platform, health_status, final_score 0-100, logs). Documented field mapping to `db.py`.
- Acceptance: models validate good data and reject bad data (invalid severity, negative score, score > 100, missing required fields).
- Testing: unit tests in `tests/test_schemas.py` (8 tests passed).
- Status: DONE

**T08 Safe upload extraction**
- Objective: accept an upload into a temp directory safely.
- Files: `upload.py`, `main.py`, `tests/test_upload.py`.
- Depends on: T07, NC-10.
- Implementation: ZIP extraction context manager with path traversal checks (`..`, drive letters, absolute paths, symlinks), size limit (25MB compressed, 100MB uncompressed, 10k files max), automatic temporary directory cleanup, `.git` presence detection, and `POST /upload` FastAPI route.
- Acceptance: valid zip extracts; malicious path/symlink/zip bomb rejected; cleanup works on normal and error flows.
- Testing: unit tests in `tests/test_upload.py` (13 tests passed).
- Status: DONE

**T09 Scanner**
- Objective: detect stack by rules.
- Files: `scanner.py`, `tests/test_scanner.py`.
- Depends on: T07, T08.
- Implementation: `requirements.txt` / AST import inspection detects Python & FastAPI, entry point, port (hardcoded or env); `package.json` detects Node (flagged unsupported in MVP with a clear message); static parsing via AST and regex text search without executing untrusted code; returns `ScanResult` Pydantic model with clearly marked T15 LLM extension point.
- Acceptance: both fixtures return correct JSON; Node project and empty/unknown projects return clear reasons; syntax errors handled gracefully.
- Testing: unit tests in `tests/test_scanner.py` (9 tests passed).
- Status: DONE

**T10 Secret scan of files**
- Objective: wrap the chosen secret scanner.
- Files: `audit.py`, `templates/gitleaks.toml`, `tests/test_audit.py`.
- Depends on: T03, T07.
- Implementation: subprocess call to Gitleaks with argument list (shell=False), timeout, `--no-git`, `--redact`, `--ignore-gitleaks-allow`, Saksham's own config via `--config`, dedicated dummy `--gitleaks-ignore-path`, and report written outside target project; parses report into High severity Issue objects without secret values.
- Acceptance: planted key found in `config.py` line 12; clean app has zero; `.gitleaks.toml` allowlist and inline comments bypassed; missing gitleaks gives clear error.
- Testing: unit tests in `tests/test_audit.py` (4 tests passed).
- Status: DONE

**T11 Secret scan of git history**
- Objective: catch keys that were removed from files but remain in history.
- Files: `audit.py`, `tests/test_audit.py`.
- Depends on: T10, NC-10.
- Implementation: `scan_git_history()` runs Gitleaks in git mode on `.git` history with `--log-opts="--all"`, safe.directory dubious ownership protection, and reports short commit hashes in issue explanations; de-duplicates against active file secrets; returns "history not available" when `.git` is absent.
- Acceptance: a key in an old commit is detected; clean history gives zero; no `.git` gives "history not available".
- Testing: unit tests with real temporary git repositories (3 tests passed).
- Status: DONE

**T12 Config checks**
- Objective: custom configuration and hygiene checks.
- Files: `audit.py`, `tests/test_audit.py`.
- Depends on: T07.
- Implementation: static checks via AST and text inspection without executing untrusted code: `check_env_in_gitignore`, `check_hardcoded_localhost`, `check_debug_enabled`, `check_hardcoded_port`, `check_junk_files`. Central severity table `DEFAULT_CHECK_SEVERITIES` defined at module top.
- Acceptance: each check fires on the vulnerable demo fixture and passes on the clean fixture.
- Testing: unit tests on fixtures and temporary trees (6 tests passed).
- Status: DONE

**T13 Readiness score**
- Objective: compute Deploy Readiness Score.
- Files: `audit.py`, `config.py`, `tests/test_audit.py`.
- Depends on: T10, T12.
- Implementation: Base 100 minus (High * 30, Medium * 15, Low * 5), bounded between 0 and 100; weights defined centrally in `config.py` (`ISSUE_SEVERITY_DEDUCTIONS`); returns `(score, reasons)` where reasons explain each deduction line-by-line; orchestrator `audit_project()` returns `(issues, score, reasons, history_status)`.
- Acceptance: deterministic score with reasons list; vulnerable fixture gives exactly 40 (30+15+15), clean fixture gives 100, clamped at 0 for many issues.
- Testing: unit tests in `tests/test_audit.py` (4 score tests passed).
- Status: DONE

**T14 Analyze endpoint**
- Objective: `POST /analyze` runs scan and audit.
- Files: `main.py`, `upload.py`, `schemas.py`, `tests/test_analyze.py`.
- Depends on: T09, T10, T12, T13.
- Implementation: `POST /analyze` safely streams ZIP upload, creates isolated workspace in `tmp/runs/{run_id}` with startup and TTL cleanup, runs rule-based `scan_project`, runs `audit_project` (secrets, git history, config checks), records active run in memory (`RUNS`), redacts secrets and persists in SQLite (`saksham.db`), and returns validated `AnalysisResult` (read-only regarding GitHub and Render).
- Acceptance: returns correct JSON for fixtures (score 40 for vulnerable fixture with 3 issues and deduction reasons, score 100 for clean fixture); enforces 25MB streaming limit and zip security.
- Testing: unit and integration tests in `tests/test_analyze.py` (8 tests passed).
- Status: DONE

**T15 LLM client**
- Objective: structured-output LLM wrapper for Google Gemini.
- Files: `llm.py`, `tests/test_llm.py`.
- Depends on: T02, T07.
- Implementation: `GeminiLLMClient` in `llm.py` using `google-genai` SDK (`gemini-2.5-flash` or configured `GEMINI_MODEL`), explicit HTTP timeouts, Pydantic structured output validation with automatic repair retry, error translation, and strict secret redaction.
- Acceptance: invalid output is rejected with clear `LLMResponseError`; valid output parsed into Pydantic models; timeouts produce `LLMTimeoutError`; zero secrets logged.
- Testing: unit tests with mocks in `tests/test_llm.py` (9 tests passed without calling real Gemini API).
- Status: DONE

**T16 Fixer**
- Objective: generate Patch objects.
- Files: `fixer.py`, `tests/test_fixer.py`.
- Depends on: T14, T15.
- Implementation: `propose_patches_for_issues()` in `fixer.py` using deterministic templates for standard config issues and `GeminiLLMClient` with sanitized context (zero raw secrets sent, only relevant file lines sent); strict safety validation (no path traversal, no absolute paths, no shell command injections, never inventing fake credentials); completely read-only in memory (no files on disk modified).
- Acceptance: vulnerable demo fixture yields 3 valid patches (`config.py`, `.gitignore`, `main.py`); invalid/malformed LLM responses handled safely; safety boundaries enforced.
- Testing: unit tests in `tests/test_fixer.py` (11 tests passed with mocks, no real Gemini API calls).
- Status: DONE

**T17 Patch apply and diff**
- Objective: show and apply patches safely.
- Files: `fixer.py`, `tests/test_patch_apply.py`.
- Depends on: T16.
- Implementation: `apply_patch()`, `apply_patches()`, `generate_unified_diff()`, `generate_patch_diff()` in `fixer.py`. Enforces strict approval requirement (`patch.status == PatchStatusEnum.APPROVED`), workspace path boundary containment (rejects traversal, absolute, drive paths, symlinks), exact old-content matching, in-memory simulation for all-or-nothing batch application, atomic temporary file replacement, and secret redaction on diffs. No subprocess/shell execution.
- Acceptance: diff matches change and masks secrets; unapproved/suggested patches rejected; exact match failures leave workspace 100% untouched; batch failure rolls back all changes.
- Testing: unit tests in `tests/test_patch_apply.py` (12 tests passed).
- Status: DONE

**T18 Template generation**
- Objective: README, Dockerfile, `.gitignore`, GitHub Actions workflow.
- Files: `templates/`, `fixer.py`, `tests/test_templates.py`.
- Depends on: T09, T15.
- Implementation: Deterministic starter templates (`Dockerfile.template`, `gitignore.template`, `ci.yml.template`, `README.md.template`, `env_example.template`) in `templates/` and `render_template()` / `propose_missing_file_patches()` in `fixer.py`. Generates proposed `Patch` objects in memory without modifying disk or calling LLM. Fully compatible with T17 safety boundaries and contains zero secrets.
- Acceptance: deterministic output with zero secrets; missing files correctly proposed as patches with status SUGGESTED; no shell commands.
- Testing: unit tests in `tests/test_templates.py` (7 tests passed).
- Status: DONE

**T19 Approve endpoint (apply stage)**
- Objective: `POST /approve` applies approved patches and re-scans.
- Files: `main.py`, `schemas.py`, `tests/test_approve.py`.
- Depends on: T17, T18.
- Implementation: `POST /approve` in `main.py` accepting `ApproveRequest` (`run_id`, `approved_patch_ids`, `repo_name`, `visibility`), applies approved patches to isolated workspace via `apply_patches()`, executes mandatory secret re-scan gate via `audit_project()`, blocks if any unresolved High-severity secret leaks remain, and returns typed `ApproveResponse`.
- Acceptance: nothing proceeds with an unresolved secret leak; approved patches successfully apply and raise readiness score to 100 on demo fixture; workspace isolation maintained.
- Testing: unit and integration tests in `tests/test_approve.py` (4 tests passed).
- Status: DONE

**T20 GitHub push**
- Objective: create new repo, commit, push.
- Files: `github_push.py`, `tests/test_github_push.py`.
- Depends on: T05, T19.
- Implementation: `github_push.py` with `validate_repo_name()` (alphanumeric/dash/underscore/dot 1-100 characters), `validate_github_token()` (verifying `repo` and `workflow` scopes), `create_remote_repo()` via PyGithub (NEW repositories only, never deletes, rejects existing conflicts, retry cap for transient 5xx errors), `pre_push_secret_check()` final audit gate blocking on any High-severity secrets, and `commit_and_push_workspace()` via GitPython (workspace-scoped safe.directory, forbidden .env/saksham.db/keys staging checks, .gitignore compliance, no force-push, immediate remote URL token sanitization).
- Acceptance: new repo created; push succeeds only when clean and approved; secrets absent; zero global git config modification.
- Testing: unit and mock tests in `tests/test_github_push.py` (24 tests passed).
- Status: DONE

**T21 Deployer**
- Objective: deploy to Render via Render API.
- Files: `deployer.py`, `tests/test_deployer.py`.
- Depends on: T20.
- Implementation: `deployer.py` with `validate_service_name()`, `validate_render_api_key()`, `create_render_service()` with transient 5xx retry and fail-fast 4xx handling, `set_render_env_vars()`, `trigger_render_deploy()`, `poll_deploy_status()` tracking deployment lifecycle states (created, build_in_progress, update_in_progress, live, build_failed, timeout), and `deploy_project_to_render()` returning typed `RenderDeployResult` with pre-deploy secret gate enforcement and zero API key leakage.
- Acceptance: creates web service on Render from GitHub repo created in T20; sets env vars/secrets via Render API; polls for status; handles all terminal failure/timeout states safely.
- Testing: unit and mock tests in `tests/test_deployer.py` (17 tests passed).
- Status: DONE

**T22 Verify and self-fix loop**
- Objective: health check and bounded retry.
- Files: `deployer.py`, `fixer.py`, `tests/test_verify_selffix.py`.
- Depends on: T21, T16.
- Implementation: `deployer.py` with `verify_deployment()` (HTTP health verification on `/health` and `/` detecting 2xx, 4xx, 5xx, timeouts, network failures, and latency), `diagnose_deployment_failure()` (proposing structured Patch objects for localhost binds, wrong ports, missing health routes, or LLM-assisted diagnosis), and `run_self_fix_loop()` (strictly bounded to <= 3 attempts, immediate exit on success, early exit on repeated failure, re-scan gate via `pre_push_secret_check()`, push via `commit_and_push_workspace()`, redeploy via `trigger_render_deploy()`, and safe metadata attempt history in `SelfFixResult`).
- Acceptance: verification detects failure modes safely; deliberate wrong-port / localhost bind failure is diagnosed and self-fixed automatically; loop respects attempt cap and stops on repeated failure; zero credentials or headers leaked.
- Testing: unit and mock tests in `tests/test_verify_selffix.py` (17 tests passed).
- Status: DONE

**T23 SSE progress stream**
- Objective: live logs and real-time progress events.
- Files: `main.py`, `schemas.py`, `tests/test_sse.py`.
- Depends on: T19.
- Implementation: `main.py` with `GET /events/{run_id}` streaming `text/event-stream` formatted events (`data: <JSON>\n\n`), `publish_progress_event()` dispatching sanitized events with `redact_text()`, bounded in-memory event history per run (max 100), per-subscriber `asyncio.Queue` broadcast, disconnect resource cleanup, safe 404 handling, and terminal event stream completion.
- Acceptance: client receives ordered real-time events across all pipeline stages (`upload`, `scan`, `audit`, `fix`, `approve`, `github`, `deploy`, `verify`, `self_fix`, `complete`, `error`) with zero secrets or token leaks.
- Testing: unit tests in `tests/test_sse.py` (7 tests passed).
- Status: DONE

## Phase 5: Core frontend
**T24 UI shell**
- Objective: React + Vite layout, CSS tokens, sidebar, step bar.
- Files: `frontend/src/index.css`, `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`, `frontend/src/components/Header.jsx`, `frontend/src/components/StepBar.jsx`, `frontend/src/components/Card.jsx`, `frontend/src/components/Button.jsx`, `frontend/src/components/Badge.jsx`.
- Depends on: T00, DESIGN.md.
- Implementation: Full DESIGN.md color, typography, and geometry tokens in CSS variables; 224px Sidebar with Saksham branding, active state, and SVG navigation icons (New deploy, History, Connections, Settings); 4-step StepBar pill navigation (Upload, Audit, Fix, Deploy); reusable Card, Button, Badge primitives; responsive layout and mission overview grid.
- Acceptance: matches the design canvas visually; production bundle built cleanly with Vite without errors.
- Testing: frontend production build (`npm run build`) succeeded in 11.66s; backend regression test suite passed (210 passed).
- Status: DONE

**T25 Upload screen**
- Objective: upload, detected chips, repo options.
- Files: `frontend/src/components/UploadScreen.jsx`, `frontend/src/App.jsx`, `frontend/src/index.css`, `frontend/vite.config.js`.
- Depends on: T24, T14.
- Implementation: per DESIGN.md section 18 in English; drag-and-drop ZIP upload zone with 25MB boundary validation, file summary card with formatted size, repository name input, visibility dropdown (private default, public), target platform (Render), and multipart `POST /analyze` integration with loading state, safe error banners, and preserved `run_id` and analysis results.
- Acceptance: real upload calls `/analyze` and preserves analysis response for Step 2; production bundle built cleanly without errors.
- Testing: frontend production build (`npm run build`) succeeded in 9.06s; backend regression suite passed (210 passed).
- Status: DONE

**T26 Audit screen**
- Objective: score, issues, diff, approval buttons.
- Files: `frontend/src/components/AuditScreen.jsx`, `frontend/src/App.jsx`, `frontend/src/index.css`.
- Depends on: T25, T17.
- Implementation: `AuditScreen.jsx` rendering real `AnalysisResult` data; 56px Deploy Readiness Score visualization with progress bar, status badges, and itemized deduction reasons; categorized security & config findings with severity filters (All, High, Medium, Low); clean state handling for zero-risk projects; empty state handling; and suggested patch summary with primary navigation to review fixes.
- Acceptance: displays real analysis results with DESIGN.md color tokens, severity badges, and score breakdown; production bundle built cleanly without errors.
- Testing: frontend production build (`npm run build`) succeeded in 9.03s; backend regression suite passed (210 passed).
- Status: DONE

**T27 Live screen**
- Objective: results, log, links.
- Files: `frontend/src/components/LiveScreen.jsx`, `frontend/src/App.jsx`, `frontend/src/index.css`.
- Depends on: T26, T23.
- Implementation: `LiveScreen.jsx` connecting to `GET /events/{run_id}` via native browser EventSource; 5-step live pipeline checklist (Pre-Push Audit, Patch Application, GitHub Push, Render Deploy, Verification & Self-Fix) with real-time status badges and spinners; autoscrolling monospace streaming log console with stage coloring; live URL and GitHub repository link cards; bounded reconnect handling (max 3 retries); terminal success and error states; and safe cleanup on component unmount.
- Acceptance: receives real-time SSE stream, displays live deployment checklist and logs, closes connection on terminal complete/error, and exposes zero secrets; production bundle built cleanly without errors.
- Testing: frontend production build (`npm run build`) succeeded in 9.05s; backend regression suite passed (210 passed).
- Status: DONE

**T28 History, Connections, Settings screens**
- Objective: remaining sidebar pages.
- Files: `frontend/src/components/HistoryScreen.jsx`, `frontend/src/components/ConnectionsScreen.jsx`, `frontend/src/components/SettingsScreen.jsx`, `frontend/src/App.jsx`, `main.py`, `tests/test_history_settings.py`.
- Depends on: T04, T24.
- Implementation: `HistoryScreen.jsx` consuming SQLite records via `GET /history` with tab filtering (All, Deployments, Analyses) and clean empty state; `ConnectionsScreen.jsx` consuming safe metadata via `GET /connections` showing Gemini, GitHub, and Render integration status without exposing keys; `SettingsScreen.jsx` consuming `GET /settings` displaying operational limits, TTL, and scoring deduction rules; integrated into functional sidebar navigation in `App.jsx`.
- Acceptance: all 3 sidebar screens render real data, navigate cleanly, and expose zero secrets; production bundle built cleanly without errors.
- Testing: frontend production build (`npm run build`) succeeded in 9.32s; backend regression suite passed (214 passed).
- Status: DONE

## Phase 6: Integration and testing
**T29 End-to-end happy path**
- Objective: upload to live URL on the demo fixture.
- Files: `main.py`, `frontend/src/App.jsx`, `frontend/src/components/ConnectionsScreen.jsx`, `db.py`, `deployer.py`, `tests/test_e2e_happy_path.py`.
- Depends on: T22, T27, T28.
- Implementation: Connected `POST /approve` with background execution of `run_deployment_pipeline_sync` (orchestrating GitHub repository creation/push -> Render deployment -> live health verification/self-fix -> SQLite history persistence -> streaming SSE progress events); connected frontend Step 3 to trigger `/approve` and transition to Step 4; ensured Gemini model name is dynamically sourced from `/connections` without hardcoding; created comprehensive E2E and regression integration test suite in `tests/test_e2e_happy_path.py` covering happy path, secret gate blocking, failure boundaries (malformed ZIP, size limits, unknown run_id, GitHub errors, verification failures), and zero-secret leakage.
- Acceptance: Full end-to-end pipeline passes deterministically with mocked external boundaries, score rises 40 to 100 after approved patches, live health verification succeeds, deployment persists safely to database, and all 223 backend tests pass with clean frontend production build.
- Testing: `tests/test_e2e_happy_path.py` (9 passed), full backend pytest suite (223 passed), frontend production build (`npm run build`) succeeded in 9.38s.
- Status: DONE

**T30 Final Integration Hardening and Demo Readiness**
- Objective: Final engineering hardening pass and demo-readiness validation across the entire Saksham application.
- Files: whole repository (`main.py`, `db.py`, `config.py`, `schemas.py`, `upload.py`, `scanner.py`, `audit.py`, `fixer.py`, `github_push.py`, `deployer.py`, `redact.py`, `frontend/src/*`, `README.md`, `tests/*`).
- Depends on: T29.
- Implementation: Full codebase security audit (zero raw secrets logged, DB/SSE/error redaction verified); pipeline consistency and state transitions verified; human-in-the-loop approval safety confirmed; bounded self-fix loop (max 3 retries) validated; Server-Sent Events memory bounds and disconnect/reconnect resilience confirmed; SQLite persistence verified; API error responses sanitized (no stack traces or internal paths exposed); demo fixtures validated; README.md setup, testing, and operational guide enriched; and zero unnecessary dependencies verified.
- Acceptance: Full test suite passes deterministically (223 passed) and frontend builds cleanly without errors or warnings.
- Testing: `pytest` regression suite (223 passed), frontend production build (`npm run build` succeeded in 9.61s).
- Status: DONE

## Phase 7: Security
**T31 Security review**
- Objective: verify RULES.md section 7.
- Files: whole codebase.
- Depends on: T29.
- Implementation: check logs for secrets, token scopes, zip handling, no delete/force-push paths, no secrets sent to LLM.
- Acceptance: written checklist with all items passed.
- Testing: grep and targeted tests.
- Status: TODO

## Phase 8: UI polish
**T32 States and accessibility**
- Objective: loading, empty, error states; accessibility.
- Files: `ui/`.
- Depends on: T27.
- Implementation: per DESIGN.md sections 12-17.
- Acceptance: each screen has all states; keyboard works; contrast passes.
- Testing: manual keyboard and contrast check.
- Status: TODO

## Phase 9: Deployment and hackathon deliverables
**T33 Deploy Saksham itself**
- Objective: host the app for judges.
- Files: deployment config.
- Depends on: T31, NC-10.
- Implementation: per decision.
- Acceptance: public demo URL works.
- Testing: smoke test from another device.
- Status: BLOCKED (NC-10)

**T34 Demo assets**
- Objective: backup demo video, stat, PPT.
- Files: outside code.
- Depends on: T29.
- Implementation: record the 2-minute run; scan 20-30 public student repos for the leak stat; make the 7-slide PPT (Title+hook; Problem+gap; Solution+uniqueness; Demo screenshots; Architecture; Impact+limits+future; Team+links).
- Acceptance: all three exist; stat is real, not invented.
- Testing: review by team.
- Status: TODO
