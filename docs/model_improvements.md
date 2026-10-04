# Model routing, fallback & quota tracking

## Earlier work: fallback logic, error handling, provider management

Here's a summary of the improvements we've made to the fallback logic, error handling, and provider management:

1. **Enhanced Fallback Logic**:
   - Implemented performance-based model selection that sorts providers by success rate and response time
   - Maintains the existing retry mechanism while optimizing the order in which models are tried

2. **Improved Error Handling**:
   - Added categorization of errors as temporary or permanent
   - Temporary errors (rate limits, timeouts) trigger short-term unavailability of providers
   - Permanent errors (invalid API keys, forbidden access) trigger longer unavailability periods
   - This prevents wasting attempts on providers with known issues

3. **Advanced Provider Management**:
   - Added performance tracking for each provider (success rate, response time)
   - Implemented temporary unavailability tracking for providers experiencing issues
   - Rate-limited providers are marked as unavailable for a short period to allow quotas to reset
   - Providers with permanent errors are marked as unavailable for longer periods

4. **Performance Optimization**:
   - Added response time tracking to continuously optimize provider selection
   - Models are now sorted dynamically based on their historical performance
   - This ensures faster and more reliable responses over time

These improvements maintain full backward compatibility with the existing functionality while making the system more robust and efficient. The fallback mechanism is now more intelligent, adapting to provider performance and error patterns to optimize the selection process.

## 2026-10-04: quota-blind retry loop fixed

Analysis of all 851 rows in `model_usage_log` (2026-08-23 → 2026-10-04) showed the
fallback chain was not protecting anything, because the runner was hammering the
single worst model in the pool.

**Measured error rates by model:**

| Model | Error rate | Free quota |
| --- | ---: | --- |
| `gemini-3.5-flash-lite` | **9.34%** (165 ok / 17 fail) | 500 RPD / 15 RPM |
| `gemini-3.1-flash-lite` | low | 500 RPD / 15 RPM |
| `gemini-3.6-flash` | 63.98% | 20 RPD / 5 RPM |
| `gemini-3.5-flash` | 71.26% | 20 RPD / 5 RPM |
| `gemini-flash-latest` | **87.95%** (219 fail / 30 ok) | 20 RPD / 5 RPM |

By stage: Content Generator 80.63% error at 202.4s average, Preparation 70.32%,
Brief 69.29%. Daily error rate sat at 50–75% consistently — not transient outages.

**Root cause — usage was only counted on success.** `run_with_fallback` called
`increment_usage()` inside the success branch only. Every rejected call left both the
RPD counter and the 60-second RPM window untouched, so a model Google was refusing
all day still read `available: true` and was retried first on every subsequent run.
Two fixes:

1. `increment_usage()` now runs **before** `_execute_agent_run`, so an attempt costs
   budget whether or not it succeeds. A failing model now exhausts its local limit
   and the chain moves on instead of looping on it.
2. `LLM_MODELS` reordered so the chain leads with the 500-RPD lite models and puts
   `gemini-flash-latest` near the end. With empty `provider_stats` every model scores
   0, `sorted()` is stable, and `run_with_fallback` overwrites `agent.model` each
   iteration — so **this declaration order is the effective routing order**, and the
   per-agent `model=` argument never decides anything on its own.

**Two new Gemini buckets.** `gemini-3.7-flash` and `gemini-3.8-flash` were added as
separate `LLM_MODELS` entries with their own `model_limits` / `model_rpm_limits`
(20 RPD / 5 RPM each). Each Gemini model has an independent daily quota, so more
entries means more total headroom before the chain has to fall through to paid
DeepSeek or `openrouter/free`.

**Verified** by driving `run_with_fallback` with an always-failing stub: usage
increments on failure, the lite model is tried first, and a model at its RPD ceiling
returns `available = False`.
