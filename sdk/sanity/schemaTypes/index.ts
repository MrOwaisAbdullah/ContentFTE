import { type SchemaTypeDefinition } from "sanity";

import { blockContentType } from "./blockContentType";
import { categoryType } from "./categoryType";
import { postType } from "./postType";
import { authorType } from "./authorType";

/**
 * The four types the ContentFTE engine actually writes (see
 * lib/sanity_adapter.py::post_blog). A site can extend
 * `schema.types` with its own types without touching these.
 */
export const schema: { types: SchemaTypeDefinition[] } = {
  types: [blockContentType, categoryType, postType, authorType],
};
