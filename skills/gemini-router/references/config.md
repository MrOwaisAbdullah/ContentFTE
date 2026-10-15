# router.yaml field reference

Everything the contentfte integration actually exercises, verified against
router 0.4.1. Minimum viable file is `listen` + a `GEMINI_API_KEY` in the
environment; the rest is what makes it survive real traffic.

```yaml
project: my-app
listen: { host: 127.0.0.1, port: 8787 }
fleet_mode: merge
fleet:
  - { model: gemini-flash-latest, rpm: 5, rpd: 20, tpm: 250000, tier: scarce }
disabled:
  - some-dead-model
pacing: { max_queue_wait_s: 30, burn_curve: even }
learning: { auto_apply: true }
modalities: [chat]
ledger_path: ./data/ledger.sqlite
```

## Fields

| Field | Meaning |
| :--- | :--- |
| `project` | Label carried in logs/admin output. |
| `listen.host` / `listen.port` | Bind address. Default port is `8787`; clients then use `http://127.0.0.1:8787/v1`. |
| `fleet_mode: merge` | The router's **built-in fleet is the base** (its shipped limits were captured from `aistudio.google.com/rate-limit`); entries under `fleet:` **overlay/appended** on top. Explicit numbers you write are never scaled by the plan. |
| `fleet[]` | `{ model, rpm, rpd, tpm, tier }` per entry. Declare **every model your app requests that is not built-in** — for an unknown requested model the router auto-picks a different candidate (`resolveModel` fallback), which is silent and easy to miss. `tier` labels quota value (values seen: `scarce` for the 20-RPD `gemini-flash-latest`, `bulk` for high-RPD bulk models). |
| `disabled[]` | Models kept out of service and failover. Dead-but-listed models burn failover slots and can surface as empty `content_filter` responses (observed live). |
| `pacing.max_queue_wait_s` | How long a request may wait in the scheduler queue before it is treated as un-servable (then your failover policy takes over). |
| `pacing.burn_curve: even` | Spread quota burn across the window rather than bursting at the front. |
| `learning.auto_apply` | `true` == `GFR_LEARN=1`: auto-apply limits learned from real 429 payloads — converges on the account's true rpm/rpd/tpm instead of guessed defaults. **Editing rpm/rpd/tpm for a model clears its learned value.** |
| `modalities` | `[chat]` for this integration. |
| `ledger_path` | SQLite ledger holding all quota state (sliding windows + learned limits). Flushed on SIGTERM — that is what CI relies on (see `ops-and-ci.md`). Keep it out of git. |

## Environment variables

| Var | Effect |
| :--- | :--- |
| `GEMINI_API_KEY` | Required. The single key the whole fleet runs on. |
| `GFR_PORT` | Overrides the bind port. |
| `GFR_TOKEN` | Start the router with it set and clients must send `Authorization: Bearer <GFR_TOKEN>`. |
| `GFR_PLAN` | `free` (default) or `pro` — `pro` scales the **built-in default** limits ×4. |
| `GFR_LEARN=1` | Same as `learning.auto_apply: true`. |
| `GFR_LOG=info` | Log verbosity (what CI uses). |

## Model selection semantics

- `model: "auto"` → the router picks the healthiest fleet model per request.
- `model: "<name>"` → served by that model if it is in the (merged) fleet;
  otherwise auto-picked — see the `fleet[]` footgun above.
- 429 from the router carries `code=free_tier_exhausted` + `retry-after` when
  the whole fleet is out of quota for now.

## The shallow-probe trap (why `disabled:` exists)

A model can answer `"Say OK"` with HTTP 200 and still be unusable on real
instructions — e.g. gemma-4-31b-it returned 200 with **empty content**
(`finishReason=STOP`) or verbose planning text that ignored the prompt. A 200
never triggers router failover, so such a model poisons every auto-pick. Probe
with a real instruction and require the exact string back:

```bash
curl -s -H "x-goog-api-key: $GEMINI_API_KEY" -H "content-type: application/json" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply with exactly: ROUTER_OK"}]}]}' \
  https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent
```

Disable anything that doesn't return exactly `ROUTER_OK`. The contentfte
`router.yaml` keeps both gemma-4 models disabled with the probe evidence in a
comment.

## Observability

- `GET /healthz` — liveness only. **Not sufficient** as an integration check.
- `GET /admin` — JSON with `plan`, `fleet_mode`, `fleet[]` (models actually
  being served after merge + disabled exclusions) and ledger state. This is
  what integration tests should assert against.
