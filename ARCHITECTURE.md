# ARCHITECTURE.md: Saksham

> Consistent with PRD.md. "Decided" = stated in conversation. "Proposed" = not stated, needs confirmation. NC-n refers to the list in PRD.md section 17.

## 1. Overall system architecture
A **pipeline** of small Python modules orchestrated by a FastAPI backend. A React frontend calls the backend. An LLM (Google Gemini `gemini-2.5-flash`) acts as a tool-calling agent for fix generation and failure diagnosis only; detection, scanning, Git and deploy actions are plain code.

```
React UI -> POST /analyze -> scanner -> audit (secrets + config) -> fixer (LLM) -> score + patches
React UI (user approves) -> POST /approve -> apply patches -> github_push -> deployer (Render) -> verify (+ self-fix loop)
Progress to UI via SSE
```
Product form: Standalone Web Application (decided).

## 2. Frontend architecture
- Framework: React with Vite and vanilla CSS (decided).
- Styling: DESIGN.md tokens directly in CSS variables (teal/white color system).
- Layout: Left sidebar (New deploy, History, Connections, Settings), main area with a 4-step progress bar (Upload, Audit, Fix, Deploy).
- Live logs consume SSE stream (`/events/{run_id}`).
- Language: English (decided).

## 3. Backend architecture
- Python 3.11 + FastAPI + Uvicorn (decided).
- Pydantic models for all inputs and LLM outputs (decided).
- Synchronous pipeline functions first; long-running operations stream progress through SSE.
- SQLite database for persistent deploy history.
- No Celery/Redis in MVP (decided).

## 4. Database architecture
SQLite relational store (`saksham.db`) for run and deploy history (decided).

| Entity | Fields | Relationships |
|---|---|---|
| User | id, email, password_hash, github_id, github_login, created_at | owns user account and sessions |
| Analysis | id, project_name, stack, score, created_at | has many Issues, Patches |
| Issue | id, analysis_id, severity (High/Medium/Low), title, file, line, explanation | belongs to Analysis |
| Patch | id, analysis_id, issue_id, file, old, new, reason, status (suggested/approved/applied/rejected) | belongs to Issue |
| Deployment | id, analysis_id, repo_url, live_url, platform, health_status, final_score, logs, created_at | belongs to Analysis |

Tokens and secret values are never stored in the database. Password hashes are computed with salted bcrypt.

## 5. Authentication architecture
- User accounts: Local email/password registration with bcrypt salted password hashing, plus GitHub OAuth login.
- Session handling: Cryptographically signed time-limited tokens via `itsdangerous` URLSafeTimedSerializer, delivered in HTTP-only, SameSite=Lax session cookies or Bearer Authorization headers.
- GitHub repo creation: Personal Access Token (scopes `repo`, `workflow`) for repository provisioning; new repos only, never deletes or force-pushes.
- Deploy platform: Render API token (`RENDER_API_KEY`).
- LLM API: Google Gemini API key (`GEMINI_API_KEY`).

## 6. API structure
| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/register` | POST | Register with email and password; returns safe user object and issues session cookie |
| `/auth/login` | POST | Authenticate with email and password; returns safe user object and issues session cookie |
| `/auth/logout` | POST | Clear session cookie and terminate active session |
| `/auth/me` | GET | Retrieve authenticated profile for current session |
| `/auth/github` | GET | Initiate GitHub OAuth authorization flow (redirect or JSON URL) |
| `/auth/github/callback` | GET | GitHub OAuth callback; exchange code, upsert user, set session cookie |
| `/analyze` | POST | Accepts ZIP upload (max 25MB); runs scan, audit, fix suggestions; returns score, issues, patches |
| `/approve` | POST | Accepts approved patch IDs and repo options; applies patches, pushes to GitHub, deploys to Render, verifies |
| `/events/{run_id}` | GET | SSE stream of progress logs |
| `/history` | GET | List past analysis and deployment runs from SQLite |
| `/health` | GET | Health check for Saksham itself |

## 7. Data flow
1. ZIP upload extracted into a temporary working directory (path-traversal verified).
2. `scanner` returns stack JSON.
3. `audit` runs `gitleaks` on files and git history (if `.git` exists), then custom config checks, and computes the readiness score (100 - High*30 - Med*15 - Low*5).
4. `fixer` sends issue + relevant file content to Gemini (`gemini-2.5-flash`); response validated as `Patch` with Pydantic.
5. Patches shown as diffs in the React UI. Nothing is written until user approval.
6. Approved patches applied by code. Secret re-scan must pass before push.
7. `github_push` creates a new GitHub repo, commits, and pushes.
8. `deployer` creates a web service on Render via Render API, sets environment variables/secrets via API, and waits for deploy completion.
9. Health check on `/health` (or `/`) of the deployed app. On failure: logs sent to Gemini, patch generated and applied, redeploy (max 2-3 attempts).
10. Return live URL, repo link, and summary report.

### 7.1 Workspace Lifetime & In-Memory Patch State (Approved)
- **Lifecycle between `/analyze` and `/approve`**:
  - When a project ZIP is uploaded to `/analyze`, a cryptographically secure `run_id` is generated using `secrets.token_urlsafe(16)`.
  - The project is extracted into an isolated workspace directory at `tmp/runs/{run_id}/`.
  - Leftover directories in `tmp/runs` from prior terminated runs are cleaned up on application startup (guaranteeing a clean state).
  - Proposed code patches and temporary analysis states are kept in memory in an active run registry (`RUNS[run_id]`), keyed by `run_id`.
  - **Security & Privacy constraint**: Proposed and applied patch contents must NEVER be written to the database or logged in plain text.
  - **Single-Worker Assumption**: Saksham operates as a single-worker process for MVP; in-memory state is maintained within the active process memory.
  - A background TTL cleaner purges expired workspaces based on `workspace_ttl_seconds` (default: 1800 seconds / 30 minutes in `config.py`) if `/approve` is not called.
  - Upon user approval (`POST /approve`), approved patches from memory are applied directly to the `run_id` workspace, pushed to GitHub, deployed to Render, verified, and the workspace directory is deleted immediately upon run conclusion.

## 8. Main modules and responsibilities
| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, API routes, and static file serving / SSE |
| `scanner.py` | Rule-based detection of language, framework, entry point, port |
| `audit.py` | Secret scan (`gitleaks` on files + history), config checks, score calculation |
| `fixer.py` | Calls Gemini API via `llm.py`, returns validated `Patch` objects, applies approved patches |
| `llm.py` | Google Gemini SDK client with Pydantic structured output validation and error handling |
| `github_push.py` | Create new GitHub repository, commit, and push |
| `deployer.py` | Render API deployment, secret configuration, health check verification, self-fix loop |
| `db.py` | SQLite database models and CRUD operations for history |
| `upload.py` | Safe ZIP extraction with path-traversal validation and cleanup |
| `schemas.py` | Pydantic models (Issue, Patch, AnalysisResult, DeployResult, etc.) |
| `config.py` | Environment configuration and credential loading |
| `templates/` | Templates for README, Dockerfile, `.gitignore`, GitHub Actions |
| `frontend/` | React + Vite UI application |

## 9. Folder / file structure
```
saksham/
├── main.py
├── config.py
├── schemas.py
├── db.py
├── upload.py
├── scanner.py
├── audit.py
├── fixer.py
├── llm.py
├── github_push.py
├── deployer.py
├── templates/
├── tests/
│   ├── fixtures/
│   │   ├── vulnerable-demo-app/
│   │   └── clean-app/
│   └── test_*.py
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── index.css
        └── components/
```

## 10. Third-party services and tools
- LLM API: Google Gemini API (`gemini-2.5-flash` via `google-genai`).
- GitHub REST API: `PyGithub` + `GitPython`.
- Secrets: `gitleaks` CLI.
- Deploy: Render API (Render web service creation and deploy). MOCK deployer allowed strictly in test files.
- Testing: `pytest`, `httpx`.

## 11. Security considerations
- Secret gate: no push while unresolved secrets exist; re-scan after patches.
- Scan git history if `.git` is present.
- Token scope minimal; no delete or force-push code paths.
- Never log or send tokens/keys to the LLM; redact matched secrets in logs and UI.
- Validate LLM output with Pydantic; apply patches only to files inside the project directory.
- Safe zip extraction (no path traversal, 25MB max size limit).
- Set app secrets through Render API, not in the git repository.

## 12. Deployment architecture
- Target apps (MVP): Student FastAPI applications on Render.
- Saksham host: Local or hosted as a web service.

## 13. Technology stack
| Layer | Choice | Status |
|---|---|---|
| Language / Backend | Python 3.11, FastAPI, Uvicorn | Decided |
| Validation | Pydantic v2 | Decided |
| Database | SQLite (`saksham.db`) | Decided |
| LLM | Google Gemini API (`gemini-2.5-flash`) | Decided |
| Secrets Scan | `gitleaks` CLI | Decided |
| Git / GitHub | `GitPython`, `PyGithub` | Decided |
| Deploy Platform | Render API | Decided |
| Live Logs | Server-Sent Events (SSE) | Decided |
| Frontend | React + Vite + Vanilla CSS (DESIGN.md tokens) | Decided |
| Testing | `pytest`, `httpx` | Decided |
