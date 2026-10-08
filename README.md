# Saksham

**Deploy with confidence.** Saksham is an AI agent that audits your project before it goes to GitHub, proposes safety and configuration fixes that you approve as a visual diff, pushes to a clean repository, deploys live to Render, and verifies the running URL.

---

## 🚨 Problem

### Students Are Accidentally Leaking API Keys to GitHub

AI coding tools and rapid development help students build applications faster, but security and deployment mistakes are often overlooked.

- Beginners have to manage multiple manual steps during deployment.
- A small configuration mistake can cause a deployment failure.
- Hardcoded API keys and secrets can accidentally be pushed to GitHub.
- An application that works locally may fail in production.
- Beginners often lack the security and DevOps knowledge needed to identify these problems.

> The problem is not just building an application — it is knowing whether the application is safe and ready to deploy.

---

## 🔍 Gap in Existing Solutions

Existing platforms and AI coding tools solve individual parts of the development workflow, but they do not provide a complete safety layer from code audit to verified deployment.

| Solution | What it doesn't provide |
|---|---|
| Vercel | Deploys applications, but does not provide a dedicated pre-push security and configuration audit layer. |
| Render | Deploys applications, but does not prevent every secret or configuration mistake before the GitHub push. |
| Claude Code | Helps build and modify code, but is not specifically designed as a controlled audit → approve → deploy → verify pipeline. |

### The Gap

> Existing tools help developers build or deploy. Saksham focuses on making the transition from code to production safer.

---

## 💡 Solution

### Saksham — The Safety Layer Before Production

Saksham is a safety-focused deployment agent that audits a project before it reaches GitHub or production.

Its core workflow is:

**🛡️ Audit → 🔧 Auto-Fix → 🚀 Deploy → ✅ Verify**

### 1. 🛡️ Audit

Before pushing the project, Saksham scans for:

- Hardcoded API keys and secrets
- Secrets in Git history
- Missing .gitignore
- Unsafe configurations
- Deployment-readiness issues

The project receives a Deploy Readiness Score from 0–100.

### 2. 🔧 Auto-Fix

Saksham proposes fixes instead of silently modifying the project.

Developers can:
- Review proposed changes
- Inspect unified diffs
- Approve selected fixes
- Apply only the approved patches

> Nothing is modified without explicit user approval.

### 3. 🚀 Deploy

After the project passes the security gate, Saksham:

- Creates a new GitHub repository
- Pushes the approved project
- Deploys it to Render
- Shows deployment progress in real time

### 4. ✅ Verify

Saksham does not assume that a successful deployment means the application is healthy.

It performs a live HTTP health check to verify that the deployed application is actually responding.

If deployment fails, Saksham can perform a bounded self-fix loop with a maximum of 3 attempts.

---

## 🔐 Security by Design

Security is at the core of Saksham.

Key protections include:

- Secret scanning before GitHub push
- High-severity secrets block the push
- Human approval for normal fixes
- Secrets are redacted from logs and the database
- Safe ZIP extraction
- Uploaded project code is never executed locally
- Patch paths are validated and contained
- No force-push or repository deletion
- Bounded timeouts and retries for external APIs
- Self-fix attempts are strictly limited

---

## 🔄 How Saksham Works

```text
Project ZIP
    ↓
🛡️ Audit
    ↓
Deploy Readiness Score
    ↓
🔧 Auto-Fix + User Approval
    ↓
Secret Re-Scan
    ↓
🚀 GitHub
    ↓
🚀 Render
    ↓
✅ Live Verification
    ↓
Bounded Self-Fix if required
```

---

## 🚀 Key Features

1. **Pre-Push Safety Audit**: Rule-based project detection and secret scanning (files & git history via `gitleaks`), plus configuration health checks.
2. **Deploy Readiness Score**: Objective 0–100 score indicating launch readiness with itemized deduction reasons.
3. **Structured Auto-Fixing**: LLM-powered diff suggestions with plain-English beginner-friendly explanations.
4. **Human-in-the-Loop Approval**: Review and approve changes as unified diffs before anything is written or pushed.
5. **Automated GitHub & Render Pipeline**: Creates a new GitHub repository, pushes approved code, and deploys directly to Render.
6. **Live Post-Deploy Verification**: Automatic health check monitoring and bounded self-fix retries (max 3 attempts) on deployment errors.
7. **Real-Time Progress Streaming**: Safe Server-Sent Events (SSE) progress bar and terminal log console.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11, FastAPI, Uvicorn, Pydantic v2
- **Frontend**: React, Vite, Vanilla CSS (Design Tokens)
- **AI / LLM**: Google Gemini API (`gemini-2.5-flash`)
- **Security Scanner**: `gitleaks`
- **Git & Deployment**: `GitPython`, `PyGithub`, Render API
- **Persistence**: SQLite (`saksham.db`)

---

## 📦 Prerequisites & Installation

Saksham requires Python 3.11+, Node.js 18+, and the `gitleaks` CLI for secret detection.

### 1. Gitleaks Installation
- **Windows (WinGet)**:
  ```powershell
  winget install --id Gitleaks.Gitleaks -e
  ```
- **Windows (Scoop)**:
  ```powershell
  scoop install gitleaks
  ```
- **macOS / Linux (Homebrew)**:
  ```bash
  brew install gitleaks
  ```

### 2. Environment Configuration
Copy `.env.example` to `.env` and set your credentials:
```bash
cp .env.example .env
```
Key configuration variables:
- `GEMINI_API_KEY`: Google Gemini API key for LLM-assisted patch diagnosis.
- `GEMINI_MODEL`: Model name (defaults to `gemini-2.5-flash`).
- `GITHUB_TOKEN`: GitHub Personal Access Token (requires `repo` and `workflow` scopes).
- `RENDER_API_KEY`: Render API Key for web service deployment.
- `PORT`: Backend server port (defaults to `8000`).

---

## 🚦 Running Locally

### Backend (FastAPI)
```powershell
# Create virtual environment & install dependencies
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Run FastAPI backend server
uvicorn main:app --reload --port 8000
```

### Frontend (React + Vite)
```powershell
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:5173`, with API proxying to `http://localhost:8000`.

---

## 🧪 Running Tests

### Backend Test Suite
Run the full pytest suite:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Frontend Production Build
Validate frontend compilation and asset bundling:
```powershell
cd frontend
npm run build
```

---

## 🔒 Security Model & Guardrails

- **Zero Secret Exposure**: Tokens, API keys, and scanned credentials are systematically redacted (`[REDACTED]`) from logs, database records, SSE streams, and UI views.
- **Mandatory Approval Gate**: No code is modified and no remote repository is created without explicit user approval.
- **Pre-Push Secret Gate**: Unresolved High-severity secrets immediately block GitHub creation and Render deployment.
- **Strict Staging Exclusion**: `.env`, `saksham.db`, `.pem`, and `.key` files are never staged or pushed to git remotes.
- **No Local Code Execution**: Uploaded project code is analyzed statically (AST & regex) and is never executed on the host server.
- **Bounded Self-Fixing**: Post-deploy health checks are limited to a maximum of 3 repair attempts.

---

## 📂 Project Structure

```text
saksham/
├── main.py              # FastAPI application, routes, and SSE streaming
├── config.py            # Environment settings and credential loading
├── schemas.py           # Pydantic data transfer objects and validation models
├── db.py                # SQLite database and run history persistence
├── upload.py            # Safe ZIP extraction & path-traversal validation
├── scanner.py           # Rule-based stack & framework detection
├── audit.py             # Secret scanning & config checks
├── fixer.py             # LLM patch generation & unified diff applicator
├── llm.py               # Google Gemini client wrapper
├── github_push.py       # GitHub repository creation and git push
├── deployer.py          # Render deployer, health checks & self-fix loop
├── redact.py            # Token and secret masking utility
├── templates/           # Starter templates (Dockerfile, README, .gitignore)
├── tests/               # Test suites and test fixtures
└── frontend/            # React + Vite user interface
```

---

## 📜 Documentation

- [`PRD.md`](./PRD.md) – Product Requirements & Specifications
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) – System Architecture & Module Contracts
- [`DESIGN.md`](./DESIGN.md) – UI/UX Design System & Color Tokens
- [`RULES.md`](./RULES.md) – Development Agreements & Quality Guardrails
- [`TASKS.md`](./TASKS.md) – Step-by-Step Task Tracker
- [`MEMORY.md`](./MEMORY.md) – Project Decisions & State Memory

