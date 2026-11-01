// In-memory failed-login limiter (plan SEC-10). Pure and clock-injectable so it
// is unit-testable. State is per server process — enough to stop online
// guessing against a single console; put a shared store behind it if the
// console is ever scaled horizontally.

export interface LimiterOptions {
  /** failures allowed inside the window before the key is blocked */
  max: number;
  windowMs: number;
}

export interface LimiterStatus {
  blocked: boolean;
  retryAfterMs: number;
  remaining: number;
}

export function createLimiter({ max, windowMs }: LimiterOptions) {
  const hits = new Map<string, number[]>();

  const live = (key: string, now: number): number[] => {
    const fresh = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
    if (fresh.length) hits.set(key, fresh);
    else hits.delete(key);
    return fresh;
  };

  return {
    status(key: string, now = Date.now()): LimiterStatus {
      const fresh = live(key, now);
      if (fresh.length >= max) {
        return { blocked: true, retryAfterMs: windowMs - (now - fresh[0]), remaining: 0 };
      }
      return { blocked: false, retryAfterMs: 0, remaining: max - fresh.length };
    },
    fail(key: string, now = Date.now()): void {
      const fresh = live(key, now);
      fresh.push(now);
      hits.set(key, fresh);
      // keep the map bounded if someone sprays unique keys
      if (hits.size > 5000) hits.delete(hits.keys().next().value as string);
    },
    reset(key: string): void {
      hits.delete(key);
    },
  };
}
