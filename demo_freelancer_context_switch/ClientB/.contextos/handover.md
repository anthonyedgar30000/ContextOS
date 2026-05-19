# ClientB Freelancer Handoff

- Originating task: update ClientB storefront copy only
- Originating branch: current feature branch
- Repo assumptions:
  - ClientB is the active client
  - ClientA settings must not be copied into ClientB
  - payments remain enabled
  - route remains `/client-b/shop`
- Expected scope:
  - `demo_freelancer_context_switch/ClientB/site_config.json`
  - `demo_freelancer_context_switch/ClientB/ui/*`
- Unresolved warnings: none
- Stale assumptions to re-check:
  - Cursor may still have ClientA context in memory
  - support email and route must remain ClientB-specific
