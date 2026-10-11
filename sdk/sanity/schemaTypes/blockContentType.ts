/**
 * Block content — the exact shape the engine's
 * `lib/sanity_adapter.py::_markdown_to_processed_blocks` writes:
 *
 * - `block` with normal/h1-h6/blockquote styles, bullet+number lists, and
 *   strong/em/code/underline/strike-through/highlight decorators + a link
 *   annotation (markDefs `{_key, _type: "link", href}`)
 * - `image` blocks with `alt` (contextual in-post images, uploaded as assets)
 * - `code` objects `{code, language, filename}`
 * - `table` objects `{rows: [{cells: [{children: [block]}]}]}`
 *
 * Mirrors the live studio (Owais-Abdullah/sanity/schemaTypes/blockContentType.ts).
 */
import { defineType, defineArrayMember } from "sanity";
import { ImageIcon } from "@sanity/icons/Image";

export const blockContentType = defineType({
  title: "Block Content",
  name: "blockContent",
  type: "array",
  of: [
    defineArrayMember({
      type: "block",
      styles: [
        { title: "Normal", value: "normal" },
        { title: "H1", value: "h1" },
        { title: "H2", value: "h2" },
        { title: "H3", value: "h3" },
        { title: "H4", value: "h4" },
        { title: "H5", value: "h5" },
        { title: "H6", value: "h6" },
        { title: "Quote", value: "blockquote" },
      ],
      lists: [
        { title: "Bullet", value: "bullet" },
        { title: "Numbered", value: "number" },
      ],
      marks: {
        decorators: [
          { title: "Strong", value: "strong" },
          { title: "Emphasis", value: "em" },
          { title: "Code", value: "code" },
          { title: "Underline", value: "underline" },
          { title: "Strike", value: "strike-through" },
          { title: "Highlight", value: "highlight" },
        ],
        annotations: [
          {
            title: "URL",
            name: "link",
            type: "object",
            fields: [
              {
                title: "URL",
                name: "href",
                type: "url",
              },
            ],
          },
        ],
      },
    }),
    defineArrayMember({
      type: "image",
      icon: ImageIcon,
      options: { hotspot: true },
      fields: [
        {
          name: "alt",
          type: "string",
          title: "Alternative Text",
        },
      ],
    }),
    // Code block object -- matches EditorialCodeBlock and /blog/[slug]/raw
    // ({_type: "code", code, language, filename}). Multi-line code must NOT
    // live in a `block` (the renderer would collapse it into one <p> line).
    defineArrayMember({
      type: "object",
      name: "code",
      title: "Code",
      fields: [
        { name: "code", type: "text", title: "Code" },
        { name: "language", type: "string", title: "Language" },
        { name: "filename", type: "string", title: "Filename" },
      ],
    }),
    // GFM pipe tables ({_type: "table", rows: [tableRow{cells: [tableCell{children}]}]});
    // row 0 is rendered as the header row by CustomComponent.
    defineArrayMember({
      type: "object",
      name: "table",
      title: "Table",
      fields: [
        {
          name: "rows",
          type: "array",
          title: "Rows",
          of: [
            {
              type: "object",
              name: "tableRow",
              title: "Row",
              fields: [
                {
                  name: "cells",
                  type: "array",
                  title: "Cells",
                  of: [
                    {
                      type: "object",
                      name: "tableCell",
                      title: "Cell",
                      fields: [
                        {
                          name: "children",
                          type: "array",
                          title: "Content",
                          of: [{ type: "block" }],
                        },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
        },
      ],
    }),
  ],
});
