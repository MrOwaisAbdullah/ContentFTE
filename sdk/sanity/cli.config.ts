import { defineCliConfig } from "sanity/cli";

/**
 * Lets you run `npx sanity <command>` in this folder. Everything comes from
 * the environment -- no project ids in source.
 */
const projectId = process.env.NEXT_PUBLIC_SANITY_PROJECT_ID;
const dataset = process.env.NEXT_PUBLIC_SANITY_DATASET;

export default defineCliConfig({ api: { projectId, dataset } });
