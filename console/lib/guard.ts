import "server-only";
import { redirect } from "./flash-redirect";
import { currentInstance } from "./instances";
import { INSTANCE_FIELD, instanceMismatchMessage } from "./instance-guard";
import { requireSession } from "./session";

/**
 * Entry check for every mutating server action: a valid operator session AND the
 * form still targeting the instance the console is on (plan CON-03). Server
 * actions are public POST endpoints, so the session check can't be skipped.
 */
export async function requireOperator(formData: FormData, returnTo = "/"): Promise<void> {
  await requireSession();
  const current = await currentInstance();
  const problem = instanceMismatchMessage(String(formData.get(INSTANCE_FIELD) ?? ""), current.name);
  if (problem) redirect(`${returnTo}?err=${encodeURIComponent(problem)}`);
}
