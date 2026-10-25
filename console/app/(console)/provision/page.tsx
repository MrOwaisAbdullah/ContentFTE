"use client";

import { useActionState, useState } from "react";
import { generateEnvAction, type EnvResult } from "@/actions/instances";
import { Alert } from "@/lib/ui";
import {
  Check,
  Copy,
  Download,
  FileCode,
  Globe,
  Hash,
  KeyRound,
  Layers,
  Link2,
  Lock,
  Rocket,
  ShieldCheck,
  Sparkles,
  Tag,
  Terminal,
  User,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const RUNBOOK_STEPS = [
  {
    step: "01",
    title: "Database Isolation (Neon / Postgres)",
    body: "Create a dedicated Neon Postgres branch or project for this site to ensure zero cross-tenant bleeding. Copy the pooled connection string into DATABASE_URL.",
  },
  {
    step: "02",
    title: "AI & Search Providers",
    body: "Configure separate API keys for Gemini, OpenRouter, and Tavily search to meter per-instance spend and quotas accurately.",
  },
  {
    step: "03",
    title: "CMS Integration (WordPress / Custom)",
    body: "For WordPress: generate an Application Password in WP Admin → Users. For Custom Next.js sites: configure webhook callbacks.",
  },
  {
    step: "04",
    title: "Engine Boot & Registration",
    body: "Run 'uvicorn main:app --port 8001' with the generated .env, then register the new port in the Instances tab.",
  },
];

export default function ProvisionPage() {
  const [state, formAction, pending] = useActionState<EnvResult, FormData>(
    generateEnvAction,
    {},
  );
  const [copied, setCopied] = useState(false);
  const [downloaded, setDownloaded] = useState(false);

  function copyEnv() {
    if (!state.env) return;
    navigator.clipboard.writeText(state.env);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function download() {
    if (!state.env) return;
    const blob = new Blob([state.env], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `.env.${state.slug || "instance"}`;
    a.click();
    URL.revokeObjectURL(url);
    setDownloaded(true);
    setTimeout(() => setDownloaded(false), 2000);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-ink sm:text-2xl">
          Site Provisioning Wizard
        </h1>
        <p className="mt-1 text-xs text-ink-dim">
          Configure, generate, and deploy an isolated ContentFTE instance and target CMS integration.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        {/* Provision Form */}
        <Card>
          <CardHeader className="bg-surface/30 pb-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <Rocket className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold">Instance Configuration</CardTitle>
                <CardDescription className="text-xs">
                  Generate isolated environment variables and optionally auto-insert the site.
                </CardDescription>
              </div>
            </div>
          </CardHeader>

          <CardContent className="pt-5">
            <form action={formAction} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  name="slug"
                  label="Site Slug"
                  required
                  leftIcon={<Hash className="h-3.5 w-3.5" />}
                  placeholder="e.g. tech-insights"
                  helperText="Lowercase slug for directory and DB partitioning."
                />

                <Input
                  name="name"
                  label="Display Name"
                  leftIcon={<Tag className="h-3.5 w-3.5" />}
                  placeholder="e.g. Tech Insights Blog"
                  helperText="User-facing blog branding."
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <Select
                  name="site_type"
                  label="Site Architecture"
                  defaultValue="wordpress"
                  leftIcon={<Layers className="h-3.5 w-3.5" />}
                  helperText="Target CMS publishing protocol."
                >
                  <option value="wordpress">WordPress REST API</option>
                  <option value="custom">Custom Site (Next.js / Sanity)</option>
                </Select>

                <Input
                  name="base_url"
                  label="Live Base URL"
                  leftIcon={<Globe className="h-3.5 w-3.5" />}
                  placeholder="https://example.com"
                  helperText="Public site root URL."
                />
              </div>

              {/* WordPress Credentials Section */}
              <div className="rounded-xl border border-line/70 bg-surface/30 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-3.5 w-3.5 text-accent" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-ink-dim">
                    WordPress CMS Credentials
                  </span>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Input
                    name="wp_user"
                    label="WP Author Username"
                    leftIcon={<User className="h-3.5 w-3.5" />}
                    placeholder="editor_bot"
                  />
                  <Input
                    name="wp_password"
                    type="password"
                    label="Application Password"
                    leftIcon={<Lock className="h-3.5 w-3.5" />}
                    placeholder="xxxx xxxx xxxx xxxx"
                  />
                </div>
              </div>

              <Input
                name="sdk_key"
                label="Master SDK Key (Optional)"
                leftIcon={<KeyRound className="h-3.5 w-3.5" />}
                placeholder="sk_live_... (leave blank to auto-generate)"
                helperText="Pre-shared key for daemon API access."
              />

              <label className="flex items-center gap-2.5 rounded-xl border border-line bg-surface/20 p-3 text-xs text-ink-dim cursor-pointer transition-colors hover:bg-surface/40">
                <input
                  type="checkbox"
                  name="also_create_site"
                  value="1"
                  defaultChecked
                  className="rounded accent-accent h-4 w-4"
                />
                <span>Automatically insert site entry into the active database</span>
              </label>

              <Button
                type="submit"
                disabled={pending}
                isLoading={pending}
                leftIcon={<Rocket className="h-4 w-4" />}
                className="w-full h-10 font-semibold"
              >
                {pending ? "Generating Environment Configuration…" : "Generate Isolated .env File"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Runbook & Generated Env Result */}
        <div className="space-y-4">
          {state.env ? (
            <Card className="border-accent/40">
              <CardHeader className="bg-accent/5 pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileCode className="h-4 w-4 text-accent" />
                    <CardTitle className="text-xs font-bold uppercase tracking-wider text-accent">
                      Generated Configuration (.env)
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={copyEnv}
                      leftIcon={copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                    >
                      {copied ? "Copied" : "Copy"}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={download}
                      leftIcon={<Download className="h-3 w-3" />}
                    >
                      Download
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="pt-4">
                {state.siteCreated ? (
                  <div className="mb-3">
                    <Alert tone="success">
                      Site row <strong>{state.slug}</strong> registered in the engine database.
                    </Alert>
                  </div>
                ) : null}

                <pre className="max-h-80 overflow-y-auto rounded-xl border border-line bg-page p-3 font-mono text-[11px] leading-relaxed text-ink-dim">
                  {state.env}
                </pre>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="bg-surface/30 pb-3">
                <div className="flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-accent" />
                  <CardTitle className="text-xs font-bold uppercase tracking-wider text-ink-dim">
                    Multi-Tenant Operator Runbook
                  </CardTitle>
                </div>
              </CardHeader>

              <CardContent className="pt-4">
                <div className="space-y-3">
                  {RUNBOOK_STEPS.map((s) => (
                    <div
                      key={s.step}
                      className="flex gap-3 rounded-xl border border-line/60 bg-surface/20 p-3 transition-colors hover:bg-surface/40"
                    >
                      <Badge variant="accent" className="h-6 w-6 font-mono text-[11px] font-bold p-0 justify-center shrink-0">
                        {s.step}
                      </Badge>
                      <div>
                        <p className="text-xs font-semibold text-ink">{s.title}</p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-ink-faint">{s.body}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
