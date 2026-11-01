/** Server-side environment for the console. Never import from client code. */

export function engineBaseUrl(): string {
  return (process.env.ENGINE_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function engineApiKey(): string {
  return process.env.ENGINE_API_KEY || "";
}

// Values shipped in .env.example. Anyone who has read the repo knows them, so
// a deployment still using one has effectively no login (plan OPS-04 / S6).
const PLACEHOLDERS = new Set(["change-me", "change-me-to-a-long-random-string", "changeme", "password"]);
const MIN_SECRET_LEN = 32;
const warned = new Set<string>();

function weak(name: string, value: string, minLen: number): string | null {
  if (PLACEHOLDERS.has(value.toLowerCase())) return `${name} is still the .env.example placeholder`;
  if (value.length < minLen) return `${name} is shorter than ${minLen} characters`;
  return null;
}

/**
 * Production refuses to run with weak credentials; development only warns
 * (once) so a local `change-me` setup keeps working.
 */
function enforceStrength(name: string, value: string, minLen: number): void {
  const problem = weak(name, value, minLen);
  if (!problem) return;
  if (process.env.NODE_ENV === "production") {
    throw new Error(`${problem}. Set a strong value in the console environment before running in production.`);
  }
  if (!warned.has(name)) {
    warned.add(name);
    console.warn(`[console] WARNING: ${problem}. This is tolerated in development only.`);
  }
}

export function operatorPassword(): string {
  const pw = process.env.OPERATOR_PASSWORD || "";
  if (!pw) throw new Error("OPERATOR_PASSWORD is not set (console/.env)");
  enforceStrength("OPERATOR_PASSWORD", pw, 12);
  return pw;
}

export function sessionSecret(): string {
  const secret = process.env.SESSION_SECRET || "";
  if (!secret) throw new Error("SESSION_SECRET is not set (console/.env)");
  enforceStrength("SESSION_SECRET", secret, MIN_SECRET_LEN);
  return secret;
}
