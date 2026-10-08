# Agent Readiness

The site must be consumable by crawlers, LLMs, and autonomous agents — not just human browsers.

## llms.txt
- Per-site `llms.txt` at root: what the site is, what it offers, key pages, contact/structured facts.
- **Why:** The emerging standard LLMs check for site context.

## Markdown alternates
- Publish a `.md` version of every article at a predictable URL (e.g. `/blog/slug.md`).
- **Why:** Agents and LLMs prefer clean markdown over parsed HTML. Cheap to generate, nobody does it yet.

## Image provenance
- Write IPTC `TrainedAlgorithmicMedia` tags on every AI-generated image.
  - XMP attribute: `Iptc4xmpExt:DigitalSourceType =
    http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`
    (IPTC's own guidance for synthetic media). Carried in a JPEG APP1 XMP
    segment or a PNG `iTXt` ("XML:com.adobe.xmp") chunk.
  - **Why:** Forward-looking provenance signal as engines start handling AI imagery distinctly. Zero cost at generation time.
  - **ContentFTE wiring:** `lib/image_provenance.tag_trained_algorithmic_media`
    runs on every Klein output.

## WebMCP readiness
- Expose key site actions/content via WebMCP-compatible endpoints where the platform supports it.
- **Why:** Lets AI agents interact with the site, not just read it.

## Lighthouse Agentic Browsing checks
- Run the agentic-browsing category checks: can an agent navigate, extract, and act on the page?
- **Why:** Scores the site the way agent-driven traffic will experience it.

## Structured data
- Article + FAQPage JSON-LD on every post. Entity `sameAs` links (Wikidata, Wikipedia, official profiles) on about/service pages.
- **Why:** Schema is how machines confirm what the page is; sameAs anchors the entity in the Knowledge Graph.
