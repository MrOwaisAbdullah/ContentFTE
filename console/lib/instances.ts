import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";
import { cookies } from "next/headers";
import { engineApiKey, engineBaseUrl } from "./env";

/** One manageable engine instance (own process + own DB). */
export interface ConsoleInstance {
  name: string;
  baseUrl: string;
  apiKey?: string;
  /** env = declared in CONSOLE_INSTANCES/ENGINE_* (read-only here);
   *  file = managed from the UI via instances.json (editable/removable). */
  origin: "env" | "file";
}

const COOKIE = "console_instance";
const MAX_AGE_S = 60 * 60 * 24 * 7;

function filePath(): string {
  // cwd = console/ when started from `npm run dev/start` there.
  return path.join(process.cwd(), "instances.json");
}

async function fileInstances(): Promise<ConsoleInstance[]> {
  try {
    const raw = await fs.readFile(filePath(), "utf8");
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((p) => ({
        name: String((p as { name?: string }).name || "").trim(),
        baseUrl: String((p as { baseUrl?: string }).baseUrl || "").replace(/\/+$/, ""),
        apiKey: (p as { apiKey?: string }).apiKey
          ? String((p as { apiKey?: string }).apiKey)
          : "",
        origin: "file" as const,
      }))
      .filter((x) => x.name && x.baseUrl);
  } catch {
    return []; // missing or corrupt file == no UI-managed instances
  }
}

async function writeFileInstances(items: ConsoleInstance[]): Promise<void> {
  const slim = items
    .filter((x) => x.origin === "file")
    .map(({ name, baseUrl, apiKey }) => ({ name, baseUrl, apiKey }));
  await fs.writeFile(filePath(), `${JSON.stringify(slim, null, 2)}\n`, "utf8");
}

function envInstances(): ConsoleInstance[] {
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
            origin: "env" as const,
          }))
          .filter((x) => x.name && x.baseUrl);
        if (items.length > 0) return items;
      }
    } catch {
      // bad JSON -> fall through to the ENGINE_* default
    }
  }
  return [{ name: "default", baseUrl: engineBaseUrl(), apiKey: engineApiKey(), origin: "env" }];
}

/** env-declared entries first (read-only), then UI-managed file entries;
 *  env wins on a name collision. */
export async function registry(): Promise<ConsoleInstance[]> {
  const env = envInstances();
  const file = await fileInstances();
  const envNames = new Set(env.map((x) => x.name));
  return [...env, ...file.filter((x) => !envNames.has(x.name))];
}

export async function saveInstance(entry: {
  name: string;
  baseUrl: string;
  apiKey?: string;
}): Promise<void> {
  const name = entry.name.trim();
  const baseUrl = entry.baseUrl.trim().replace(/\/+$/, "");
  if (!name || !baseUrl) throw new Error("name and baseUrl are required");
  const env = envInstances();
  if (env.some((x) => x.name === name)) {
    throw new Error(`"${name}" is declared in CONSOLE_INSTANCES/ENGINE_* (env) — edit the env instead`);
  }
  const file = await fileInstances();
  const idx = file.findIndex((x) => x.name === name);
  const next: ConsoleInstance = { name, baseUrl, apiKey: entry.apiKey || "", origin: "file" };
  if (idx >= 0) file[idx] = next;
  else file.push(next);
  await writeFileInstances(file);
}

export async function removeInstance(name: string): Promise<boolean> {
  if (envInstances().some((x) => x.name === name)) {
    throw new Error(`"${name}" is declared in env — remove it from CONSOLE_INSTANCES instead`);
  }
  const file = await fileInstances();
  const next = file.filter((x) => x.name !== name);
  if (next.length === file.length) return false;
  await writeFileInstances(next);
  return true;
}

export async function currentInstance(): Promise<ConsoleInstance> {
  const reg = await registry();
  const store = await cookies();
  const name = store.get(COOKIE)?.value;
  return reg.find((x) => x.name === name) || reg[0];
}

export async function setCurrentInstance(name: string): Promise<boolean> {
  const reg = await registry();
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
