# Tapebuilding Web UI

React SPA frontend for the tapebuilding music library app. Served by the same FastAPI backend (`src/app/main.py`) at `http://localhost:8000`.

## Tech Stack

- **React 18** + **TypeScript**
- **Vite** (build tool, dev server)
- **TanStack Query** (server state / data fetching)
- **TanStack Virtual** (virtualized track table)
- **dnd-kit** (drag-and-drop playlist reordering)
- **Radix UI ContextMenu** (right-click track context menu)
- **Zustand** (client selection state)
- **Oxlint** (linting)

## Setup

From the repo root:

```bash
# Install dependencies (one-time)
cd src/app/ui && npm install

# Build the frontend (production)
npm run build

# Or from the repo root without cd:
npm run build --prefix src/app/ui
```

The built SPA is output to `src/app/ui/dist/` and served by FastAPI with SPA fallback.

## Running

### Production (from repo root)

```bash
npm run build --prefix src/app/ui
uv run app
```

Open `http://localhost:8000`.

If you have GNU `make` installed (via `winget install make` or `choco install make`):

```bash
make build   # builds the frontend
make start   # starts the backend
```

### Dev Mode (two terminals)

Terminal 1 — backend:
```bash
uv run app
```

Terminal 2 — frontend dev server (port 5173, proxies `/api` and `/files` to port 8000):
```bash
npm run dev --prefix src/app/ui
```

## Project Structure

```
src/app/ui/
├── src/
│   ├── main.tsx              # React entry point
│   ├── App.tsx               # App shell + routing
│   ├── App.css               # App-level styles
│   ├── index.css             # Design system (colors, typography, layout)
│   ├── assets/               # Static assets (hero image, Vite/React logos)
│   ├── components/
│   │   ├── AppShell.tsx          # Shell layout (sidebar + main pane)
│   │   ├── Sidebar.tsx           # Playlist navigation sidebar
│   │   ├── LibraryView.tsx       # Library browse view (track table)
│   │   ├── PlaylistsView.tsx     # Playlist listing view
│   │   ├── PlaylistDetailView.tsx| Playlist detail/edit view
│   │   ├── PlaylistCard.tsx      # Playlist card in listing
│   │   ├── TrackTable.tsx        # Virtualized track table (selection, right-click)
│   │   ├── TrackMenu.tsx         # Radix context menu (add to playlist, etc.)
│   │   ├── TrackMenu.tsx         # Context menu with add-to-playlist checklist
│   │   ├── CoverImage.tsx        # Playlist cover upload/display
│   │   ├── AudioPlayer.tsx       # Inline audio player (/files/ endpoint)
│   │   ├── JobsView.tsx          # Background job monitoring
│   │   └── DownloadView.tsx      # Download job creation
│   ├── services/
│   │   └── api.ts              # Fetch-based API client (query params for jobs, FormData for covers)
│   ├── store/
│   │   └── useSelectionStore.ts  # Zustand store for track selection state
│   └── utils/
│       └── useInterval.ts      # Polling interval hook
├── index.html                # Vite entry HTML
├── tsconfig.json             # TypeScript config
├── vite.config.ts            # Vite config
├── package.json              # npm scripts (dev, build, lint, preview)
└── README.md                 # this file
```

## Key Architecture Decisions

**Build output served by FastAPI.** Vite builds to `dist/`, which FastAPI serves with SPA fallback (all non-API routes fall back to `index.html`). No separate dev/production frontend hosting needed.

**CSS custom properties in JSX.** Design tokens (`--bg`, `--outline-soft`, etc.) live in `index.css`. In JSX `style` objects they must be string literals: `color: 'var(--outline-soft)'` (not unquoted).

**ContextMenu controlled open.** Radix UI `@radix-ui/react-context-menu` v1.0.0's `Root` doesn't accept a controlled `open` prop. The menu auto-opens by programmatically clicking a hidden fixed-position trigger button positioned at the right-click x/y coordinates.

**API client.** `services/api.ts` uses `fetch` directly. `createJob` sends `job_type`/`target`/`organize` as URL search params (matching the FastAPI endpoint signature — fixes a previous 422 error). `uploadCover` uses `FormData` POST to `/api/playlists/{name}/cover`.

**Selection state.** `store/useSelectionStore.ts` (Zustand) holds selected track paths. Click = select, Ctrl/Cmd+click = toggle, Shift+click = range select. The context menu acts on the current selection, not just the right-clicked row.

## Scripts (`src/app/ui/package.json`)

- `npm run dev` — start Vite dev server (port 5173)
- `npm run build` — TypeScript check + Vite production build
- `npm run lint` — Oxlint
- `npm run preview` — preview production build locally
