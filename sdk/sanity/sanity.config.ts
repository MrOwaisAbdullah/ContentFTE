"use client";

/**
 * Sanity Studio config. Mount it at /studio:
 *
 *   // app/studio/[[...tool]]/page.tsx
 *   import Studio from "./Studio";
 *   export default function Studio() { return <Studio /> }
 */
import { visionTool } from "@sanity/vision";
import { defineConfig } from "sanity";
import { structureTool } from "sanity/structure";

import { apiVersion, dataset, projectId } from "./env";
import { schema } from "./schemaTypes";
import { structure } from "./structure";

export default defineConfig({
  basePath: "/studio",
  projectId,
  dataset,
  schema,
  plugins: [
    structureTool({structure}),
    // Query with GROQ from inside the Studio.
    visionTool({defaultApiVersion: apiVersion}),
  ],
});
