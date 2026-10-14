# gemini-free-router Integration Guide for contentfte SEO Blog Agent

## Overview

`gemini-free-router` is a per-model RPM/RPD/TPM scheduling proxy that sits between your application and the Gemini API. It optimizes free-tier quota usage by scheduling requests preemptively instead of bursting into 429 errors and rotating keys.

Since Google quotas are **per project** (not per key), key rotation buys nothing — efficient scheduling is the only real lever.

This guide shows how to integrate the router with your **contentfte SEO Blog Agent** project.

## Installation

```bash
# From your contentfte project directory
npm i gemini-free-router

# Or install from the tarball if not yet published
npm pack gemini-free-router
tar -xzf gemini-free-router-0.2.0.tgz
```

## Quickstart

```bash
# 1. Set your Gemini API key
export GEMINI_API_KEY=your-53-char-key-starting-with-AQ.A

# 2. Start the router
npx gemini-free-router

# 3. Point your OpenAI-compatible client at the router
# From your contentfte code:
from openai import OpenAI
client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="router"  # any string; the router ignores it
)

# 4. Make requests
response = client.chat.completions.create(
    model="auto",          # router picks the best available model
    messages=[{"role": "user", "content": "Write a blog about SEO"}],
)
print(response.choices[0].message.content)
```

## Configuration

Create a `router.yaml` config file (or set env vars):

```yaml
# router.yaml
project: contentfte
listen:
  host: 127.0.0.1
  port: 8787
gemini:
  base_url: https://generativelanguage.googleapis.com/v1beta
  api_key_env: GEMINI_API_KEY
fleet_mode: merge  # or "replace" (default)
plan: free  # or "pro" via GFR_PLAN env
disabled: []     # drop deprecated models by id
pacing:
  max_queue_wait_s: 30
  burn_curve: even   # or "front-loaded"
  max_in_flight_per_model: auto
fallback:
  strategy: remaining-budget
learning:
  auto_apply: false    # set to "1" to auto-learn from 429s
modalities: [chat]
ledger_path: ./data/ledger.sqlite
dry_run: false
```

### Env overrides (`.env`)

| Variable | Description | Default |
|---|---|---|
| `GFR_HOST` | Bind host | `127.0.0.1` |
| `GFR_PORT` | Bind port | `8787` |
| `GFR_LEDGER` | Ledger file path | `./data/ledger.sqlite` |
| `GFR_TOKEN` | Auth token (optional) | — |
| `GFR_LEARN` | Enable forensics learner (`1`/`true`) | `0` |
| `GFR_DRY_RUN` | Synthetic responses, no quota spent | `0` |
| `GFR_LOG` | Log level (`debug|info|warn|error|off`) | `warn` |
| `GFR_BURN_CURVE` | `even` (spreads RPD across PT day) or `front-loaded` | `even` |
| `GFR_POOL_CONNECTIONS` | Max concurrent upstream connections | system default |
| `GFR_POOL_KEEPALIVE_MS` | Keep-alive timeout ms | `0` (auto) |
| `GFR_POOL_CONNECT_MS` | Connect timeout ms | `0` (auto) |
| `GFR_PLAN` | `free` or `pro` (overrides `router.yaml` `plan:`) | — |

## Key Features for SEO Blog Agent

### 1. Per-Model RPM/RPD/TPM Scheduling
- **RPM**: Sliding 60s window per model; requests queue (bounded wait) instead of firing into a 429
- **RPD**: Per-model daily counter resets at **midnight Pacific** (not local midnight)
- **TPM**: Input-token sliding window — estimated pre-call, corrected with actual `promptTokenCount` post-call

### 2. 429 Forensics & Learned Limits
- Google's 429 payloads contain `quotaId`, `quotaMetric`, `retryDelay`, and `limit:` fields
- The router parses these and **learns** actual `rpm`/`rpd`/`tpm` limits
- Set `GFR_LEARN=1` (or `plan: pro`) to auto-apply learned limits on restart
- Limits self-correct on first quota violation

### 2. 404 Dead-Model Circuit Breaker
- When a model returns 404 with "no longer available|not found for api|unknown model", the router:
  - Marks the model `doneForDay` via `ledger.markDoneForDay(model)`
  - Logs `model_unavailable` warning
  - Subsequent requests automatically route to the next-ranked model
  - The dead model re-enters the pool only after its minute window rolls

### 3. Plan Modes (`plan: free|pro`)
- **`plan: free`** (default): built-in `DEFAULT_FLEET` limits from AI Studio free-tier screenshots
- **`plan: pro`**: starts defaults at **4×** Google's published Pro-vs-free ratio; the 429 forensics learner then converges to your project's actual console limits
- Explicit `fleet:` lists (replace mode) are **never scaled** — copy exact per-model numbers from `aistudio.google.com/rate-limit` and use `fleet_mode: merge`

### 2. Tiered Model Ranking
- Models are ranked by **remaining daily budget × rolling quality** (EMA of success rate + latency)
- Exhausted models drop out for the day
- `x-gfr-tier: bulk|standard|scarce` header can influence ranking preference

### 3. Admission Control & 429 Handling
- **Admission control** runs before every upstream call via `acquire()`
- 429s are classified as `daily`, `minute`, or `token_minute` via forensics
- `retryDelay` from Google is honored exactly (floored to 5s)
- Ambiguous 429s back off exponentially (1s→60s, jittered)
- Daily exhaustion → model done-for-day; minute throttle → honor `retryDelay`; token-minute → per-model cooldown

### 4. Embeddings Support
- `POST /v1/embeddings` now goes through the same `acquire()` gate as chat
- RPM/TPM/RPD gating active (models with full windows sit out until roll)
- 404 breaker active (dead embedding models disabled for PT day)
- Dry-run mode for embeddings (`GFR_DRY_RUN=1`)

### 5. Rate-Limit Header (`x-gfr-tier`)
- Send `x-gfr-tier: bulk|standard|scarce` to preference model ranking
- Unknown tier values are ignored (falls back to remaining-budget ranking)

### 5. Dry-Run Mode
- `GFR_DRY_RUN=1` makes the proxy answer synthetically
- Admission control still runs against the ledger (exhausted models still return `429`)
- No request sent to Gemini, no quota reserved or committed
- Every dry-run response carries `x-gfr-dry-run: 1`

### 6. Structured Logging
- JSON lines on stderr — one object per line with `ts`, `level`, `event` and event fields
- Level via `GFR_LOG=debug|info|warn|error|off` (default `info` from CLI, `warn` when embedded)
- Events: `listening`, `served` (`model`, `latency_ms`), `quota_signal`, `rejected`, `upstream_error`

### 6. Docker

```bash
docker build -t gemini-free-router .
docker run -p 8787:8787 -e GEMINI_API_KEY=your-key gemini-free-router
```

The image runs on `0.0.0.0:8787` (binding baked in via `GFR_HOST`). CI probes `/healthz` on every push.

## Integrating with contentfte

In your contentfte SEO Blog Agent, you can now:

1. **Start the router** as a local proxy before your content generation pipeline
2. **Use `model: auto`** in all OpenAI-compatible calls — the router picks the best available model from your fleet
3. **Monitor `/admin`** endpoint for per-model remaining budget, PT-reset countdown, and learned limits
4. **Set `GFR_LEARN=1`** to auto-learn quota limits from 429 responses (especially useful when starting with a new Gemini key or plan)
5. **Configure `plan: pro`** if you have a Google AI Pro subscription, or keep `plan: free` for free-tier keys

### Example: contentfte Integration Snippet

```python
# In your contentfte blog generator
from openai import OpenAI
import requests

# Router is already running at http://127.0.0.1:8787
client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="router",
)

# "auto" lets the router pick the best model from your fleet
response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Generate an SEO-optimized blog post about sustainable farming"}],
    temperature=0.7,
)

blog_content = response.choices[0].message.content
print(f"Generated blog post ({len(blog_content)} chars)")

# Check admin stats
admin_resp = requests.get("http://127.0.0.1:8787/admin")
print(admin_resp.json()["learned_limits"])
```

## Maintenance

- **Update the fleet** via `router.yaml` or env overrides — never hardcode in code
- **Set `GFR_LEARN=1`** initially; after limits are learned, you can disable it or keep it for ongoing convergence
- **Verify your actual per-model limits** at `aistudio.google.com/rate-limit` and override via `fleet:` in `router.yaml` using `fleet_mode: merge` for precision
- **Rotate the API key** only if you truly need to change projects — quotas are per project, not per key

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| All requests get 429 quickly | RPM window full, no scheduling | Check `GFR_LEARN=1`; verify actual console limits |
| Model keeps returning 404 | Dead model not being bypassed | Ensure 404 breaker is active; check console for model availability |
| `x-gfr-tier` has no effect | Tier not in `bulk|standard|scarce` | Use exact tier values from fleet config |
| Dry-run mode not working | `GFR_DRY_RUN` not set | `export GFR_DRY_RUN=1` |
| Admin shows `0` remaining budget | Ledger not persisted | Check `ledger_path` and file permissions |

## Frequently Asked Questions

**Q:** Does the router multiply my quotas?  
**A:** No. It only schedules your existing entitlement more efficiently. Quotas are per project, not per key.

**Q:** Can I use multiple Gemini API keys?  
**A:** The router is designed for **one key / one project**. Key rotation doesn't help since quotas are project-level.

**Q:** What happens if I exceed my RPD limit?  
**A:** The model is marked `doneForDay` and won't be selected until the Pacific-day resets. Other models with remaining budget will be used.

**Q:** Can I run multiple router instances?  
**A:** Not recommended — they'd share no state and could exceed quotas. Use a single instance behind a load balancer if you need high availability.

## License

MIT - see [LICENSE](./LICENSE).

## Spec

See [docs/SPEC.md](./SPEC.md) for the detailed specification.

--- 

*Integration guide for contentfte SEO Blog Agent — gemini-free-router v0.2.0*