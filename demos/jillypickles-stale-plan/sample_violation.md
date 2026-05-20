# Sample violation

The stale execution plan was generated on `feature/clientA`, where the reviewed
context only allowed changes to Client A documentation and recommendation code.

After switching locally to `main`, the simulated assistant continues as if it is
still operating under the `feature/clientA` context and stages a deployment
change:

```diff
diff --git a/deploy/production.yml b/deploy/production.yml
index 2f2e4c1..d4f6b7a 100644
--- a/deploy/production.yml
+++ b/deploy/production.yml
@@
 service: jillypickles-web
-replicas: 2
+replicas: 4
```

This is invalid for two independent reasons:

- `.contextos/session_context.json` was ingested on `feature/clientA`, but the
  local branch is now `main`.
- `deploy/production.yml` matches protected path pattern `deploy/**`.

The verification step fails before any commit or push.
