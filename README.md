# ContentFTE — Autonomous AI Content Employee (Digital FTE)

[![Part of FTE Suite](https://img.shields.io/badge/Fleet-Digital%20FTE%20Suite-blueviolet.svg)](https://github.com/MrOwaisAbdullah/Digital-FTE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12+-blue.svg?logo=python)](https://python.org)
[![Publishing: Sanity CMS](https://img.shields.io/badge/CMS-Sanity.io-red.svg?logo=sanity)](https://sanity.io)
[![Adapters: WordPress | Shopify | Wix](https://img.shields.io/badge/Adapters-WordPress%20%7C%20Shopify%20%7C%20Wix-green.svg)](https://github.com/MrOwaisAbdullah/ContentFTE)
[![Gateways: Discord | Telegram | WhatsApp](https://img.shields.io/badge/Gateways-Discord%20%7C%20Telegram%20%7C%20WhatsApp-5865F2.svg)](https://github.com/MrOwaisAbdullah/ContentFTE)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-orange.svg)](./LICENSE)
[![npm: content-fte](https://img.shields.io/npm/v/content-fte.svg?logo=npm&label=npm)](https://www.npmjs.com/package/content-fte)

> **Autonomous multi-agent Digital FTE that researches, writes, and publishes 15–17 SEO-optimized articles daily. Directly pushes to Sanity CMS with extensible adapters for WordPress, Shopify, Wix, and Headless CMS platforms, integrated with Discord, Telegram, and WhatsApp gateways for real-time notifications and approvals.**

---

## Overview

**ContentFTE** is an autonomous content engine designed to eliminate manual content production bottlenecks. Powered by a multi-agent orchestration pipeline (using the OpenAI Agents SDK and Google Gemini / OpenRouter fallbacks), the system performs deep search intent analysis, keyword discovery, content brief structuring, high-authority article generation, image generation, and automated multi-platform publishing.

While natively configured to publish rich portable text directly to **Sanity CMS**, ContentFTE features a modular adapter architecture allowing seamless publication to **WordPress, Shopify, Wix, custom Webhooks, and any headless CMS**.

---

## 🌐 Multi-Platform CMS Adapters

ContentFTE separates content generation from publishing targets via a pluggable adapter layer:

| Target Platform | Integration Method | Status | Capabilities |
| :--- | :--- | :---: | :--- |
| **Sanity CMS** | Sanity REST API / Client | ✅ Active | Rich Portable Text, Authors, Categories, Slugs, Assets |
| **WordPress** | WP REST API (`/wp/v2/posts`) | ✅ Active | Gutenberg-block body, featured + in-post images, categories/tags, Yoast / Rank Math / AIOSEO meta, Article + FAQPage JSON-LD, FAQ accordion; optional native **Elementor** layout |
| **Shopify Blogs** | Shopify Admin REST / GraphQL | 🔌 Pluggable | Article publishing, Blog tags, Authors, SEO handle |
| **Wix & Webflow** | Wix REST API & Webflow CMS | 🔌 Pluggable | Automated item creation, Collection binding |
| **Custom Headless** | Webhook / JSON Payload | ✅ Active | Unified `/content` payload (SDK pull) + webhook push for Next.js, Nuxt, Astro, or custom backends |

---

## 🧰 SDK & Integration Layers

Phase 1 adds an **API → SDK → MCP** stack on top of the engine so your own
frontend, a script, or an AI agent can drive the pipeline:

| Layer | What it is |
| :--- | :--- |
| **REST API** (`/sdk/v1/*`) | Canonical service ops — sites, briefs, articles, generate, gate/approve, publish, WordPress/Elementor build |
| **MCP server** (`/mcp`) | `contentfte_*` tools (`list_sites`, `get_brief`, `generate_article`, `get_article_status`, `get_image`, `publish_article`, `site_health`, `elementor_*`) for Claude Code or any MCP client |
| **npm package** | [`content-fte`](https://www.npmjs.com/package/content-fte) — typed TS/JS client + React renderer that turns the unified `/content` payload into a fully SEO'd page (GFM, heading anchors, FAQ accordion, Article + FAQPage JSON-LD) |
| **Python client** | `sdk/python_client.py` for scripts and scheduled jobs |

```bash
npm install content-fte
```

```tsx
import { ContentFTEClient } from "content-fte";
import { ContentFTEArticle } from "content-fte/renderer";
import "content-fte/contentfte-prose.css";

const client = new ContentFTEClient(process.env.CONTENTFTE_URL!, process.env.CONTENTFTE_SITE_KEY!);
const payload = await client.getContent(articleId);
```

Every publish is **gated**: an article must clear the quality gate and be
approved before `publish_article` moves it to published. The WordPress push runs
inside that same call (body, meta, schema, images, categories) and stays
**fail-open** — an outage reports `wp.ok=false` rather than losing the article.

See `docs/site-onboarding-flow.md` for the step-by-step **WordPress** and
**custom React/Astro** onboarding + publishing flows, `sdk/quickstart.md` for
frontend patterns, and `docs/phase1-feature-map.md` for the full surface.

> **AI agents:** `skills/contentfte/SKILL.md` is a public skill that teaches an
> agent to install the SDK and implement it correctly for the user's stack
> (Next.js/React, Astro, Vue/Nuxt, Svelte, plain HTML, WordPress, or MCP).

---

## 📲 Omnichannel Notification & Control Gateways

Keep humans in the loop or receive instant live updates via your preferred messaging channels:

- 🎮 **Discord Gateway**: Automated webhook and bot alerts with rich embeds whenever an article is drafted, queued, or published.
- ✈️ **Telegram Gateway**: Bot integration sending instant post summaries, direct preview links, and approval buttons.
- 💬 **WhatsApp Gateway**: Business API / webhook notifications for instant publishing alerts and remote workflow triggers.

## System Architecture

The system consists of multiple agents working together:

1. **Triage Agent** - Selects keywords or YouTube URLs for research
2. **Research Agent** - Conducts keyword research using Tavily API
3. **Brief Agent** - Creates content briefs from research findings
4. **Content Generator Agent** - Generates SEO-optimized blog posts
5. **Image Selection Agent** - Builds and QA-checks the thumbnail (see below)
6. **Posting Agent** - Publishes content to Sanity CMS
7. **Repurposing Agent** - Repurposes content for other platforms (planned)

### Thumbnail Generation & QA

Every post gets a thumbnail from Cloudflare Workers AI (genuinely free tier,
10,000 Neurons/day) rather than a stock photo, using the site's fixed house
cinematic-3D prompt — the agent never writes the prompt itself, it only supplies
the title, the SEO summary, and an optional one-sentence scene concept.

Generation is a **generate → look → revise** loop, not a single shot:

1. `_image_plan(attempt)` picks the model *and* the typography for this attempt.
   With `IMAGE_ROUTER` on (the default) attempt 1 uses the cheap model
   (`@cf/black-forest-labs/flux-2-klein-4b`, ~110 Neurons per 1280×720 image,
   overridable with `CLOUDFLARE_IMAGE_MODEL`) with **zero on-image text** — it
   garbles baked-in words, so the cheapest pass never asks for any. Only if it
   fails QA does attempt 2+ escalate to `IMAGE_TEXT_MODEL`
   (`flux-2-klein-9b`, ~1,364 Neurons) with a headline. `IMAGE_ROUTER=0` pins
   every attempt to `CLOUDFLARE_IMAGE_MODEL` with a headline.
2. `_build_house_prompt()` fills the title/summary/scene-concept slots of the
   house template and appends a closing rule: *no text at all* on the cheap
   pass, *one short headline and no watermark* on the text pass.
3. `lib/image_vision.py` sends the actual pixels to a VLM (`gemini-3.5-flash-lite`)
   which returns a description, the on-image text it can read, style notes, and
   issues — the image is never judged from its filename.
4. Jev turns that into a decision: `matches_blog` and `matches_style` must both
   clear their thresholds (0.65 / 0.6) to pass. Jev is **fail-open** — if the
   decision service is down the image is accepted rather than blocking a post.
5. On a miss, the image is regenerated with the failed attempt attached as an
   img2img reference and the VLM's specific complaints written into the prompt —
   up to `IMAGE_MAX_REVISIONS` (default 3) attempts. The best-scoring attempt is
   always returned; a non-passing QA is reported, not raised. A router step that
   produces no image (Workers AI's flaky content-moderation flag, a rate limit)
   is retried once and then skipped rather than ending the loop, so a later step
   still gets its turn.

Pexels is only reached if Cloudflare is unset or every attempt fails.

### Model routing

All agents run through `FallbackAgentRunner`, which tries models in a
performance-sorted chain and records every attempt. Two properties matter for
reliability on the free tier:

- **Each Gemini model has its own independent daily quota** — Lite variants are
  500 RPD / 15 RPM, Flash variants 20 RPD / 5 RPM — so they are separate entries
  in the chain rather than one shared bucket.
- **Usage is counted per attempt, not per success.** Counting only successes made
  a quota-exhausted model look available all day; now a model that Google is
  rejecting exhausts its local budget and the chain moves on.

The chain leads with `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite` (measured
9.34% error across 851 logged runs) and puts `gemini-flash-latest` (87.95%
error) later.

### Logging

Two worksheets answer "what actually happened" after the fact:

- **`model_usage_log`** — one row per LLM attempt: `Timestamp, Model, Agent,
  Stage, Status, Latency (s)`.
- **`image_logs`** — one row per image call: `Timestamp, Model, Stage, Subject,
  Status, Reference, Latency (s), Detail`. `Stage=generate` covers every
  Cloudflare attempt (`Reference=yes` marks img2img revisions), `Stage=stock`
  covers Pexels fallbacks, and one `Stage=result` row per call carries the
  VLM/Jev verdict and attempts used. Created automatically on first write.

## Prerequisites

- Python 3.8+
- Google Cloud Platform account (for Google Sheets API)
- Sanity CMS account
- API keys for various services (see Environment Variables section)
- Google Service Account credentials (JSON format)

## Environment Variables

Create a `.env` file in the root directory with the following variables:

```env
# LLM API Keys
GEMINI_API_KEY=your_gemini_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
OPENAI_API_KEY=your_openai_api_key

# Sanity CMS Configuration
SANITY_PROJECT_ID=your_sanity_project_id
SANITY_API_TOKEN=your_sanity_api_token
SANITY_DATASET=production
SANITY_DEFAULT_AUTHOR_ID=your_author_document_id
SANITY_DEFAULT_AUTHOR_NAME="Your Author Name"

# Google Sheets Credentials
GOOGLE_CREDENTIALS={"type":"service_account","project_id":"your_project","private_key_id":"your_key_id","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"your_service_account_email","client_id":"your_client_id","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"your_cert_url"}

# Search and Research API Keys
TAVILY_API_KEY=your_tavily_api_key
SERPAPI_KEY=your_serpapi_key

# Image API Keys
PEXELS_API_KEY=your_pexels_api_key
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
CLOUDFLARE_API_TOKEN=your_cloudflare_workers_ai_token

# Optional: Image generation knobs
CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-2-klein-4b
IMAGE_TEXT_MODEL=@cf/black-forest-labs/flux-2-klein-9b
IMAGE_ROUTER=1
IMAGE_MAX_REVISIONS=3

# Security
API_KEY=your_custom_api_key_for_authentication

# Optional: Override default model settings
DEFAULT_MODEL=gemini-2.5-flash
```

### Required Environment Variables Breakdown

#### LLM API Keys
- `GEMINI_API_KEY` - Google Gemini API key for primary LLM
- `OPENROUTER_API_KEY` - OpenRouter API key for fallback LLMs
- `OPENAI_API_KEY` - OpenAI API key for fallback LLMs

#### Sanity CMS Configuration
- `SANITY_PROJECT_ID` - Your Sanity project ID
- `SANITY_API_TOKEN` - API token with write permissions
- `SANITY_DATASET` - Dataset name (usually "production")
- `SANITY_DEFAULT_AUTHOR_ID` - Document ID of the author to attribute posts to
- `SANITY_DEFAULT_AUTHOR_NAME` - Name of the default author

#### Google Sheets Credentials
- `GOOGLE_CREDENTIALS` - JSON string of Google Service Account credentials (contents of your service account key file)
  
  _Note: This should contain the entire JSON content from your Google Service Account key file, not a file path. The service account key file (e.g., `contentfte-service-account-key.json`) should be kept secure and never committed to version control._

#### Search and Research API Keys
- `TAVILY_API_KEY` - Tavily API key for web search and research
- `SERPAPI_KEY` - SerpAPI key for search data (fallback)

#### Image API Keys
- `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` - Cloudflare Workers AI for AI image generation (primary; genuinely free, 10,000 Neurons/day)
- `PEXELS_API_KEY` - Pexels API key for stock images (fallback)

#### Image Generation Knobs (optional)
- `CLOUDFLARE_IMAGE_MODEL` - Which Workers AI model makes the thumbnail. Defaults to `@cf/black-forest-labs/flux-2-klein-4b` (~110 Neurons → ~90 images/day, and it accepts an img2img reference, which the revision loop needs). Swap to `.../flux-2-klein-9b` for legible on-image text (~7/day) or `.../flux-2-dev` for highest quality (~3/day).
- `IMAGE_TEXT_MODEL` - The text-capable model the router escalates to. Defaults to `@cf/black-forest-labs/flux-2-klein-9b` (~1,364 Neurons), which spells baked-in headlines correctly where klein-4b does not (3/3 live tests: `SPEC-DRIFIEN` / `SPEC-DRITEN` / `SPEC-DRVIEN`).
- `IMAGE_ROUTER` - `1` (default) runs attempt 1 on `CLOUDFLARE_IMAGE_MODEL` with no on-image text and only escalates to `IMAGE_TEXT_MODEL` with a headline if QA fails — so a typical post costs ~110 Neurons, not ~1,364. `0` disables routing and sends every attempt to `CLOUDFLARE_IMAGE_MODEL` with a headline.
- `IMAGE_MAX_REVISIONS` - Max generate → validate → regenerate cycles per post before the best attempt is accepted (default `3`, bounding worst-case spend at ~2,838 Neurons with the router on).

#### Security
- `API_KEY` - Custom API key for authenticating requests to the agent API

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd ContentFTE
   ```

2. **Install dependencies (this project uses [uv](https://docs.astral.sh/uv/), not pip):**
   ```bash
   uv sync
   ```
   This creates and manages `.venv` automatically from `pyproject.toml`/`uv.lock` —
   no separate manual venv step needed. Run project commands via `uv run ...`
   (e.g. `uv run uvicorn main:app --reload`) or activate `.venv` directly.

3. **Create `.env` file:**
   Copy `.env.example` to `.env` and fill in your actual values (see
   `docs/service_setup.md` for where to get each credential).

## Setup Instructions

### 1. Google Sheets Setup

1. Create **two** Google Sheets (titles are hardcoded in `tools/sheet_tool.py`):

   - **`ContentSpark_Keywords`** — a standalone spreadsheet whose first sheet is
     the input queue, with headers `Keyword` (A) and `Status` (B). Rows are
     `available` until claimed, then flipped to `used`.
   - **`ContentSpark`** — the pipeline's database, with these worksheets:

     | Worksheet | Written by | Notes |
     | --- | --- | --- |
     | `research_data` | Research Agent | |
     | `content_briefs` | Brief Agent | |
     | `generated_posts` | Content Generator | `Created At` and `Image Source` columns are appended automatically at the end |
     | `approved_unpublished` | **you** | A live `FILTER` view over `generated_posts` — see `docs/service_setup.md` |
     | `published_posts` | Posting Agent | |
     | `claims_audit` | Claims gate | |
     | `review_feedback_log` | Review stages | |
     | `model_usage_log` | Fallback runner | One row per LLM attempt |
     | `freshness sweep`, `performance` | Review stages | |
     | `image_logs` | Image tools | **Created automatically** on first write — don't create it by hand |

2. Create a Google Cloud Project and enable the Google Sheets API

3. Create a Service Account:
   - Go to Google Cloud Console → IAM & Admin → Service Accounts
   - Create a new service account
   - Download the JSON key file (e.g., `contentfte-service-account-key.json`)
   - Keep this file secure and never commit it to version control

4. Configure Google Sheets Access:
   - Open your Google Sheet
   - Click "Share" button
   - Add the service account email address from your JSON key file as an editor
   - The email will look like: `contentfte-service-account@your-project.iam.gserviceaccount.com`

### 2. Sanity CMS Setup

1. Create a Sanity project at https://sanity.io

2. Deploy the Sanity Studio to manage content

3. Create the required document types (post, author, category) using the provided schema

4. Create at least one author document and note its document ID

5. Obtain an API token with write permissions

### 3. API Keys Setup

Obtain API keys for all the required services and add them to your `.env` file.

### 4. Testing the Setup

1. **Start the API server:**
   ```bash
   uv run uvicorn main:app --reload
   ```
   Note: as of this repo's move to GitHub Actions + Discord for triggering
   (see `docs/service_setup.md`), `main.py` is no longer the active way the
   pipeline runs day-to-day — this is just for local testing of the
   endpoints, which are still present in the code.

2. **Test the health endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```

3. **Test with authentication:**
   ```bash
   curl -H "Authorization: Bearer your_api_key" http://localhost:8000/health
   ```

## API Endpoints

### Health Check
```
GET /health
```
Response: `{"status": "OK", "message": "The server is healthy"}`

### Research Topic
```
GET /research
Headers: Authorization: Bearer <your_api_key>
```
Triggers the research workflow to select a keyword and conduct research.

### Generate Content Brief
```
GET /generate_brief
Headers: Authorization: Bearer <your_api_key>
```
Generates a content brief from approved research findings.

### Generate Content
```
GET /generate_content
Headers: Authorization: Bearer <your_api_key>
```
Creates a blog post from an approved content brief.

### Post Content
```
GET /post_content
Headers: Authorization: Bearer <your_api_key>
```
Publishes an approved blog post to Sanity CMS.

## Workflow

The system follows a multi-step workflow:

1. **Triage** - Selects the next keyword or YouTube URL from the ContentFTE_Keywords sheet
2. **Research** - Conducts research on the selected topic using Tavily API
3. **Brief Creation** - Creates a content brief from research findings
4. **Content Generation** - Generates a full blog post from the brief
5. **Posting** - Publishes the blog post to Sanity CMS
6. **Repurposing** - (Planned) Repurposes content for other platforms

Each step is handled by a dedicated agent with built-in fallback logic across different LLM providers.

## Security Best Practices

1. **Environment Variables**:
   - Never commit `.env` files to version control
   - Use different API keys for development, staging, and production environments
   - Rotate API keys regularly

2. **Google Service Account**:
   - Keep the service account key file (`contentfte-service-account-key.json`) secure
   - Limit the service account's permissions to only what's necessary
   - Use a dedicated service account for this application

3. **Sanity CMS**:
   - Use API tokens with minimal required permissions
   - Rotate tokens regularly
   - Monitor API usage

4. **API Keys**:
   - Enable rate limiting where possible
   - Use API key restrictions (IP whitelisting, referrer restrictions)
   - Monitor usage for unusual activity

5. **Application Security**:
   - Use the `API_KEY` environment variable to protect your endpoints
   - Keep dependencies updated
   - Regularly audit third-party services

## Troubleshooting

### Common Issues

1. **Authentication Errors**
   - Verify your `API_KEY` in the `.env` file
   - Ensure you're using the correct Bearer token format

2. **Google Sheets Access Errors**
   - Check that your service account has access to the spreadsheet
   - Verify the `GOOGLE_CREDENTIALS` JSON is correctly formatted
   - Ensure the sheet names match exactly

3. **Sanity CMS Errors**
   - Verify `SANITY_PROJECT_ID` and `SANITY_API_TOKEN` are correct
   - Check that `SANITY_DEFAULT_AUTHOR_ID` exists in your Sanity project
   - Ensure your Sanity schema matches the expected structure

4. **API Rate Limits**
   - The system includes fallback logic across providers
   - Check the custom runner implementation for quota management

### Logs and Debugging

Enable verbose logging by uncommenting the following line in `blog_agent/blog_agents.py`:
```python
# enable_verbose_stdout_logging()
```

### Environment Verification

Check that all environment variables are loaded correctly:
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); [print(f'{k}: {v[:10]}...') for k, v in os.environ.items() if 'KEY' in k or 'TOKEN' in k or 'API' in k]"
```

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** license — free for personal and non-commercial use with attribution to **Owais Abdullah**. See the [LICENSE](./LICENSE) file for details.