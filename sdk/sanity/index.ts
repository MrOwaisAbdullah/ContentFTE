/**
 * ContentFTE Sanity package.
 *
 * Drop this folder into a site repo as `sanity/`, add the env vars to
 * `.env.local`, and wire `sanity.config.ts` into the studio route:
 *
 *   // app/studio/[[...tool]]/page.tsx
 *   import Studio from "./Studio";
 *   ...
 *   // sanity/Studio.tsx
 *   "use client";
 *   import { NextStudio } from "next-sanity/studio";
 *   import config from "@/sanity.config";
 *   export default function Studio() { return <NextStudio config={config} />; }
 *
 * Deploy the schema once:
 *   npx sanity schema deploy
 *
 * Point the publish webhook at `/api/revalidate` and set
 * SANITY_REVALIDATE_SECRET (and INDEXNOW_KEY, which is optional -- omit it
 * and IndexNow pings are simply skipped).
 */
export { authorType } from "./schemaTypes/authorType";
export { blockContentType } from "./schemaTypes/blockContentType";
export { categoryType } from "./schemaTypes/categoryType";
export { postType } from "./schemaTypes/postType";

export { schema } from "./schemaTypes";
export { apiVersion, dataset, projectId } from "./env";
export { resolveSeoTitle, resolveSeoDescription } from "./lib/seo";
export type { SeoSource } from "./lib/seo";
