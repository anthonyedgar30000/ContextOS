# ContextOS

ContextOS is a Next.js MVP for an AI-native contextual media overlay prototype built for a cybersecurity capstone.

## Features

- Video player page with futuristic dark UI
- Contextual overlay cards rendered over the video
- Mode selector for Minimal, Movie, Sports, and Learning experiences
- Text command box for contextual questions
- Context Overlay Protocol JSON schema at `/api/protocol`
- SQLite-backed local user profile with overlay density, spoiler mode, preferred mode, and detail level
- Behavior logging for `overlay_opened`, `overlay_dismissed`, `useful_rating`, and `annoying_rating`
- Adaptive rules that reduce overlay frequency after dismissals or annoying ratings and increase detail after useful ratings
- Admin/debug dashboard at `/admin` showing logs and current profile state

## Getting started

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) for the video player and [http://localhost:3000/admin](http://localhost:3000/admin) for the debug dashboard.

## Data

Local prototype data is stored in `data/contextos.sqlite`. The database file is ignored by Git.
