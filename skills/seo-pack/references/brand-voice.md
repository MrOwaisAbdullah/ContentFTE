# Brand Voice

## Brand DNA profile
Per site, a versioned profile containing:
- **Tone sliders:** formal↔casual, terse↔expansive, playful↔serious.
- **Reading level:** target grade (e.g. 8th) — enforced, not suggested.
- **Signature phrases:** 5–10 phrases the brand actually uses.
- **Banned phrases:** AI-tell clichés and off-brand wording, explicitly listed.
- **POV:** first-person plural? expert guide? peer? Pick one and hold it.

## Learn from samples
- Build the profile from **5–10 existing posts** (or client-provided samples). Extract patterns; don't invent a voice from a questionnaire.
- **Why:** Real voice lives in the archive, not in adjectives the client chose.

## Versioned per site
- One profile per site, versioned. Voice changes go through a diff, not a silent edit.
- **Why:** Multi-client engines need voice isolation — Client A's slang must never leak into Client B.

## Injected into every agent
- The profile is system-prompt-level context for brief, draft, eval, and image-prompt agents.
- **Why:** See eval-gates: optional voice = drifted voice.

## Blind-distinguishability test
- **Test:** strip branding from three drafts; the client should identify theirs.
- **Why:** If the voice isn't recognizable blind, it's generic — fail the voice sub-score.
