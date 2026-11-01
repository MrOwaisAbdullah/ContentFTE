"use client";

import { useState, useTransition } from "react";
import { updateSiteSettingsAction, testSiteConnectionAction, type WpTestResult } from "@/actions/instances";
import { PendingButton } from "@/lib/interactive";
import type { SiteCadenceStatus, SiteInfo } from "@/lib/engine";
import {
  AlertCircle,
  Bell,
  Calendar,
  CheckCircle2,
  Clock,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Globe,
  ImageIcon,
  Info,
  KeyRound,
  Lock,
  RefreshCw,
  Save,
  Send,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  Sparkles,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDateTimeUtc } from "@/lib/format";

const CADENCE_OPTIONS = [
  { value: "daily", label: "Daily", sub: "1 post every 24 hours" },
  { value: "every_2_days", label: "Every 2 Days", sub: "1 post every 48 hours (Recommended)" },
  { value: "twice_a_week", label: "Twice a Week", sub: "Every 3 to 4 days (~8/month)" },
  { value: "weekly", label: "Weekly", sub: "1 post every 7 days (~4/month)" },
  { value: "biweekly", label: "Bi-Weekly", sub: "1 post every 14 days (~2/month)" },
  { value: "monthly", label: "Monthly", sub: "1 post every 30 days (~1/month)" },
  { value: "manual", label: "Manual Only", sub: "Never auto-publish; manual trigger only" },
];

const VLM_OPTIONS = [
  { value: "qwen/qwen3-vl-30b-a3b-instruct", label: "Qwen 3 VL 30B Instruct (Recommended - High Precision)" },
  { value: "qwen/qwen3-vl-8b-instruct", label: "Qwen 3 VL 8B Instruct (Fast & Economic)" },
  { value: "deepseek/deepseek-vl", label: "DeepSeek Vision 7B" },
];

const IMAGE_PREF_OPTIONS = [
  { value: "stock_first", label: "Stock Photos First (Recommended)", sub: "Uses curated stock photos for real illustrations; fallback to AI diagrams" },
  { value: "ai_first", label: "AI Generated First", sub: "Generate illustrations via AI models; fallback to stock if quota or safety triggers" },
  { value: "stock_only", label: "Stock Photos Only", sub: "Never use AI image generation; stock photos and diagrams only" },
];

/** Opt-in removal of a stored secret. Blank inputs keep the value, so deleting needs an explicit tick. */
function ClearSecret({ flag, label, saved }: { flag: string; label: string; saved: boolean }) {
  if (!saved) return null;
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-ink-faint cursor-pointer">
      <input type="checkbox" name="clear_secret" value={flag} className="h-3 w-3 accent-accent rounded" />
      <span>Remove the saved {label} when I save</span>
    </label>
  );
}

interface Props {
  site: SiteInfo;
  cadence?: SiteCadenceStatus | null;
}

export function SiteCadenceSettings({ site, cadence }: Props) {
  const settings = (site.settings || {}) as Record<string, any>;
  const wpSettings = (settings.wp || {}) as Record<string, any>;
  const imageSettings = (settings.image || {}) as Record<string, any>;
  const contentSettings = (settings.content || {}) as Record<string, any>;
  const budgetSettings = (settings.budget || {}) as Record<string, any>;
  const indexingSettings = (settings.indexing || {}) as Record<string, any>;
  const notifSettings = (settings.notifications || {}) as Record<string, any>;
  // Secret VALUES never reach the browser (stripped by lib/engine.ts); only
  // these booleans do. A blank secret input means "keep the stored one".
  const secretsSet = (site.secrets_set || {}) as Record<string, boolean>;
  const secretHint = (flag: string, empty: string) =>
    secretsSet[flag] ? "•••••••• saved — leave blank to keep" : empty;

  // Tab State
  const [activeTab, setActiveTab] = useState<"cadence" | "wordpress" | "images" | "content" | "seo">("cadence");

  // Cadence Form States
  const [frequency, setFrequency] = useState(String(settings.posting_frequency || cadence?.frequency || "every_2_days"));
  const [maxPosts, setMaxPosts] = useState(Number(settings.max_posts_per_cadence ?? cadence?.max_posts_per_cadence ?? 1));
  const [requireApproval, setRequireApproval] = useState(Boolean(settings.require_approval ?? cadence?.require_approval ?? true));
  const [autoPublish, setAutoPublish] = useState(Boolean(settings.auto_publish ?? cadence?.auto_publish ?? false));
  const [enforceCadence, setEnforceCadence] = useState(Boolean(settings.enforce_cadence ?? cadence?.enforced ?? false));
  const [publishMode, setPublishMode] = useState(String(settings.publish_mode || cadence?.publish_mode || site.publish_mode || "draft"));

  // WordPress Auth States
  const [wpBaseUrl, setWpBaseUrl] = useState(String(wpSettings.base_url || site.base_url || ""));
  const [wpUsername, setWpUsername] = useState(String(wpSettings.username || ""));
  const [wpPassword, setWpPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [testResult, setTestResult] = useState<WpTestResult | null>(null);
  const [isTestingWp, startTestingWp] = useTransition();

  // Image Pipeline States
  const [imagePreference, setImagePreference] = useState(String(imageSettings.image_preference || "stock_first"));
  const [stockThreshold, setStockThreshold] = useState(Number(imageSettings.stock_relevancy_threshold ?? 30));
  const [vlmModel, setVlmModel] = useState(String(imageSettings.vlm_model || "qwen/qwen3-vl-30b-a3b-instruct"));
  const [maxRevisions, setMaxRevisions] = useState(Number(imageSettings.max_revisions ?? 2));

  // Content & SEO States
  const [minWords, setMinWords] = useState(Number(contentSettings.min_words ?? 1500));
  const [brandVoice, setBrandVoice] = useState(String(contentSettings.brand_voice_prompt || ""));
  const [generateFaqs, setGenerateFaqs] = useState(Boolean(contentSettings.generate_faqs ?? true));
  const [monthlyBudget, setMonthlyBudget] = useState(String(budgetSettings.monthly_usd ?? ""));

  const [autoIndex, setAutoIndex] = useState(Boolean(indexingSettings.auto_index_on_publish ?? true));
  const [indexnowKey, setIndexnowKey] = useState("");
  const [bingKey, setBingKey] = useState("");
  const [gscProperty, setGscProperty] = useState(String(indexingSettings.search_console_property || settings.search_console_site_url || ""));

  // Webhooks
  const [discordWebhook, setDiscordWebhook] = useState("");
  const [notifyOnDraft, setNotifyOnDraft] = useState(Boolean(notifSettings.notify_on_draft ?? false));
  const [notifyOnApproval, setNotifyOnApproval] = useState(Boolean(notifSettings.notify_on_approval_needed ?? true));
  const [notifyOnPublish, setNotifyOnPublish] = useState(Boolean(notifSettings.notify_on_publish ?? true));

  // Cadence window calculations
  const canPublishNow = cadence?.can_publish_now ?? true;
  const hoursRemaining = cadence?.seconds_remaining ? Math.round((cadence.seconds_remaining / 3600) * 10) / 10 : 0;
  const nextAllowed = cadence?.next_allowed_at ? fmtDateTimeUtc(cadence.next_allowed_at) : null;
  const lastPublished = cadence?.last_published_at ? fmtDateTimeUtc(cadence.last_published_at) : null;

  const handleTestWp = () => {
    setTestResult(null);
    startTestingWp(async () => {
      const res = await testSiteConnectionAction(site.slug, {
        base_url: wpBaseUrl,
        username: wpUsername,
        app_password: wpPassword,
      });
      setTestResult(res);
    });
  };

  return (
    <div className="space-y-6">
      {/* Cadence Telemetry & Real-Time Status Card */}
      <div className="rounded-xl border border-line bg-surface/30 p-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-line/60">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-accent" />
            <h3 className="font-headline text-sm font-semibold text-ink">
              Live Posting Cadence &amp; Frequency Status
            </h3>
          </div>
          <div>
            {frequency === "manual" ? (
              <Badge variant="outline" className="font-mono text-xs border-line bg-surface text-ink-dim">
                <Lock className="mr-1 h-3 w-3 text-ink-faint" /> Manual Publishing Only
              </Badge>
            ) : canPublishNow ? (
              <Badge variant="outline" className="font-mono text-xs border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="mr-1 h-3 w-3 text-emerald-500" /> Cadence Window Open (Ready)
              </Badge>
            ) : (
              <Badge variant="outline" className="font-mono text-xs border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                <Clock className="mr-1 h-3 w-3 text-amber-500" /> Window Locked ({hoursRemaining}h remaining)
              </Badge>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3">
          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-ink-faint">
              Active Frequency
            </span>
            <p className="font-mono text-xs font-semibold text-ink">
              {CADENCE_OPTIONS.find((c) => c.value === frequency)?.label || frequency}
            </p>
            <p className="text-[11px] text-ink-faint">
              {CADENCE_OPTIONS.find((c) => c.value === frequency)?.sub || "Custom cadence rule"}
            </p>
          </div>

          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-ink-faint">
              Last Article Published
            </span>
            <p className="font-mono text-xs font-semibold text-ink truncate" title={cadence?.last_published_title || "None"}>
              {cadence?.last_published_title ? `#${cadence.last_published_id}: ${cadence.last_published_title}` : "None recorded"}
            </p>
            <p className="text-[11px] text-ink-faint">
              {lastPublished ? lastPublished : "No post on record"}
            </p>
          </div>

          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-ink-faint">
              Next Cadence Dispatch Slot
            </span>
            <p className="font-mono text-xs font-semibold text-ink">
              {frequency === "manual" ? "On manual approval" : nextAllowed ? nextAllowed : "Open now"}
            </p>
            <p className="text-[11px] text-ink-faint">
              {requireApproval ? "Requires operator approval first" : autoPublish ? "Auto-dispatches on slot" : "Ready when triggered"}
            </p>
          </div>
        </div>
      </div>

      {/* Main Settings Panel with Multi-Section Navigation */}
      <Card>
        <CardHeader className="pb-3 border-b border-line/50">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-accent" />
              <CardTitle className="text-sm font-semibold">Site Engine &amp; Feature Configuration</CardTitle>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-ink-faint">
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
              <span>Multi-Tenant Instance Control</span>
            </div>
          </div>
          <CardDescription className="text-xs">
            Manage cadence pacing, WordPress API credentials, AI image filters, brand voice guidelines, and SEO webhooks.
          </CardDescription>

          {/* Section Navigation Tabs */}
          <div className="flex flex-wrap items-center gap-1.5 pt-3">
            <button
              type="button"
              onClick={() => setActiveTab("cadence")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === "cadence"
                  ? "bg-accent text-white font-semibold shadow-xs"
                  : "bg-surface/50 text-ink-dim hover:text-ink hover:bg-surface border border-line"
              }`}
            >
              <Clock className="h-3.5 w-3.5" />
              <span>Posting Cadence</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("wordpress")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === "wordpress"
                  ? "bg-accent text-white font-semibold shadow-xs"
                  : "bg-surface/50 text-ink-dim hover:text-ink hover:bg-surface border border-line"
              }`}
            >
              <KeyRound className="h-3.5 w-3.5" />
              <span>WordPress Auth &amp; Probe</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("images")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === "images"
                  ? "bg-accent text-white font-semibold shadow-xs"
                  : "bg-surface/50 text-ink-dim hover:text-ink hover:bg-surface border border-line"
              }`}
            >
              <ImageIcon className="h-3.5 w-3.5" />
              <span>AI Images &amp; VLM</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("content")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === "content"
                  ? "bg-accent text-white font-semibold shadow-xs"
                  : "bg-surface/50 text-ink-dim hover:text-ink hover:bg-surface border border-line"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              <span>Brand Voice &amp; Content</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("seo")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === "seo"
                  ? "bg-accent text-white font-semibold shadow-xs"
                  : "bg-surface/50 text-ink-dim hover:text-ink hover:bg-surface border border-line"
              }`}
            >
              <Zap className="h-3.5 w-3.5" />
              <span>SEO Indexing &amp; Alerts</span>
            </button>
          </div>
        </CardHeader>

        <CardContent className="pt-5">
          <form action={updateSiteSettingsAction} className="space-y-6" noValidate>
            <input type="hidden" name="slug" value={site.slug} />
            {/* Every tab stays mounted (hidden), so one save submits all groups; the action only touches the groups listed here. */}
            <input type="hidden" name="_groups" value="cadence wp image content budget indexing notifications" />

            {/* TAB 1: CADENCE & APPROVAL */}
            <section hidden={activeTab !== "cadence"} aria-hidden={activeTab !== "cadence"}>{(
              <div className="space-y-6 animate-fadeIn">
                <div className="space-y-2">
                  <label className="block text-xs font-semibold uppercase tracking-wider text-ink">
                    Posting Frequency / Cadence
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                    {CADENCE_OPTIONS.map((opt) => {
                      const isSelected = frequency === opt.value;
                      return (
                        <label
                          key={opt.value}
                          className={`flex flex-col p-3 rounded-xl border cursor-pointer transition-all ${
                            isSelected
                              ? "border-accent bg-accent/10 shadow-xs ring-1 ring-accent"
                              : "border-line bg-card hover:border-line-dim hover:bg-surface/30"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className={`text-xs font-bold ${isSelected ? "text-accent" : "text-ink"}`}>
                              {opt.label}
                            </span>
                            <input
                              type="radio"
                              name="posting_frequency"
                              value={opt.value}
                              checked={isSelected}
                              onChange={() => setFrequency(opt.value)}
                              className="h-3.5 w-3.5 accent-accent"
                            />
                          </div>
                          <span className="mt-1 text-[11px] text-ink-faint leading-snug">
                            {opt.sub}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                    <label className="block text-xs font-semibold text-ink">
                      Max Posts Per Cadence Window
                    </label>
                    <div className="flex items-center gap-2 mt-1">
                      <input
                        type="number"
                        name="max_posts_per_cadence"
                        min="1"
                        max="10"
                        value={maxPosts}
                        onChange={(e) => setMaxPosts(parseInt(e.target.value, 10) || 1)}
                        className="w-20 px-3 py-1.5 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <span className="text-xs text-ink-faint">post(s) per interval</span>
                    </div>
                    <p className="text-[11px] text-ink-faint mt-1">
                      Guarantees no more than {maxPosts} article(s) are published within a single {frequency.replace(/_/g, " ")} window.
                    </p>
                  </div>

                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                    <label className="block text-xs font-semibold text-ink">
                      Target Publish Mode on CMS
                    </label>
                    <div className="grid grid-cols-2 gap-2 mt-1">
                      <label
                        className={`flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-medium cursor-pointer transition-all ${
                          publishMode === "draft"
                            ? "border-accent bg-accent/15 text-accent font-semibold"
                            : "border-line bg-card text-ink-dim hover:text-ink"
                        }`}
                      >
                        <input
                          type="radio"
                          name="publish_mode"
                          value="draft"
                          checked={publishMode === "draft"}
                          onChange={() => setPublishMode("draft")}
                          className="hidden"
                        />
                        <span>Draft (Safe)</span>
                      </label>
                      <label
                        className={`flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-medium cursor-pointer transition-all ${
                          publishMode === "publish"
                            ? "border-accent bg-accent/15 text-accent font-semibold"
                            : "border-line bg-card text-ink-dim hover:text-ink"
                        }`}
                      >
                        <input
                          type="radio"
                          name="publish_mode"
                          value="publish"
                          checked={publishMode === "publish"}
                          onChange={() => setPublishMode("publish")}
                          className="hidden"
                        />
                        <span>Live Public</span>
                      </label>
                    </div>
                    <p className="text-[11px] text-ink-faint mt-1">
                      {publishMode === "draft"
                        ? "Creates articles as Drafts in WordPress/CMS for operator signoff before public view."
                        : "Pushes articles directly to public status on the live site."}
                    </p>
                  </div>
                </div>

                <div className="space-y-3 pt-2 border-t border-line/60">
                  <span className="block text-xs font-semibold uppercase tracking-wider text-ink">
                    Approval &amp; Automation Guardrails
                  </span>

                  <div className="flex items-start gap-3 p-3.5 rounded-xl border border-line bg-surface/20">
                    <input
                      type="checkbox"
                      id="require_approval"
                      name="require_approval"
                      value="1"
                      checked={requireApproval}
                      onChange={(e) => setRequireApproval(e.target.checked)}
                      className="mt-0.5 h-4 w-4 accent-accent rounded"
                    />
                    <div className="space-y-0.5 flex-1">
                      <label htmlFor="require_approval" className="text-xs font-semibold text-ink cursor-pointer flex items-center gap-1.5">
                        <span>Require Explicit Operator Approval</span>
                        <Badge variant="outline" className="text-[10px] border-emerald-500/40 text-emerald-500 py-0 px-1.5">
                          Recommended
                        </Badge>
                      </label>
                      <p className="text-[11px] text-ink-faint">
                        Prevents automated publishing. All pipeline-generated articles stay in <code>Pending Review</code> until you review and click <b>Approve</b>.
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3 p-3.5 rounded-xl border border-line bg-surface/20">
                    <input
                      type="checkbox"
                      id="auto_publish"
                      name="auto_publish"
                      value="1"
                      checked={autoPublish}
                      onChange={(e) => setAutoPublish(e.target.checked)}
                      className="mt-0.5 h-4 w-4 accent-accent rounded"
                    />
                    <div className="space-y-0.5 flex-1">
                      <label htmlFor="auto_publish" className="text-xs font-semibold text-ink cursor-pointer flex items-center gap-1.5">
                        <span>Autonomous Dispatch on Cadence Window</span>
                        <Badge variant="outline" className="text-[10px] border-accent/40 text-accent py-0 px-1.5">
                          Automation
                        </Badge>
                      </label>
                      <p className="text-[11px] text-ink-faint">
                        When active, once an article is approved, the background scheduler automatically publishes it when the <code>{frequency}</code> slot arrives.
                      </p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3 p-3.5 rounded-xl border border-line bg-surface/20">
                    <input
                      type="checkbox"
                      id="enforce_cadence"
                      name="enforce_cadence"
                      value="1"
                      checked={enforceCadence}
                      onChange={(e) => setEnforceCadence(e.target.checked)}
                      className="mt-0.5 h-4 w-4 accent-accent rounded"
                    />
                    <div className="space-y-0.5 flex-1">
                      <label htmlFor="enforce_cadence" className="text-xs font-semibold text-ink cursor-pointer">
                        Enforce the post cap on every publish
                      </label>
                      <p className="text-[11px] text-ink-faint">
                        Refuse to publish once <code>{maxPosts}</code> post{maxPosts === 1 ? "" : "s"} already went out in the
                        current <code>{frequency}</code> window (a one-off <em>force</em> still overrides). Off = the cadence is
                        only a guide for the scheduler.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}</section>

            {/* TAB 2: WORDPRESS & CMS AUTH */}
            <section hidden={activeTab !== "wordpress"} aria-hidden={activeTab !== "wordpress"}>{(
              <div className="space-y-6 animate-fadeIn">
                <div className="rounded-xl border border-line bg-surface/20 p-4 space-y-4">
                  <div className="flex items-center justify-between pb-2 border-b border-line/60">
                    <div className="flex items-center gap-2">
                      <Globe className="h-4 w-4 text-accent" />
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-ink">
                        Per-Site WordPress REST API Credentials
                      </h4>
                    </div>
                    <Badge variant="outline" className="text-[11px] font-mono">
                      Site.settings[&quot;wp&quot;]
                    </Badge>
                  </div>

                  <p className="text-xs text-ink-faint">
                    Configure independent WordPress REST API credentials for this site. Per-site credentials prevent cross-instance bleed and let you manage unlimited WordPress sites securely from one console.
                  </p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-ink-dim">
                        WordPress Base URL
                      </label>
                      <input
                        type="url"
                        name="wp_base_url"
                        value={wpBaseUrl}
                        onChange={(e) => setWpBaseUrl(e.target.value)}
                        placeholder="https://yourdomain.com"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-ink-dim">
                        WordPress Username / Application User
                      </label>
                      <input
                        type="text"
                        name="wp_username"
                        value={wpUsername}
                        onChange={(e) => setWpUsername(e.target.value)}
                        placeholder="admin or editor_user"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1.5 md:col-span-2">
                      <div className="flex items-center justify-between">
                        <label className="block text-xs font-medium text-ink-dim">
                          WordPress Application Password
                        </label>
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline cursor-pointer"
                        >
                          {showPassword ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          <span>{showPassword ? "Hide" : "Show"} password</span>
                        </button>
                      </div>
                      <input
                        type={showPassword ? "text" : "password"}
                        name="wp_app_password"
                        value={wpPassword}
                        onChange={(e) => setWpPassword(e.target.value)}
                        placeholder={secretHint("wp_app_password", "xxxx xxxx xxxx xxxx")}
                        autoComplete="new-password"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <p className="text-[11px] text-ink-faint">
                        Generate in WordPress Admin → Users → Profile → Application Passwords.
                      </p>
                      <ClearSecret flag="wp_app_password" label="application password" saved={Boolean(secretsSet.wp_app_password)} />
                    </div>
                  </div>

                  {/* Live Connection Test Button & Feedback */}
                  <div className="pt-3 border-t border-line/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <button
                      type="button"
                      onClick={handleTestWp}
                      disabled={isTestingWp}
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-line bg-surface hover:bg-surface-high font-mono text-xs font-medium text-ink transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${isTestingWp ? "animate-spin" : ""}`} />
                      <span>{isTestingWp ? "Testing Endpoint…" : "Test WordPress Connection"}</span>
                    </button>

                    {testResult && (
                      <div className="flex-1 sm:max-w-md">
                        {testResult.ok ? (
                          <div className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-mono">
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                            <span className="truncate">
                              {testResult.message || "Connection verified successfully!"}
                              {testResult.tested === "saved" ? " (saved credentials)" : ""}
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 p-2 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-400 text-xs font-mono">
                            <AlertCircle className="h-4 w-4 shrink-0 text-rose-500" />
                            <span className="truncate">{testResult.error || "Connection failed."}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}</section>

            {/* TAB 3: AI IMAGES & VLM */}
            <section hidden={activeTab !== "images"} aria-hidden={activeTab !== "images"}>{(
              <div className="space-y-6 animate-fadeIn">
                <div className="space-y-2">
                  <label className="block text-xs font-semibold uppercase tracking-wider text-ink">
                    Visual Media Pipeline Strategy
                  </label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {IMAGE_PREF_OPTIONS.map((opt) => {
                      const isSelected = imagePreference === opt.value;
                      return (
                        <label
                          key={opt.value}
                          className={`flex flex-col p-3 rounded-xl border cursor-pointer transition-all ${
                            isSelected
                              ? "border-accent bg-accent/10 shadow-xs ring-1 ring-accent"
                              : "border-line bg-card hover:border-line-dim hover:bg-surface/30"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className={`text-xs font-bold ${isSelected ? "text-accent" : "text-ink"}`}>
                              {opt.label}
                            </span>
                            <input
                              type="radio"
                              name="image_preference"
                              value={opt.value}
                              checked={isSelected}
                              onChange={() => setImagePreference(opt.value)}
                              className="h-3.5 w-3.5 accent-accent"
                            />
                          </div>
                          <span className="mt-1 text-[11px] text-ink-faint leading-snug">
                            {opt.sub}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                    <div className="flex items-center justify-between">
                      <label className="block text-xs font-semibold text-ink">
                        Stock Photo Match Threshold
                      </label>
                      <span className="font-mono text-xs font-bold text-accent">{stockThreshold}%</span>
                    </div>
                    <input
                      type="range"
                      name="stock_relevancy_threshold"
                      min="10"
                      max="90"
                      step="5"
                      value={stockThreshold}
                      onChange={(e) => setStockThreshold(parseInt(e.target.value, 10))}
                      className="w-full accent-accent"
                    />
                    <p className="text-[11px] text-ink-faint">
                      Lower values (30%) accept broader matching real photos from Pexels. Higher values (80%+) enforce strict keyword overlap.
                    </p>
                  </div>

                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                    <label className="block text-xs font-semibold text-ink">
                      Max Image Revision Attempts
                    </label>
                    <div className="flex items-center gap-2 mt-1">
                      <input
                        type="number"
                        name="max_revisions"
                        min="1"
                        max="3"
                        value={maxRevisions}
                        onChange={(e) => setMaxRevisions(parseInt(e.target.value, 10) || 1)}
                        className="w-20 px-3 py-1.5 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <span className="text-xs text-ink-faint">attempts per slot</span>
                    </div>
                    <p className="text-[11px] text-ink-faint mt-1">
                      Number of times the image generator can retry if VLM judges quality as poor.
                    </p>
                  </div>
                </div>

                <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                  <label className="block text-xs font-semibold text-ink">
                    VLM Image Quality Judge Model
                  </label>
                  <select
                    name="vlm_model"
                    value={vlmModel}
                    onChange={(e) => setVlmModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-line bg-card text-xs text-ink focus:outline-none focus:border-accent"
                  >
                    {VLM_OPTIONS.map((v) => (
                      <option key={v.value} value={v.value}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                  <p className="text-[11px] text-ink-faint mt-1">
                    The vision language model that scores generated images on relevance, style artifacts, and text rendering before publishing.
                  </p>
                </div>
              </div>
            )}</section>

            {/* TAB 4: CONTENT & BRAND VOICE */}
            <section hidden={activeTab !== "content"} aria-hidden={activeTab !== "content"}>{(
              <div className="space-y-6 animate-fadeIn">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20">
                    <label className="block text-xs font-semibold text-ink">
                      Target Minimum Word Count
                    </label>
                    <div className="flex items-center gap-2 mt-1">
                      <input
                        type="number"
                        name="min_words"
                        min="800"
                        max="4000"
                        step="100"
                        value={minWords}
                        onChange={(e) => setMinWords(parseInt(e.target.value, 10) || 1500)}
                        className="w-28 px-3 py-1.5 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <span className="text-xs text-ink-faint">words</span>
                    </div>
                    <p className="text-[11px] text-ink-faint mt-1">
                      Enforces article depth. Generator will plan sufficient H2/H3 sub-sections to satisfy this target.
                    </p>
                  </div>

                  <div className="space-y-1.5 rounded-xl border border-line p-3.5 bg-surface/20 flex flex-col justify-between">
                    <div>
                      <label className="block text-xs font-semibold text-ink">
                        FAQ Generation &amp; Schema
                      </label>
                      <p className="text-[11px] text-ink-faint mt-1">
                        Automatically appends a comprehensive FAQ section and generates Article + FAQPage JSON-LD schemas.
                      </p>
                    </div>
                    <label className="flex items-center gap-2 mt-2 cursor-pointer">
                      <input
                        type="checkbox"
                        name="generate_faqs"
                        value="1"
                        checked={generateFaqs}
                        onChange={(e) => setGenerateFaqs(e.target.checked)}
                        className="h-4 w-4 accent-accent rounded"
                      />
                      <span className="text-xs font-medium text-ink">Generate FAQs &amp; JSON-LD Schema</span>
                    </label>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-semibold uppercase tracking-wider text-ink">
                      Brand Voice &amp; Tone Instructions
                    </label>
                    <span className="text-[11px] text-ink-faint">Passed to Writer System Prompt</span>
                  </div>
                  <textarea
                    name="brand_voice_prompt"
                    rows={4}
                    value={brandVoice}
                    onChange={(e) => setBrandVoice(e.target.value)}
                    placeholder="e.g. Tone should be authoritative, technical, yet approachable. Avoid buzzwords like 'revolutionary'. Use clear code examples and real-world analogies."
                    className="w-full px-3 py-2 rounded-lg border border-line bg-card text-xs text-ink focus:outline-none focus:border-accent font-sans leading-relaxed"
                  />
                  <p className="text-[11px] text-ink-faint">
                    Custom instructions injected into the Content Agent prompt for every article created under this site.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="budget_monthly_usd" className="block text-xs font-semibold uppercase tracking-wider text-ink">
                    Monthly spend cap (USD)
                  </label>
                  <input
                    id="budget_monthly_usd"
                    type="number"
                    name="budget_monthly_usd"
                    min={0}
                    step="0.01"
                    inputMode="decimal"
                    value={monthlyBudget}
                    onChange={(e) => setMonthlyBudget(e.target.value)}
                    placeholder="0 = no cap"
                    className="w-40 px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                  />
                  <p className="text-[11px] text-ink-faint">
                    Once this site&apos;s month-to-date spend reaches the cap, the engine refuses writing and image generation
                    for it (publishing and reading keep working) until next month or until you raise the cap. Protects you from
                    one client running up the bill.
                  </p>
                </div>
              </div>
            )}</section>

            {/* TAB 5: SEO INDEXING & ALERTS */}
            <section hidden={activeTab !== "seo"} aria-hidden={activeTab !== "seo"}>{(
              <div className="space-y-6 animate-fadeIn">
                <div className="rounded-xl border border-line bg-surface/20 p-4 space-y-4">
                  <div className="flex items-center justify-between pb-2 border-b border-line/60">
                    <div className="flex items-center gap-2">
                      <Zap className="h-4 w-4 text-accent" />
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-ink">
                        Automated SEO Submission &amp; IndexNow
                      </h4>
                    </div>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        name="auto_index_on_publish"
                        value="1"
                        checked={autoIndex}
                        onChange={(e) => setAutoIndex(e.target.checked)}
                        className="h-4 w-4 accent-accent rounded"
                      />
                      <span className="text-xs font-medium text-ink">Auto-Submit on Publish</span>
                    </label>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-ink-dim">
                        IndexNow API Key
                      </label>
                      <input
                        type="text"
                        name="indexnow_key"
                        value={indexnowKey}
                        onChange={(e) => setIndexnowKey(e.target.value)}
                        placeholder={secretHint("indexnow_key", "e.g. 32-char hex key")}
                        autoComplete="off"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <p className="text-[10px] text-ink-faint">
                        Instant notification to Bing, Yandex, and participating search engines.
                      </p>
                      <ClearSecret flag="indexnow_key" label="IndexNow key" saved={Boolean(secretsSet.indexnow_key)} />
                    </div>

                    <div className="space-y-1.5">
                      <label className="block text-xs font-medium text-ink-dim">
                        Bing Webmaster Tools API Key
                      </label>
                      <input
                        type="text"
                        name="bing_wmt_key"
                        value={bingKey}
                        onChange={(e) => setBingKey(e.target.value)}
                        placeholder={secretHint("bing_wmt_key", "Bing WMT API Key")}
                        autoComplete="off"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                      <ClearSecret flag="bing_wmt_key" label="Bing key" saved={Boolean(secretsSet.bing_wmt_key)} />
                    </div>

                    <div className="space-y-1.5 md:col-span-2">
                      <label className="block text-xs font-medium text-ink-dim">
                        Google Search Console Property URL
                      </label>
                      <input
                        type="text"
                        name="search_console_property"
                        value={gscProperty}
                        onChange={(e) => setGscProperty(e.target.value)}
                        placeholder="sc-domain:yourdomain.com or https://yourdomain.com/"
                        className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                      />
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-line bg-surface/20 p-4 space-y-4">
                  <div className="flex items-center gap-2 pb-2 border-b border-line/60">
                    <Bell className="h-4 w-4 text-accent" />
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-ink">
                      Discord &amp; Team Webhook Notifications
                    </h4>
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-xs font-medium text-ink-dim">
                      Discord Channel Webhook URL
                    </label>
                    <input
                      type="url"
                      name="discord_webhook_url"
                      value={discordWebhook}
                      onChange={(e) => setDiscordWebhook(e.target.value)}
                      placeholder={secretHint("discord_webhook_url", "https://discord.com/api/webhooks/...")}
                      autoComplete="off"
                      className="w-full px-3 py-2 rounded-lg border border-line bg-card font-mono text-xs text-ink focus:outline-none focus:border-accent"
                    />
                    <ClearSecret flag="discord_webhook_url" label="webhook URL" saved={Boolean(secretsSet.discord_webhook_url)} />
                  </div>

                  <div className="space-y-2 pt-1">
                    <span className="block text-xs font-medium text-ink-dim">
                      Notification Triggers
                    </span>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                        <input
                          type="checkbox"
                          name="notify_on_draft"
                          value="1"
                          checked={notifyOnDraft}
                          onChange={(e) => setNotifyOnDraft(e.target.checked)}
                          className="h-3.5 w-3.5 accent-accent rounded"
                        />
                        <span>Article Drafted</span>
                      </label>

                      <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                        <input
                          type="checkbox"
                          name="notify_on_approval_needed"
                          value="1"
                          checked={notifyOnApproval}
                          onChange={(e) => setNotifyOnApproval(e.target.checked)}
                          className="h-3.5 w-3.5 accent-accent rounded"
                        />
                        <span>Needs Approval</span>
                      </label>

                      <label className="flex items-center gap-2 text-xs text-ink cursor-pointer">
                        <input
                          type="checkbox"
                          name="notify_on_publish"
                          value="1"
                          checked={notifyOnPublish}
                          onChange={(e) => setNotifyOnPublish(e.target.checked)}
                          className="h-3.5 w-3.5 accent-accent rounded"
                        />
                        <span>Article Published</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            )}</section>

            {/* Bottom Actions Row */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-4 border-t border-line/60">
              <div className="flex items-center gap-1.5 text-xs text-ink-faint">
                <Info className="h-3.5 w-3.5 text-ink-faint shrink-0" />
                <span>All changes persist into SQLite and apply across pipeline stages immediately.</span>
              </div>
              <PendingButton
                pendingLabel="Saving Settings…"
                className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-accent text-white font-mono text-xs font-semibold shadow-xs hover:brightness-110 transition-all cursor-pointer"
                leftIcon={<Save className="h-3.5 w-3.5" />}
              >
                Save Site Configuration
              </PendingButton>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
