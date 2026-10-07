/**
 * ContentFTEArticle — renderer for the SDK delivery payload.
 *
 *   npm install @owais-abdullah/contentfte
 *   import { ContentFTEArticle } from "@owais-abdullah/contentfte/renderer";
 *   import "@owais-abdullah/contentfte/contentfte-prose.css";
 *
 * Takes the response of `client.getContent(articleId)` (the unified
 * `/content` payload) and renders it portfolio-style:
 *
 *   - payload.title is the <h1> — the pipeline never emits an H1 in the
 *     markdown body (blog_agents.py: "THE TITLE WILL BE USED AS H1"); the
 *     body opens with the TL;DR blockquote → H2 sections
 *   - markdown body via react-markdown + remark-gfm (tables/strikethrough),
 *     rehype-raw (engine markdown may contain inline HTML),
 *     rehype-sanitize (defense-in-depth for LLM-authored content — keeps
 *     <mark>/ids/classes, drops scripts/handlers), then rehype-slug last so
 *     heading ids stay clean for TOC/scrollspy anchors
 *   - `==highlight==` → <mark> (same syntax lib/wp_render.py:80 renders for
 *     WordPress) via a remark plugin that only touches text nodes, so code
 *     spans/fences are never rewritten
 *   - external links target=_blank rel="noopener noreferrer"
 *   - tables wrapped in an overflow-x container
 *   - FAQ section from payload.schema.faq (<section id="faqs">)
 *   - Article + FAQPage JSON-LD (with `<` escaped so it can never break out
 *     of the script element)
 *
 * Works in React Server Components (no hooks, no "use client" directive).
 * If `markdown` is empty but `html` is present, falls back to the
 * server-rendered html field.
 */
import React from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

export interface ContentFTESchema {
  article?: Record<string, unknown>;
  faq?: {
    mainEntity?: Array<{ name?: string; acceptedAnswer?: { text?: string } }>;
  } | null;
}

export interface ContentFTEPayload {
  title: string;
  slug: string;
  url: string;
  excerpt: string;
  html: string;
  markdown: string;
  markdown_alternate?: string;
  schema?: ContentFTESchema;
  [key: string]: unknown;
}

export interface ContentFTEArticleProps {
  /** Response of client.getContent(articleId). */
  content: ContentFTEPayload;
  /**
   * Your site origin (e.g. "https://mysite.com"). Absolute links on this
   * origin stay in-tab; every other absolute link opens in a new tab with
   * rel="noopener noreferrer". Omit to treat all absolute links as external.
   */
  siteOrigin?: string;
  /** Extra class on the <article> wrapper (the cfte-prose class is always there). */
  className?: string;
}

/** `==text==` → `<mark>text</mark>` on text nodes only (parity with wp_render). */
const remarkHighlight = () => (tree: { children?: unknown }) => {
  const walk = (node: { type?: string; value?: unknown; children?: unknown[] }) => {
    if (!Array.isArray(node.children)) return;
    const next: unknown[] = [];
    for (const child of node.children as Array<{
      type?: string;
      value?: unknown;
      children?: unknown[];
    }>) {
      if (child.type === "text" && typeof child.value === "string" && child.value.includes("==")) {
        for (const part of child.value.split(/(==[^=\n]+==)/g)) {
          if (!part) continue;
          if (part.startsWith("==") && part.endsWith("==") && part.length > 4) {
            next.push({ type: "html", value: `<mark>${part.slice(2, -2)}</mark>` });
          } else {
            next.push({ type: "text", value: part });
          }
        }
      } else {
        walk(child);
        next.push(child);
      }
    }
    node.children = next;
  };
  walk(tree as { children?: unknown[] });
};

/** Schema forked from rehype-sanitize's default: keep mark/ids/classes. */
const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "mark", "del", "section"],
  attributes: {
    ...defaultSchema.attributes,
    "*": [...(defaultSchema.attributes?.["*"] ?? []), "id", "className"],
  },
  // headings get clean ids from rehype-slug (runs after sanitize) for TOC anchors
  clobberPrefix: "",
};

function isExternal(href: string, siteOrigin?: string): boolean {
  if (!/^https?:\/\//i.test(href)) return false; // relative / #anchor → in-tab
  if (!siteOrigin) return true;
  return !href.toLowerCase().startsWith(siteOrigin.toLowerCase());
}

/** Per-render component map (closes over siteOrigin). */
function buildComponents(siteOrigin?: string): Components {
  return {
    a: ({ node: _node, href = "", children, ...rest }) =>
      isExternal(href, siteOrigin) ? (
        <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
        </a>
      ) : (
        <a href={href} {...rest}>
          {children}
        </a>
      ),
    table: ({ node: _node, children, ...rest }) => (
      <div className="cfte-table-wrap">
        <table {...rest}>{children}</table>
      </div>
    ),
    img: ({ node: _node, ...rest }) => (
      <img loading="lazy" decoding="async" {...rest} />
    ),
  };
}

function jsonLd(data: Record<string, unknown>) {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

/** FAQ section rendered from payload.schema.faq (schema.org FAQPage shape). */
export function ContentFTEFaq({ schema }: { schema?: ContentFTESchema }) {
  const items = schema?.faq?.mainEntity ?? [];
  if (items.length === 0) return null;
  return (
    <section id="faqs" aria-label="Frequently asked questions" className="cfte-faq">
      <h2>Frequently asked questions</h2>
      {items.map((item, i) => (
        <div key={i} className="cfte-faq-item">
          <h3>{item.name}</h3>
          <p>{item.acceptedAnswer?.text}</p>
        </div>
      ))}
    </section>
  );
}

export function ContentFTEArticle({ content, siteOrigin, className }: ContentFTEArticleProps) {
  const body = content.markdown ? (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkHighlight]}
      rehypePlugins={[
        rehypeRaw,
        [rehypeSanitize, sanitizeSchema],
        rehypeSlug,
      ]}
      components={buildComponents(siteOrigin)}
    >
      {content.markdown}
    </ReactMarkdown>
  ) : content.html ? (
    // engine-rendered HTML fallback (markdown_to_wp_html, blocks=False)
    <div dangerouslySetInnerHTML={{ __html: content.html }} />
  ) : null;

  return (
    // structured data is JSON-LD only (Google's recommended format) — no
    // microdata, since React 19 serializes itemProp/itemScope camelCase
    <article className={["cfte-prose", className].filter(Boolean).join(" ")}>
      {content.schema?.article ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(content.schema.article) }}
        />
      ) : null}
      {content.schema?.faq ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(content.schema.faq) }}
        />
      ) : null}

      <h1>{content.title}</h1>
      {content.excerpt ? (
        <p className="cfte-dek">{content.excerpt}</p>
      ) : null}

      {body}

      <ContentFTEFaq schema={content.schema} />
    </article>
  );
}
