# contentfte SEO Blog Agent — gemini-free-router Integration Guide

> **AS IMPLEMENTED (2026-10-14, branch `feature/router-integration`)** — the
> integration below is live in this repo. The actual wiring differs from the
> generic walkthrough further down; trust this section:
>
> | Piece | Where it lives |
> |---|---|
> | npm dependency | `package.json` → `npm ci` / `npm run router` |
> | Router config | `router.yaml` (fleet_mode: merge, gemini-flash-latest appended, gemma-4-31b-it re-enabled 2026-10-15 after a healthy direct probe, gemma-4-26b-a4b-it still disabled — Google 500s it on this account) |
> | Chat routing switch | `GFR_BASE_URL=http://127.0.0.1:8787/v1` in `.env` → `blog_agent/custom_runner.py::get_gemini_client()` points every Gemini call at the router; **unset = legacy direct-Google path** |
> | Vision QA | **routed through the router** — `IMAGE_VLM_ENDPOINT=http://127.0.0.1:8787/v1/chat/completions` in `.env` → `lib/image_vision.py` posts images through the router too. Requires gemini-free-router **>= 0.3.0** (0.2.x silently dropped image parts — only `type:"text"` was translated; fixed 2026-10-14: `image_url` → Gemini `inline_data`/`file_data`, flat ~1100 tokens/image estimate measured live). Registry install bumped to `^0.3.0` after publish. Verified live end-to-end 2026-10-14: accurate caption through the registry-installed router, `prompt_tokens: 1072`, and `describe_image_vlm()` returned a correct description with `fallback: false` |
> | Quota persistence across workflow runs | `.github/workflows/pipeline.yml`: ledger `data/` restored/saved via `actions/cache` (`gfr-ledger-*` keys), router started before the stage with health-check, SIGTERM-stopped after (flush), serialized by the existing `concurrency: contentspark-pipeline` |
> | Verification | `GFR_BASE_URL=... uv run python scripts/test_router_integration.py` — checks client base_url, a live completion through the router, and `/admin` plan+fleet |

## Purpose

This guide explains how to integrate `gemini-free-router` v0.2.0 into your **contentfte SEO Blog Agent** project. The router runs as a local proxy that optimizes your Gemini API quota, enabling efficient blog generation without key rotation or quota exhaustion.

## Prerequisites

- Node.js >= 22.18
- A Gemini API key (free-tier or Pro)
- Your contentfte project source code

## Step 1: Install the Router

```bash
# From your contentfte project root
npm i gemini-free-router

# Or if not yet published, use the tarball:
# npm pack gemini-free-router
# tar -xzf gemini-free-router-0.2.0.tgz
```

## Step 2: Start the Router

```bash
# Basic startup with your API key
export GEMINI_API_KEY=your-53-char-key

# Or via .env file (recommended for contentfte)
# .env file:
# GEMINI_API_KEY=your-53-char-key
# GFR_PLAN=free      # or "pro" if you have AI Pro subscription
# GFR_LEARN=1        # auto-learn limits from 429s (highly recommended start)

npx gemini-free-router
```

### Alternative: Start with config file

```bash
# Create router.yaml in your project root
cat > router.yaml << 'EOF'
project: contentfte
listen:
  host: 127.0.0.1
  port: 8787
gemini:
  base_url: https://generativelanguage.googleapis.com/v1beta
  api_key_env: GEMINI_API_KEY
fleet_mode: merge
plan: free
disabled: []
pacing:
  max_queue_wait_s: 30
  burn_curve: even
  max_in_flight_per_model: auto
fallback:
  strategy: remaining-budget
learning:
  auto_apply: false
modalities: [chat]
ledger_path: ./data/ledger.sqlite
dry_run: false
EOF

npx gemini-free-router --config router.yaml
```

## Step 3: Configure Your contentfte Code

In your contentfte blog generation code, modify the OpenAI client setup:

```python
# Example: contentfte/blog_generator.py

from openai import OpenAI

# Router is running at http://127.0.0.1:8787
client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="router",  # any string; router ignores it
)

def generate_blog(topic, **kwargs):
    """Generate an SEO blog using the router."""
    response = client.chat.completions.create(
        model="auto",  # router picks best available model from your fleet
        messages=[
            {"role": "system", "content": "You are a knowledgeable SEO writer."},
            {"role": "user", "content": f"Write a blog about {topic}. Optimize for search engines."}
        ],
        temperature=0.7,
        **kwargs,
    )
    return response.choices[0].message.content

# Usage
blog = generate_blog("sustainable farming practices")
print(f"Generated {len(blog)} chars of blog content")
```

## Step 4: Monitor & Maintain

### Admin Dashboard

The router provides an admin endpoint at `http://127.0.0.1:8787/admin`:

- **JSON**: `Accept: */*` or `curl http://127.0.0.1:8787/admin`
- **HTML**: `Accept: text/html` (auto-refreshes every 30s)

Key metrics:
- `plan`: `free` or `pro`
- `fleet_mode`: `merge` or `replace`
- Per-model remaining RPM/RPD/TPM
- PT reset time (midnight Pacific)
- Learned limits (from 429 forensics)
- Quality signals (success rate, latency EMA)

### Environment Variable Recommendations for contentfte

```bash
# .env file in contentfte project root
GEMINI_API_KEY=your-key
GFR_PLAN=free           # or "pro" if you have AI Pro subscription
GFR_LEARN=1           # auto-learn from 429s (recommended start)
GFR_LOG=warn          # production log level
GFR_POOL_CONNECTIONS=8  # tune based on your concurrency needs
```

### Step 4: Content Generation Patterns

#### Basic Blog Generation

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="router",
)

# "auto" lets the router select the best model from your fleet
response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Write a 1500-word SEO blog about climate change solutions"}],
    temperature=0.7,
)

content = response.choices[0].message.content
tokens_used = response.usage.total_tokens
```

#### Batch Generation (multiple blogs)

```python
import concurrent.futures

def gen_blog(topic):
    client = OpenAI(
        base_url="http://127.0.0.1:8787/v1",
        api_key="router",
    )
    response = client.chat.completions.create(
        model="auto",
        messages=[{"role": "user", "content": f"Write a blog about {topic}"}],
        temperature=0.7,
    )
    return response.choices[0].message.content

topics = ["solar energy", "urban gardening", "zero waste living"]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    blogs = list(executor.map(gen_blog, topics))
```

#### Streaming Responses

```python
response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me about AI trends 2026"}],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## Step 5: Production Considerations

### 1. Router as a Service

For production contentfte deployments, consider running the router as a persistent service:

```bash
# Using PM2 (process manager)
npm i -g pm2
pm2 start npx --name "gfr" -- "gemini-free-router" \
  -e GEMINI_API_KEY=your-key \
  -e GFR_PLAN=pro \
  -e GFR_LEARN=1

# View logs
pm2 logs gfr
```

### 2. High Availability

- Run a single router instance (quotas are per project, not per instance)
- Behind a load balancer only if you have multiple projects sharing the same Gemini key
- Monitor `/admin` for quota signals and learned limits

### 3. Scaling Considerations

- The router is single-threaded for quota scheduling (this is by design — it prevents over-running quotas)
- Concurrent upstream calls are managed by the Node.js fetch pool (`GFR_POOL_CONNECTIONS`)
- If you need higher throughput, increase `GFR_POOL_CONNECTIONS` and `GFR_POOL_KEEPALIVE_MS`
- The router's internal queue is bounded by `pacing.max_queue_wait_s` (default 30s)

### 4. Contentfte-Specific Tips

#### a) Blog Topic Rotation
```python
TOPICS = [
    "AI in healthcare",
    " sustainable farming", 
    "remote work productivity",
    "digital marketing trends",
    "content marketing ROI"
]

for topic in TOPICS:
    blog = generate_blog(topic)
    # Save to your contentfte CMS
```

#### b) Seasonal Content
```python
import calendar
import datetime

# Generate seasonal content
month = datetime.datetime.now().month
themes = {
    1: "New Year resolutions",
    2: "Valentine's Day strategies",
    # ... etc
}
```

#### c) Evergreen Content Series
```python
EVERGREEN_TOPICS = [
    "How to succeed in business",
    "Essential productivity habits",
    "Understanding SEO fundamentals",
]

for topic in EVERGREEN_TOPICS:
    blog = generate_blog(topic)
    # Evergreen content stays relevant; re-use across years
```

#### c) A/B Testing Content
```python
def test_blog_titles(topic, variations):
    results = []
    for title in variations:
        response = client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": f"Write a blog about {topic} with title: {title}"}],
        )
        results.append({
            "title": title,
            "content": response.choices[0].message.content,
            "tokens": response.usage.total_tokens,
        })
    return results

# Test which title generates the best engagement
variations = ["beginner's guide", "ultimate guide", "step-by-step tutorial"]
results = test_blog_titles("remote work", variations)
```

## Step 6: Scaling to Multiple Blogs

If your contentfte agent generates multiple blogs per day:

```python
DAILY_BLOG_QUOTA = 20  # max blogs per day per your Gemini quota

def daily_blog_cycle():
    """Generate up to DAILY_BLOG_QUOTA blogs, respecting quota."""
    generated = 0
    while generated < DAILY_BLOG_QUOTA:
        try:
            blog = generate_blog(generate_random_topic())
            save_blog(blog)
            generated += 1
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                # Quota exhausted for the day - stop
                break
            raise
```

## Step 7: Decommissioning

When you no longer need the router:

```bash
# Stop the process (Ctrl+C if running in foreground)
# Or if using PM2:
pm2 delete gfr

# Clean up
rm -rf data/ledger.sqlite
rm -f router.yaml .env
```

## Frequently Asked Questions (contentfte-specific)

**Q:** *Can I use the router with multiple contentfte projects?*  
**A:** The router is designed for **one Gemini key / one project**. If you have multiple contentfte projects, each needs its own router instance with its own API key.

**Q:** *What if my blog generation hits the daily quota limit?*  
**A:** The router will return 429s once your quota is exhausted. Set `GFR_LEARN=1` to learn your actual limits, then adjust your daily blog target accordingly.

**Q:** *Can I switch between free and Pro plans mid-stream?*  
**A:** Change `GFR_PLAN` env variable and restart the router. The forensics learner will converge to the new plan's limits.

**Q:** *How do I back up my learned limits?*  
**A:** The ledger SQLite database at `./data/ledger.sqlite` contains all learned limits. Back up this file if you want to preserve settings across router restarts or across machines.

## Next Steps

1. **Start the router** with your Gemini key
2. **Update your contentfte code** to use `model: auto` and the router base URL
3. **Monitor `/admin`** to see learned limits and quota status
4. **Set `GFR_LEARN=1`** initially, then decide whether to keep it on
5. **Adjust `plan: free|pro`** based on your Google AI subscription status
6. **Review the troubleshooting table** if you encounter issues

## Version History

- **v0.2.0** (current): Added plan modes (free/pro), 404 dead-model breaker, gap_ms logging, embeddings acquire gate, window_wait_ms in rejected payload
- **v0.1.0**: Initial release with RPM/RPD/TPM scheduling, 5xx failover, basic 429 forensics

---

*Integration guide for contentfte SEO Blog Agent — gemini-free-router v0.2.0*