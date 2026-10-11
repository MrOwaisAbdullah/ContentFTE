import type { StructureResolver } from "sanity/structure";

/**
 * Studio structure. Extend with your own pinned singletons the same way --
 * copy the promoBanner block and change the schemaType + documentId.
 */
export const structure: StructureResolver = (S) =>
  S.list()
    .title("Content")
    .items([
      S.divider(),
      ...S.documentTypeListItems(),
    ]);
