# Freelancer Context Switch Demo

A solo developer is moving between ClientA and ClientB. Cursor retains stale
ClientA assumptions and applies a ClientA config to ClientB.

- Without ContextOS, the bad mutation can be committed and pushed.
- With ContextOS, the AI session context says `ClientA` while the governed target
  policy says `ClientB`, and the changed file is outside the declared ClientA
  task scope. The commit gate blocks before Git becomes authoritative.

Run:

```bash
demo_freelancer_context_switch/run_without_contextos.sh
demo_freelancer_context_switch/run_with_contextos.sh
```
