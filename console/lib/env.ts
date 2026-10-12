/** Server-side environment for the console. Never import from client code. */

export function engineBaseUrl(): string {
  return (process.env.ENGINE_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function engineApiKey(): string {
  return process.env.ENGINE_API_KEY || "";
}

export function operatorPassword(): string {
  const pw = process.env.OPERATOR_PASSWORD || "";
  if (!pw) throw new Error("OPERATOR_PASSWORD is not set (console/.env)");
  return pw;
}

export function sessionSecret(): string {
  const secret = process.env.SESSION_SECRET || "";
  if (!secret) throw new Error("SESSION_SECRET is not set (console/.env)");
  return secret;
}
