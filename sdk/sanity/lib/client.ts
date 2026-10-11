import { createClient } from "next-sanity";

import { apiVersion, dataset, projectId } from "../env";

export const client = createClient({
  projectId,
  dataset,
  apiVersion,
  // Set to false when statically generating pages, using ISR or
  // tag-based revalidation.
  useCdn: true,
});
