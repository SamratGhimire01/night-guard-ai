# Night Guard AI — Business Dashboard Reference UI

**This is a non-functional visual reference, not a deliverable.** It exists to
show a frontend developer the intended *layout and screens* of the business
dashboard, to be looked at alongside `docs/frontend-api-contract.md`. It is not
wired to the real API, not a component library, and not something to build on
top of — nothing here has real state, and clicking a button does nothing.

- 11 static HTML pages + one shared `shared.css`. No framework, no build step,
  no JavaScript. Navigation between pages is plain `<a href="...">` links.
- Placeholder content (business name "Willow Creek Family Dentistry", services,
  staff, appointments, knowledge docs, etc.) reuses real values that appeared in
  this project's own testing, so it reads as a grounded example rather than
  Lorem Ipsum — but every number and name on these pages is invented for
  display purposes. None of it is live data.
- A few pages carry an explicit inline note where the mockup shows something
  the live API doesn't fully support yet (e.g. Follow-ups' "scheduled runs"
  history, Settings' missing "invite teammate" button, Appointments' lack of
  pagination). Read those notes — they're cross-checked against
  `docs/frontend-api-contract.md`'s findings, not guesses.

## Visual design is a suggestion, not a spec

Clean, light-mode, professional business-SaaS look — sidebar nav, card-based
content, indigo/teal accent. This was a deliberate choice *for this reference
only* because the dashboard is business-facing, unlike the dark/purple test-chat
tool built earlier in this project (that was an internal dev tool). **The
frontend developer building the real dashboard has full creative license to
change colors, layout, spacing, component style — anything.** Nothing here is
meant to be pixel-matched.

## Pages

| Page | File |
|---|---|
| Overview / dashboard home | `overview.html` |
| Appointments | `appointments.html` |
| Services | `services.html` |
| Staff | `staff.html` |
| Business Hours | `hours.html` |
| Knowledge Base | `knowledge.html` |
| AI Training Room | `training.html` |
| Human Handoffs | `handoffs.html` |
| Reports | `reports.html` |
| Follow-ups | `followups.html` |
| Settings | `settings.html` |

## Viewing it

Open `overview.html` directly in a browser, or serve the folder locally, e.g.:

```
python3 -m http.server 8000 --directory docs/ui-reference
```

then visit `http://localhost:8000/overview.html` and click through the sidebar.

## What to actually build from

**`docs/frontend-api-contract.md`** — every real endpoint, request/response
shape, RBAC rule, and known inconsistency in the live API. This folder shows
*what it could look like*; that document says *what's actually there to build
against*.
