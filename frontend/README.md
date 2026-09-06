# Night Guard AI — Business Dashboard

The real, running business-facing web dashboard (React + TypeScript + Vite + React
Router + Mantine). See `PHASE_STATUS.md` (Phase 35+) for the stack decision and
per-phase build notes. Unlike `docs/ui-reference/`, this app is wired to the real API.

## Run it

```
npm install
npm run dev
```

Then open `http://localhost:5173/`. The backend must be running (`docker compose up -d`
from the repo root) — this app talks to it at the URL in `.env` (`VITE_API_BASE_URL`,
defaults to `http://localhost:8010/api/v1`).

## Scripts

- `npm run dev` — Vite dev server
- `npm run build` — type-check (`tsc -b`) then production build
- `npm run lint` — oxlint
- `npm run preview` — serve the production build locally
