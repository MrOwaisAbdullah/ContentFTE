import { requireSession } from "@/lib/session";
import { currentInstance, registry } from "@/lib/instances";
import {
  removeInstanceAction,
  saveInstanceAction,
  switchInstanceAction,
} from "@/actions/instances";
import { Alert, PageHeader } from "@/lib/ui";
import { PendingButton } from "@/lib/interactive";
import {
  ArrowRightLeft,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Cpu,
  KeyRound,
  Link2,
  Plus,
  PlusCircle,
  Radio,
  Server,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const dynamic = "force-dynamic";

export default async function InstancesPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; saved?: string; removed?: string }>;
}) {
  await requireSession();
  const { err, saved, removed } = await searchParams;
  const instances = await registry();
  const current = await currentInstance();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Engine Instances"
        sub="Manage and register autonomous engine processes, port routing, and isolated database connections"
      />

      {saved ? <Alert tone="success">Instance "{saved}" saved successfully.</Alert> : null}
      {removed ? <Alert tone="success">Instance "{removed}" removed from registry.</Alert> : null}
      {err ? <Alert tone="error">{err}</Alert> : null}

      {/* Instance Summary Cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-line bg-card p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-ink-dim">Active Instance</span>
            <Server className="h-4 w-4 text-accent" />
          </div>
          <p className="mt-2 font-mono text-xl font-bold text-ink">{current.name}</p>
          <p className="mt-1 truncate font-mono text-xs text-ink-faint">{current.baseUrl}</p>
        </div>

        <div className="rounded-xl border border-line bg-card p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-ink-dim">Registered Engines</span>
            <Boxes className="h-4 w-4 text-accent" />
          </div>
          <p className="mt-2 font-mono text-xl font-bold text-ink">{instances.length}</p>
          <p className="mt-1 text-xs text-ink-faint">
            {instances.filter((i) => i.origin === "env").length} env-locked • {instances.filter((i) => i.origin === "file").length} file-managed
          </p>
        </div>

        <div className="rounded-xl border border-line bg-card p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-ink-dim">Isolation Mode</span>
            <ShieldCheck className="h-4 w-4 text-emerald-500" />
          </div>
          <p className="mt-2 font-mono text-xl font-bold text-emerald-600 dark:text-emerald-400">Strict Scoped</p>
          <p className="mt-1 text-xs text-ink-faint">Per-process DB & API credentials</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        {/* Table of Instances */}
        <Card className="overflow-hidden">
          <CardHeader className="bg-surface/30 pb-3">
            <CardTitle className="text-sm font-semibold">Registered Engines</CardTitle>
            <CardDescription className="text-xs">
              List of configured ContentFTE engine daemon endpoints.
            </CardDescription>
          </CardHeader>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Instance Name</TableHead>
                  <TableHead>Base URL</TableHead>
                  <TableHead>Auth Key</TableHead>
                  <TableHead>Origin</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {instances.map((i) => {
                  const isActive = i.name === current.name;
                  return (
                    <TableRow key={i.name} className="group">
                      <TableCell className="font-semibold text-ink whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <Server className={`h-3.5 w-3.5 ${isActive ? "text-accent" : "text-ink-faint"}`} />
                          <span>{i.name}</span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-ink-dim whitespace-nowrap">
                        {i.baseUrl}
                      </TableCell>
                      <TableCell className="text-xs text-ink-faint whitespace-nowrap">
                        {i.apiKey ? (
                          <span className="font-mono text-[11px] text-ink-dim">••••••••</span>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <Badge
                          variant={i.origin === "env" ? "warning" : "secondary"}
                          className="font-mono text-[10px]"
                        >
                          {i.origin}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {isActive ? (
                          <Badge variant="success" dot className="font-medium">
                            Active
                          </Badge>
                        ) : (
                          <form action={switchInstanceAction} className="inline">
                            <input type="hidden" name="instance" value={i.name} />
                            <PendingButton
                              className="inline-flex items-center gap-1 text-xs font-medium text-accent transition-colors hover:text-accent-strong hover:underline"
                              pendingLabel="Switching…"
                              leftIcon={<ArrowRightLeft className="h-3 w-3" />}
                            >
                              Switch
                            </PendingButton>
                          </form>
                        )}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {i.origin === "file" ? (
                          <form action={removeInstanceAction} className="inline">
                            <input type="hidden" name="name" value={i.name} />
                            <PendingButton
                              className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-rose-500 transition-all hover:bg-rose-500/15 hover:text-rose-600 focus-visible:outline-none"
                              confirmMessage={`Remove instance "${i.name}" from the console registry?`}
                              pendingLabel="…"
                              title={`Remove instance "${i.name}"`}
                              aria-label={`Remove instance "${i.name}"`}
                              leftIcon={<Trash2 className="h-3.5 w-3.5" />}
                            >
                              <span className="sr-only">Remove</span>
                            </PendingButton>
                          </form>
                        ) : (
                          <span className="text-[11px] text-ink-faint">Locked (env)</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </Card>

        {/* Add/Edit Instance Card */}
        <Card>
          <CardHeader className="bg-surface/30 pb-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <PlusCircle className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold">Register Engine Daemon</CardTitle>
                <CardDescription className="text-xs">
                  Connect to a running ContentFTE FastAPI service.
                </CardDescription>
              </div>
            </div>
          </CardHeader>

          <CardContent className="pt-4">
            <form action={saveInstanceAction} className="space-y-4">
              <Input
                name="name"
                label="Instance Identifier"
                required
                placeholder="e.g. site2-staging"
                leftIcon={<Server className="h-3.5 w-3.5" />}
                helperText="Internal name for quick switching."
              />

              <Input
                name="base_url"
                label="Base Engine URL"
                required
                placeholder="http://127.0.0.1:8001"
                leftIcon={<Link2 className="h-3.5 w-3.5" />}
                helperText="Direct HTTP address where the engine is listening."
              />

              <Input
                name="api_key"
                type="password"
                label="Master SDK Key (Optional)"
                placeholder="Leave blank if engine has no master key"
                leftIcon={<KeyRound className="h-3.5 w-3.5" />}
                helperText="Passed in X-Site-Key headers for authenticated endpoints."
              />

              <div className="pt-2">
                <PendingButton
                  pendingLabel="Saving instance…"
                  leftIcon={<Plus className="h-4 w-4" />}
                  className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent-strong px-4 py-2 text-xs font-semibold text-white shadow-xs transition-all hover:bg-accent hover:shadow active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Register Engine Instance
                </PendingButton>
              </div>
            </form>

            <p className="mt-4 border-t border-line/60 pt-3 text-[11px] leading-relaxed text-ink-faint">
              Saving with an existing name overwrites the entry. Instances stored in <code className="rounded bg-surface px-1 py-0.5 font-mono">instances.json</code> can be removed anytime.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
