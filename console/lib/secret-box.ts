// Encrypts the engine API keys the console stores in instances.json (SEC-14).
//
// instances.json used to hold every managed engine's key in plaintext, so a backup, a screenshot of the file or
// a read-only file-system leak exposed full access to each engine. With INSTANCES_KEY set the `apiKey` values are
// written as  enc:v1:<iv>.<tag>.<ciphertext>  (AES-256-GCM, random IV per value). Without it nothing changes, and
// a plaintext value is still read, so enabling it needs no migration step - the next save re-writes the file
// encrypted. The key lives in the environment, never next to the file.
//
// Pure (node:crypto only, no next/*) so it runs under node:test.
import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";

const PREFIX = "enc:v1:";
const SALT = "contentfte-console-instances-v1";

function key(material: string): Buffer {
  return scryptSync(material, SALT, 32);
}

export function isSealed(value: string | undefined | null): boolean {
  return typeof value === "string" && value.startsWith(PREFIX);
}

/** Encrypt `plain` if a key is configured; empty values and already-sealed values pass through. */
export function sealSecret(plain: string | undefined, material: string | undefined): string {
  const v = plain ?? "";
  if (!v || !material || isSealed(v)) return v;
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(material), iv);
  const ct = Buffer.concat([cipher.update(v, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${PREFIX}${iv.toString("base64url")}.${tag.toString("base64url")}.${ct.toString("base64url")}`;
}

/** Decrypt a sealed value. Plaintext is returned unchanged; a sealed value that cannot be opened (wrong or
 *  missing key, tampered) yields "" - the instance then simply has no key, it never crashes the console. */
export function openSecret(stored: string | undefined, material: string | undefined): string {
  const v = stored ?? "";
  if (!isSealed(v)) return v;
  if (!material) return "";
  try {
    const [iv, tag, ct] = v.slice(PREFIX.length).split(".");
    const decipher = createDecipheriv("aes-256-gcm", key(material), Buffer.from(iv, "base64url"));
    decipher.setAuthTag(Buffer.from(tag, "base64url"));
    return Buffer.concat([decipher.update(Buffer.from(ct, "base64url")), decipher.final()]).toString("utf8");
  } catch {
    return "";
  }
}
