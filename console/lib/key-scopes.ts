// Scopes a per-site API key can carry (plan SEC-03). Client-safe on purpose: lib/engine.ts is
// `server-only`, and the key-creation form (a client component) needs this list at runtime.
// `admin` implies every scope, and any scope implies `read`. Keep in step with sdk/keys.py::SCOPES.
export const KEY_SCOPES = ["read", "write", "approve", "publish", "admin"] as const;
export type KeyScope = (typeof KEY_SCOPES)[number];
