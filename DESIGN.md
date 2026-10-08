# DESIGN.md: Saksham

> Source: the UI canvas already designed in this conversation (3 screens: Upload, Audit, Live). Reference: https://claude.ai/artifact/GrZE6yjTnAsu47BtBKqarV. Items not in that design are marked **Proposed** (must follow the same tokens) or **Needs clarification**.

## 1. Design philosophy
Calm, clear, trust-building. The product's promise is safety, so the screen shows risk plainly (score, severity, diff) and uses red only for risk and green only for success. Every screen shows where the user is in the 4 steps. Nothing happens without explicit approval.

## 2. Color system
| Token | Value | Use |
|---|---|---|
| Page background | #F4F6F8 | App background |
| Surface | #FFFFFF | Cards, sidebar |
| Border | #DDE3E8 | Card/sidebar borders |
| Strong border | #C5CED5 | Inputs, secondary buttons |
| Ink | #12202B | Primary text |
| Muted text | #52636F | Secondary text |
| Accent (teal) | #0B6E69 | Primary button, logo, active nav, active step |
| Accent tint | #E3F1EF | Active nav bg, completed step, chips (text #085048) |
| Danger | #B3261E | Low score, risk |
| High severity | bg #FBE4E2, text #8C1D17 | Badge, removed diff line |
| Medium severity | bg #FCEBCF, text #7A4500 | Badge |
| Success | #1B7F4B (text #14603A) | High score, done states |
| Success tint | #DDF2E6 | Added diff line |
Rule: colors that must be told apart also differ in lightness, not only hue.

## 3. Typography
Font: Plus Jakarta Sans (weights 400, 600, 800), fallback system-ui. Sizes: page title 28px/800; score number 56px/800; card heading 15-16px/800; body 15px; secondary 13-14px; code/log: monospace 13px. UI language: English throughout.

## 4. Spacing and layout
Sidebar 224px; main padding 32px top/bottom, 40px sides; content max width about 980-1000px; card padding 20px; gap between cards 16px; card radius 12px; control radius 8px. Cards wrap using min-widths (220-300px).

## 5. Buttons
Primary: teal fill, white text, radius 8px, min height 44px, weight 800. Secondary: white, 1px #C5CED5 border. One primary action per screen. Labels are verbs: "Analyze project", "Approve 3 fixes and deploy", "Open live app". Real `<button>` elements.

## 6. Inputs and forms
Min height 44px, 1px #C5CED5 border, radius 8px, visible label above (13px muted) linked with `for`. Fields in Upload: Repo name (text), Visibility (select: Private default, Public), Deploy on (select: Render).

## 7. Cards
White, 1px #DDE3E8 border, radius 12px. Dashed border (#8FA3B0) for the upload drop zone. No shadows.

## 8. Navbar / sidebar
Left sidebar: logo "Saksham" (teal, 22px/800), items New deploy (active), History, Connections, Settings. Active item: tint bg, teal text, weight 800. Step bar above the page title: 4 pills (Upload, Audit, Fix, Deploy); current = teal fill, completed = tint, upcoming = grey.

## 9. Modals
A confirm dialog before making a repo Public, using the card style and one primary button.

## 10. Tables and lists
Issues list: rows separated by 1px lines; each row = severity badge (High/Medium) + bold title + muted one-line explanation. Checklist rows on Live: label left, status right ("Done", "200 OK"). Diff: monospace, removed line red tint with "-", added line green tint with "+", horizontal scroll.

## 11. Icons
Single stroke icon set or clean SVG iconography, never emoji.

## 12. Notifications
Inline banners using danger/success tints with a plain English sentence explaining what happened and what action to take.

## 13. Loading states
Step bar shows current step; Live log streams lines as they arrive (SSE).

## 14. Empty states
Headline naming the section, one-line body, verb CTA (e.g., "Deploy your first project").

## 15. Error states
Clear explanation of what failed and how to resolve it; blocked push explains which secret was found and where; deploy failure shows root cause and retry count.

## 16. Responsive / mobile
Designed at 1280px width. Cards wrap on narrower widths.

## 17. Accessibility
Real buttons, labels tied to inputs, text contrast at least 4.5:1, touch targets at least 44px, severity conveyed by text as well as color, visible keyboard focus.

## 18. Page-by-page UI requirements
**Upload:** step 1 active; title "Deploy a new project"; dashed drop zone showing file name and size; Detected card with chips (Python, FastAPI, Port 8000, requirements.txt) and the three fields; primary "Analyze project".
**Audit:** step 2 active; title "Audit result: <project>"; score card (40/100, red bar, "Not safe to push"); Issues card (High: API key hardcoded in config.py line 12; Medium: .env not gitignored; Medium: port hardcoded); Suggested fix card with diff and explanation; primary "Approve 3 fixes and deploy", secondary "Review each fix".
**Live:** step 4 active; title "<project> is live"; score card 95/100 with "Previous: 40/100"; checklist (fixes applied, repo pushed, deployed, health check 200 OK); Live URL and GitHub repo cards; Deploy log card; primary "Open live app", secondary "Deploy another project".
**History, Connections, Settings:**
- History: List of previous analysis and deployment runs with timestamp, project name, score, and status.
- Connections: Setup and status of GitHub Personal Access Token and Render API token.
- Settings: App configuration and preferences.

## 19. Interaction behavior
- Analyze triggers the audit; progress shown in the step bar.
- Nothing is applied until the user approves.
- Approve starts apply, push, deploy; Live screen shows streamed log.
- Review each fix lets the user accept patches one by one.
