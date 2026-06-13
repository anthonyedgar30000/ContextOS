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
