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
- Does not read or write repository files from the Tauri backend yet.

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

All UI data currently comes from `src/data/mockContext.json`. TypeScript data
contracts live in `src/types/contextos.ts`.
