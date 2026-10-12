import "server-only";
import { cookies } from "next/headers";
import { engineApiKey, engineBaseUrl } from "./env";

/** One manageable engine instance (own process + own DB). */
export interface ConsoleInstance {
  name: string;
  baseUrl: string;
  apiKey?: string;
}

const COOKIE = "console_instance";
const MAX_AGE_S = 60 * 60 * 24 * 7;

/** CONSOLE_INSTANCES env (JSON array) or the single ENGINE_* default. */
export function registry(): ConsoleInstance[] {
  const raw = (process.env.CONSOLE_INSTANCES || "").trim();
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        const items = parsed
          .map((p, i) => ({
            name: String((p as { name?: string }).name || `instance-${i + 1}`),
            baseUrl: String((p as { baseUrl?: string }).baseUrl || "").replace(/\/+$/, ""),
            apiKey: (p as { apiKey?: string }).apiKey
              ? String((p as { apiKey?: string }).apiKey)
              : "",
          }))
          .filter((x) => x.name && x.baseUrl);
        if (items.length > 0) return items;
      }
    } catch {
      // bad JSON -> fall through to the default registry
    }
  }
  return [{ name: "default", baseUrl: engineBaseUrl(), apiKey: engineApiKey() }];
}

export async function currentInstance(): Promise<ConsoleInstance> {
  const reg = registry();
  const store = await cookies();
  const name = store.get(COOKIE)?.value;
  return reg.find((x) => x.name === name) || reg[0];
}

export async function setCurrentInstance(name: string): Promise<boolean> {
  const reg = registry();
  if (!reg.some((x) => x.name === name)) return false;
  const store = await cookies();
  store.set(COOKIE, name, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE_S,
  });
  return true;
}
