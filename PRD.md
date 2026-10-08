# PRD.md: Saksham

> Source: full conversation history. Anything not decided there is marked **Needs clarification (NC-n)**. The NC list is in section 17 and is shared by all six files.

## 1. Project name
**Saksham** (earlier placeholder name: DeploySafe).

## 2. One-line description
An AI agent that audits a project before it goes to GitHub, proposes fixes the user approves as a diff, pushes the repo, deploys it, and verifies the live URL.

## 3. Problem statement
Students and beginners leak API keys on GitHub, or hit one of 10+ deployment steps wrongly so the app fails. Existing tools (Vercel, Render, Claude Code with gh CLI, GitHub Agentic Workflows) deploy or push, but do not audit first or self-fix beginner mistakes.

## 4. Goal
Build, within a 24-48 hour hackathon window, a working MVP whose differentiator is a **safety layer**: pre-push audit, user-approved auto-fix, post-deploy verification, and beginner-friendly explanations. Positioning line: "Vercel deploys. Saksham checks that deploying is safe and correct, and fixes it if it fails."

## 5. Target users
- Primary: beginner and student developers deploying their own projects.
- Niche for MVP (decided): student FastAPI (+ React) projects.
- Secondary (hackathon context): judges who need a 2-minute demo.

## 6. Core use cases
1. Upload a project and get a Deploy Readiness Score with a list of issues.
2. Review and approve suggested fixes as a diff.
3. Push the fixed project to a new GitHub repo and deploy it.
4. See a live URL after a passing health check; if it fails, see the cause and an automatic retry.

## 7. Complete feature list
1. Project upload (zip or folder; see NC-10).
2. Project scanner (rule-based): language, framework, entry point, port, dependencies. LLM only if rules fail.
3. Secret scan of files **and git history** (gitleaks or detect-secrets).
4. Config checks: `.env` not in `.gitignore`, hardcoded localhost URLs, DEBUG on, hardcoded port, junk files (`node_modules`, `venv`, `.DS_Store`).
5. Deploy Readiness Score (0-100) with reasons (formula: NC-7).
6. LLM auto-fix returning structured patches (file, old, new, reason); explanations in simple language.
7. Generated files from templates (LLM fills blanks only): README, Dockerfile, `.gitignore`, GitHub Actions workflow.
8. Human approval step: shows files to be pushed, new files, repo visibility, diff.
9. GitHub push: create new repo, commit, push.
10. Deploy to one platform (Render or Railway; NC-4); set secrets through the platform API.
11. Post-deploy verification: health check, log-based root cause, auto-fix retry (max 2-3).
12. Live progress logs (SSE).
13. Output: live URL, repo link, short report.
14. Deploy history (implied by the History screen; NC-5).
15. Hackathon deliverables (non-software): 7-slide PPT, backup demo video, stat from scanning 20-30 public student repos.

## 8. Must-have features (MVP)
Features 1-13 above, restricted to one project type (FastAPI) and one deploy platform. Features 3, 4, 6, 8 (audit, fix, approval) are the differentiator and must never be cut.

## 9. Nice-to-have features
- Node/React project support.
- Multi-platform deploy (Railway and Render both, GitHub Pages for static sites, Docker).
- OAuth for GitHub instead of a Personal Access Token.
- Packaging as a GitHub Action, `gh` extension, or MCP server (NC-1).
- Portfolio-ready repo output (screenshots, badges, resume summary).
- Review-each-fix mode (button exists in the design).
- Fine-tuning, LangGraph, Redis, Celery: **not** for MVP.

## 10. User flows
**Main flow**
1. User opens New deploy, uploads project.
2. Saksham detects stack, shows chips (Python, FastAPI, port, requirements.txt), repo name, visibility (default Private), deploy platform.
3. User clicks Analyze project. Backend scans, audits, generates fix suggestions.
4. Audit screen shows score, issues (High/Medium), diff, explanation.
5. User clicks Approve fixes and deploy (or Review each fix).
6. Fixes applied, repo created and pushed, deployed, health checked.
7. Live screen shows score, step results, log, live URL, repo link.

**Failure flow:** health check fails, logs go to the LLM, root cause is shown, a patch is applied, redeploy; stop after the retry limit and show the cause.

**Blocked-push flow:** unresolved secret detected, push is blocked and the user is told why.

## 11. Functional requirements
- FR1: Detection of language/framework/port via file rules first.
- FR2: Push is blocked while any unresolved secret exists.
- FR3: No patch is applied and nothing is pushed before explicit user approval.
- FR4: LLM output must validate against a Pydantic schema; invalid output is rejected.
- FR5: Generated files come from templates; LLM only fills blanks.
- FR6: Repo creation only creates new repos; never deletes or force-pushes.
- FR7: App secrets are set through the platform secrets API, never pushed.
- FR8: Retry loop is capped (2-3) and each retry receives fresh logs.
- FR9: Progress is streamed live to the UI.

## 12. Non-functional requirements
- Reliability on the chosen niche is the top quality attribute; demo must work on a random FastAPI project from a judge.
- MVP deliverable within 24-48 hours; 25-32 hours of coding estimated.
- Large projects: send file tree plus important files to the LLM, not everything.
- Secrets and tokens never appear in logs or LLM prompts (see RULES.md).
- Max upload size and timeouts: NC-10.

## 13. Authentication requirements
- GitHub: Personal Access Token for MVP with scopes `repo` and `workflow`. Permission used only to create new repos. OAuth is post-MVP.
- Deploy platform: Render API token (`RENDER_API_KEY`).
- LLM provider: Google Gemini API key (`GEMINI_API_KEY`, model `gemini-2.5-flash`).
- Saksham user login: Single-user, no login for MVP (local/web tool).

## 14. Data requirements
- Uploaded project files: Temporary working copy extracted from ZIP (max 25MB, path-traversal validated), deleted after run.
- Per run: detected stack, issues, score, patches, deploy logs, URLs.
- Tokens and keys: supplied via environment configuration (`.env`); never stored in plaintext in logs or database.
- Persistence: SQLite database for run and deploy history.

## 15. Important constraints
- Do not train a model; use an LLM with tool-calling (Google Gemini `gemini-2.5-flash`).
- Use existing tools (gitleaks, GitHub API, Render API) rather than rebuilding them.
- Team 2-4 students; skills: Python, FastAPI, React.
- Free-tier limits and cold starts on Render; test accounts and tokens before the hackathon.
- Idea must not be generic.

## 16. Out of scope
- Training or fine-tuning models.
- Supporting every framework or monorepos in MVP.
- Multiple deploy platforms in MVP (Render is the sole target).
- Deleting repos, force-pushing, or any destructive GitHub action.
- LangGraph, Redis, Celery in MVP.
- User login / multi-tenancy in MVP.
- Mobile-specific design.

## 17. Decisions & Clarifications Log
| ID | Topic | Decision / Status |
|---|---|---|
| NC-1 | Product Form | **Decided:** Standalone web application with full pipeline. |
| NC-2 | UI Framework | **Decided:** React (Vite) with vanilla CSS matching DESIGN.md tokens. |
| NC-3 | LLM Provider | **Decided:** Google Gemini API (`gemini-2.5-flash` via `google-genai`). |
| NC-4 | Deploy Platform | **Decided:** Render API. No mock deployer in product flow; MOCK used only in unit/integration tests. |
| NC-5 | Database / History | **Decided:** SQLite database for storing deploy history and run results. |
| NC-6 | Saksham Login | **Decided:** Single-user application, no login in MVP. |
| NC-7 | Score Formula | **Decided:** Base 100; High severity -30, Medium -15, Low -5. (Floor 0, Cap 100). |
| NC-8 | UI Language | **Decided:** English throughout the entire UI. |
| NC-9 | Hackathon details | Non-blocking hackathon deliverables (7-slide deck, backup demo video, leak stat). |
| NC-10 | Upload & Git history | **Decided:** ZIP upload, max 25MB, path-traversal check. Scan git history when `.git` included, else report "history not available". |
| NC-11 | Versions | **Decided:** Python 3.11, pinned dependencies, `gitleaks` for secret scanning. |
| NC-12 | Extra screens design | Standard cards/tables in English using DESIGN.md tokens for History/Connections/Settings. |
| NC-13 | Deploy scope | **Decided:** Full pipeline including live cloud deploy to Render + health check verification. |

## 18. Success criteria
- Demo project with a planted API key and wrong port: score goes 40 to 95 on screen.
- Secret caught before push; diff shown; fix applied after approval; live URL passes health check, all within about 2 minutes.
- A fresh random FastAPI project deploys successfully (target 95%+ reliability in the niche).
- Stat available: "X of 20-30 public student repos had leaked secrets".
- PPT (7 slides) and backup demo video exist.
