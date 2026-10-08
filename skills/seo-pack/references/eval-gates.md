# Eval Gates

## The 90+ gate
- Nothing publishes below **90/100**. Sub-scores: accuracy, depth, SEO, voice, originality, **citability**.
- **Hard rule:** no article publishes if **any sub-score < 80**, even when the overall score is 90+.
- **Zero P0 issues** (broken links, false claims, missing schema) — P0s block regardless of score.

## Falsifiable guidance
- Every critic recommendation must carry: (a) the observation it rests on, (b) **"how would we know this failed?"**, (c) a leading indicator to watch.
- **Why:** Vague feedback ("make it more engaging") is unactionable. Falsifiable feedback tells the revision agent exactly what to change and how to verify it.
- **Rule:** Guidance without a fail-check is rejected and regenerated.

## Fact-check BEFORE eval
- Fact-checking is a **discrete gate before** the frontier eval: extract every stat/claim → verify against cited sources → fix or cut.
- **Why:** The critic should never waste tokens scoring unverified claims. Draft → fact-check → eval, in that order.

## Brand files auto-loaded
- Brand DNA is injected at the **system-prompt level** for brief, draft, eval, and image-prompt agents — never an optional parameter.
- **Why:** Voice drift happens when voice is "available" but not mandatory.

## Revision loop
- Eval → revision → re-eval, up to **3 iterations**. Below 90 after 3 rounds: escalate to human, don't publish.
- Log every run: model IDs, costs, scores, revision count, publish decision.
