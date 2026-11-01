// Pure logic for the cross-tab instance guard (plan CON-03).
//
// The active engine instance is a single browser cookie, resolved at call time.
// Open instance A in one tab, switch to B in another, then click "Publish" in the
// stale A tab: the action ran against B (and article ids collide across instances).
// Every submitted form now carries the instance its tab was RENDERED against
// (`_instance`, stamped by components/instance-stamp.tsx) and the server action
// refuses to run when that no longer matches the cookie.

export const INSTANCE_FIELD = "_instance";

/** An error message when the form was rendered for a different instance than the cookie now selects; else null. */
export function instanceMismatchMessage(claimed: string | null | undefined, current: string): string | null {
  const c = (claimed ?? "").trim();
  if (!c) return null; // unstamped (non-browser caller / form rendered before this shipped): allow
  if (c === current) return null;
  return (
    `This page was showing instance '${c}', but the console is now on '${current}' ` +
    `(you switched in another tab). Nothing was changed — reload and try again.`
  );
}
