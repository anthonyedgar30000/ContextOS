# ContextOS GUI

This directory contains a Tauri + React + TypeScript desktop UI for ContextOS.
The first version uses mock data so the interface can evolve independently from
the Python CLI.

## Commands

```sh
npm install
npm run dev
npm run build
npm run tauri dev
```

The Tauri shell uses the stable Rust toolchain declared in
`src-tauri/rust-toolchain.toml`.

## Current scope

- Displays mock Intent Contract, policy fallback, observed change, and assurance
  decision data.
- Does not call external APIs.
- Does not mutate Git state.
- Reads live change-classification data through a read-only Tauri command when
  the desktop shell is running.
- Falls back to bundled mock JSON when the backend command is unavailable.

## Backend integration architecture

The first real backend integration is intentionally narrow and read-only:

```text
React refresh button / initial load
        |
        v
@tauri-apps/api invoke("classify_changes")
        |
        v
Tauri command in src-tauri/src/lib.rs
        |
        v
python3 contextos.py classify-changes --format json
        |
        v
JSON parsed by src/services/classifier.ts
        |
        v
Overview, Files, Current Task, and Details panels
```

The Tauri command:

- executes `contextos.py classify-changes`
- requests JSON output with `--format json`
- returns stdout to the frontend
- does not write files
- does not stage, commit, push, or switch Git branches
- does not call external APIs

The React app:

- loads live classifier data on startup when Tauri is available
- exposes a **Refresh classification** button
- shows loading state while the command is running
- shows an error state and keeps mock fallback data if the command fails
- maps classifier findings into existing UI models for Overview, Files, Current
  Task, Scope Analysis, and Details

## Component hierarchy

```text
App
├── Sidebar
├── WorkspacePanel
│   ├── OverviewPanel
│   │   └── MetricCard
│   ├── CurrentTaskPanel
│   ├── FilesPanel
│   │   ├── FileStatusPill
│   │   └── RiskPill
│   ├── ScopeAnalysisPanel
│   ├── TokenUsagePanel
│   │   └── MetricCard
│   ├── ConstitutionPanel
│   │   ├── RiskPill
│   │   └── Apply Recommendation button
│   ├── AuditLogPanel
│   │   └── StatusPill
│   └── SettingsPanel
└── DetailsPanel
    └── StatusPill
```

The layout is a persistent three-column desktop shell:

- left sidebar navigation
- center workspace that switches between ContextOS views
- right details panel for assurance decision signals

## Folder structure

```text
gui/
├── src/
│   ├── components/
│   │   ├── DetailsPanel.tsx
│   │   ├── MetricCard.tsx
│   │   ├── Panels.tsx
│   │   ├── Sidebar.tsx
│   │   └── StatusPill.tsx
│   ├── data/
│   │   └── mockContext.json
│   ├── services/
│   │   └── classifier.ts
│   ├── types/
│   │   └── contextos.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── styles.css
└── src-tauri/
    ├── src/
    │   ├── lib.rs
    │   └── main.rs
    └── tauri.conf.json
```

Fallback UI data comes from `src/data/mockContext.json`. Live classifier data is
loaded through `src/services/classifier.ts` when Tauri is available. TypeScript
data contracts live in `src/types/contextos.ts`.
