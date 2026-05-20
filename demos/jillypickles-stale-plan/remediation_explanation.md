# Remediation explanation

The correct recovery is to re-establish a fresh local execution context before
continuing.

## Option A: continue the Client A work

If the intended task is still the Client A copy update:

1. switch back to BranchA
2. regenerate or review the context packet for BranchA
3. run `contextos ingest`
4. re-run verification before committing

```sh
git checkout feature/clientA
./contextos ingest context_packet.yaml
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce
```

## Option B: change deployment settings on BranchB

If the intended task is now deployment work on BranchB:

1. create or review a new context packet for BranchB
2. update `allowed_paths` to include the deployment file
3. decide whether protected deployment paths should remain blocked or be handled
   through an explicit review path
4. run `contextos ingest`
5. re-run verification before committing

```sh
git checkout main
./contextos ingest context_packet.yaml
python3 verify_cli.py --session session.json --policy policy.yaml --protected-mode enforce
```

## Why not bypass the hook?

Bypassing the hook would allow a commit created under stale assumptions. The
demo is designed to show the safer local workflow: refresh the context first,
then retry verification and commit.
