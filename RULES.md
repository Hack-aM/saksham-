# RULES.md: Saksham

> Strict rules for the AI coding agent. These rules must stay consistent with ARCHITECTURE.md. If a rule conflicts with a task, stop and ask.

## 1. Working agreements
1. Read PRD.md, ARCHITECTURE.md, DESIGN.md, TASKS.md and MEMORY.md before starting any task.
2. Work on **one task at a time**, in TASKS.md order.
3. **Ask before making major architectural changes** (new framework, new database, changing module boundaries, adding a platform, changing the API shape).
4. **Do not modify unrelated files.** Touch only files listed in the task.
5. **Never use placeholder or fake functionality where real functionality is required.** No hardcoded fake scores, fake deploy results, or stubbed GitHub calls presented as working. A stub is allowed only if the task says so and it is labelled `# STUB` and logged in MEMORY.md.
6. **Never claim a feature is complete without testing it.** Report what was run and the result.
7. Do not invent requirements. If something is unclear, see Needs clarification (NC-n) in PRD.md and ask.
8. Update MEMORY.md and the task status at the end of every task.

## 2. Coding standards
- Python for the backend. Use type hints on all function signatures.
- Pin the Python version and tool versions at setup (NC-11); use a formatter and linter chosen at that time.
- Prefer small pure functions. A function should do one thing and fit on one screen (about 40 lines max). Split otherwise.
- No dead code, no commented-out code, no TODOs without a task reference.
- Comments explain why, not what.

## 3. Naming conventions
- Python: `snake_case` for functions/variables/modules, `PascalCase` for classes and Pydantic models, `UPPER_SNAKE` for constants.
- API paths lowercase, nouns (`/analyze`, `/approve`).
- If React is chosen (NC-2): `PascalCase` components, `camelCase` functions, files named after the component. TypeScript only if the team confirms it; no `any`, strict mode on.

## 4. File organization
Follow the structure in ARCHITECTURE.md section 9. One responsibility per module. New modules need a reason recorded in MEMORY.md. Templates live in one folder. Tests mirror source file names under `tests/`.

## 5. Component rules (UI)
- Follow DESIGN.md tokens exactly; do not introduce new colors, fonts, or spacing.
- Reuse components (cards, badges, buttons, diff view); never copy-paste markup between screens.
- Use real `<button>`, `<a>`, `<input>` + `<label>`; no clickable divs.
- Every screen handles loading, empty, and error states.

## 6. Error handling
- Never swallow exceptions. Catch specific exceptions, add context, return clear errors.
- User-facing errors say what happened and what to do; never show raw stack traces or raw exception strings.
- External calls (LLM, GitHub, platform API, subprocess) need timeouts and handled failures.
- Retry loops are bounded (2-3) with fresh logs on each attempt.

## 7. Security rules
- Never commit secrets. `.env` is git-ignored; provide `.env.example` with names only.
- Never log tokens or detected secret values; redact.
- Never send tokens or detected secret values to the LLM.
- Push is blocked while any unresolved secret exists; re-scan after applying patches.
- The GitHub token may only create new repos. **Never** write code that deletes repos or force-pushes.
- Validate all LLM output with Pydantic before use. Apply patches only to files inside the working project directory.
- Extract uploads safely (no path traversal); enforce size limits (NC-10).
- Do not execute uploaded project code on the Saksham host.

## 8. API rules
- Request and response bodies use Pydantic models.
- Correct HTTP status codes; consistent error shape.
- Endpoints that change anything require the approval payload; `/analyze` must be read-only with respect to the user's project and GitHub.
- Long operations stream progress over SSE.

## 9. Database rules
- Persistence is undecided (NC-5). Do not add a database until decided.
- If added: migrations for every schema change, parameterized queries only, no tokens or secret values in tables.

## 10. Dependency / library rules
- Use only libraries listed in ARCHITECTURE.md section 13. Adding any other dependency needs approval and a one-line justification in MEMORY.md.
- Pin versions in the dependency file. Prefer maintained libraries; do not reimplement secret scanning.
- Do not add LangGraph, Redis, or Celery for the MVP.

## 11. Testing rules
- Every module gets unit tests (pytest).
- Required fixtures: a demo project with a hardcoded API key, `.env` not ignored, hardcoded port, and a clean project.
- Required tests: secret detected in files and in history; push blocked on unresolved secret; patch schema validation rejects bad LLM output; retry cap honored; zip path traversal rejected.
- Integration tests for GitHub/platform calls use a test account or mocks that are clearly marked; the final end-to-end test uses real services.
- Tests must pass before a task is marked DONE.

## 12. Git rules
- Small commits, one task per commit or branch. Message format: `T<number>: short description`.
- Do not commit generated files, `.env`, `node_modules`, `venv`, or build output.
- No force-push and no history rewriting on shared branches.

## 13. UI consistency rules
- One primary button per screen; verb-first labels.
- Colors, spacing, and typography from DESIGN.md only.
- Red means risk, green means success; severity also shown as text.

## 14. Do not duplicate code
Search for existing helpers before writing new ones. Extract shared logic into one module instead of copying.
