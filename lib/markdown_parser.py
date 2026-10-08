"""
Enhanced Markdown to Sanity Portable Text Converter
With comprehensive styling support, image handling, and debugging
"""
import uuid
import logging
from typing import List, Dict, Any, Optional
import commonmark
import html
import re

logger = logging.getLogger(__name__)

class MarkdownToSanityConverter:
    """Converts Markdown to Sanity Portable Text format with debugging."""
    
    def __init__(self, debug=False):
        self.blocks: List[Dict[str, Any]] = []
        self.debug = debug
        self.mark_def_counter = 0
        # Element-fidelity state
        self._list_stack: List[str] = []       # ancestor list types -> nesting level
        self._pending_images: List[Any] = []   # inline images to flush as blocks
        self._html_marks: List[str] = []       # open <u>/<s>/<del>/<mark> -> marks
    
    def _create_block_key(self) -> str:
        """Generate a unique key for Sanity blocks/spans."""
        return str(uuid.uuid4())
    
    def _get_next_mark_key(self) -> str:
        """Generate a unique key for Sanity markDefs like links."""
        self.mark_def_counter += 1
        return f"mark-def-{self.mark_def_counter}"

    def _list_type_of(self, list_node) -> str:
        """'bullet' | 'ordered'.

        commonmark-py exposes list metadata on ``node.list_data['type']``;
        the long-standing ``getattr(node, 'list_type', 'bullet')`` always
        fell back to 'bullet', which is why ordered lists in every published
        post came out as bullets.
        """
        list_data = getattr(list_node, 'list_data', None) or {}
        raw = list_data.get('type') or getattr(list_node, 'list_type', 'bullet')
        return 'ordered' if raw == 'ordered' else 'bullet'

    @staticmethod
    def _uniform_dedent(markdown_text: str) -> str:
        """Remove a UNIFORM deep indent (>=4 spaces on every non-empty line)
        without touching relative indentation, so nested lists survive.

        The old per-line ``lstrip()`` erased *all* leading whitespace and
        flattened every nested list to level 1; doing nothing instead would
        make uniformly over-indented LLM output parse as one giant code
        block. Only dedent when EVERY non-empty line is indented >= 4.
        """
        lines = markdown_text.split('\n')
        indents = []
        for line in lines:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(' '))
            indents.append(indent)
        if not indents:
            return markdown_text
        min_indent = min(indents)
        if min_indent < 4:
            return markdown_text
        return '\n'.join(
            line[min_indent:] if line.strip() else line
            for line in lines
        )
    
    def _debug_log(self, message: str):
        """Log debug messages if debug mode is enabled."""
        if self.debug:
            print(f"DEBUG: {message}")
    
    def _walk_ast_and_print(self, node, depth=0):
        """Debug function to print AST structure."""
        if not self.debug:
            return
        indent = "  " * depth
        node_info = f"{indent}{node.t}"
        if hasattr(node, 'literal') and node.literal:
            node_info += f" -> '{node.literal[:50]}'"
        if hasattr(node, 'level'):
            node_info += f" (level: {node.level})"
        if hasattr(node, 'destination'):
            node_info += f" (href: {node.destination})"
        print(node_info)
        
        # Walk children
        child = node.first_child
        while child:
            self._walk_ast_and_print(child, depth + 1)
            child = child.nxt
    
    def _extract_all_text_from_node(self, node) -> str:
        """Extract all text content from a node and its children."""
        if not node:
            return ""
        text_parts = []
        
        if node.t == 'text' and hasattr(node, 'literal'):
            text_parts.append(node.literal or "")
        elif node.t in ['softbreak', 'linebreak']:
            text_parts.append(" ")
        
        # Process children
        child = node.first_child
        while child:
            text_parts.append(self._extract_all_text_from_node(child))
            child = child.nxt
            
        return "".join(text_parts)
    
    def _create_simple_span(self, text: str, marks: Optional[List[str]] = None):
        """Create a simple span with text and marks."""
        if not text:
            return None
            
        span = {
            "_key": self._create_block_key(),
            "_type": "span",
            "text": str(text)
        }
        
        if marks and len(marks) > 0:
            span["marks"] = [mark for mark in marks if mark]
            
        return span
    
    def _parse_inline_content(self, node) -> tuple[List[Dict], List[Dict]]:
        """Parse inline content and return spans and mark definitions."""
        spans = []
        mark_defs = []
        self._html_marks = []
        
        def process_node_inline(current_node, current_marks=None):
            if current_marks is None:
                current_marks = []
            if not current_node:
                return
                
            node_type = current_node.t
            self._debug_log(f"Processing inline node: {node_type}")
            
            if node_type == 'text':
                text = getattr(current_node, 'literal', '')
                if text:
                    marks = current_marks.copy()
                    for open_mark in self._html_marks:
                        if open_mark not in marks:
                            marks.append(open_mark)
                    span = self._create_simple_span(text, marks)
                    if span:
                        spans.append(span)
                        
            elif node_type in ['softbreak', 'linebreak']:
                text = ' ' if node_type == 'softbreak' else '\n'
                span = self._create_simple_span(text, current_marks.copy())
                if span:
                    spans.append(span)
                    
            elif node_type == 'strong':
                new_marks = current_marks.copy()
                new_marks.append('strong')
                child = current_node.first_child
                while child:
                    process_node_inline(child, new_marks)
                    child = child.nxt
                    
            elif node_type == 'emph':
                new_marks = current_marks.copy()
                new_marks.append('em')
                child = current_node.first_child
                while child:
                    process_node_inline(child, new_marks)
                    child = child.nxt
                    
            elif node_type == 'code':
                text = getattr(current_node, 'literal', '')
                if text:
                    new_marks = current_marks.copy()
                    new_marks.append('code')
                    span = self._create_simple_span(text, new_marks)
                    if span:
                        spans.append(span)
                        
            elif node_type == 'link':
                destination = getattr(current_node, 'destination', '')
                title = getattr(current_node, 'title', '')
                # Validate that destination is a proper URL
                if destination:
                    # Check if URL is properly formatted
                    if not destination.startswith(('http://', 'https://', '/', '#', 'mailto:', 'tel:')):
                        # If not a proper URL, treat as text instead of link
                        child = current_node.first_child
                        while child:
                            process_node_inline(child, current_marks)
                            child = child.nxt
                    else:
                        mark_key = self._get_next_mark_key()
                        mark_def = {
                            "_key": mark_key,
                            "_type": "link",
                            "href": destination
                        }
                        if title:
                            mark_def["title"] = title
                        mark_defs.append(mark_def)
                        
                        new_marks = current_marks.copy()
                        new_marks.append(mark_key)
                        child = current_node.first_child
                        while child:
                            process_node_inline(child, new_marks)
                            child = child.nxt
                else:
                    # Process children without link mark
                    child = current_node.first_child
                    while child:
                        process_node_inline(child, current_marks)
                        child = child.nxt
                        
            elif node_type == 'strikethrough':
                new_marks = current_marks.copy()
                new_marks.append('strike-through')
                child = current_node.first_child
                while child:
                    process_node_inline(child, new_marks)
                    child = child.nxt
                    
            elif node_type == 'html_inline':
                # commonmark tokenizes inline HTML as SEPARATE open/close
                # tokens (`<u>` ... `</u>`), never one literal -- so track an
                # open-tag stack and stamp its marks onto following text.
                literal = getattr(current_node, 'literal', '')
                tag = (literal or '').strip().lower()
                open_tags = {
                    '<u>': 'underline',
                    '<s>': 'strike-through',
                    '<del>': 'strike-through',
                    '<mark>': 'highlight',
                }
                close_tags = {
                    '</u>': 'underline',
                    '</s>': 'strike-through',
                    '</del>': 'strike-through',
                    '</mark>': 'highlight',
                }
                if tag in open_tags:
                    if open_tags[tag] not in self._html_marks:
                        self._html_marks.append(open_tags[tag])
                elif tag in close_tags:
                    mark = close_tags[tag]
                    if mark in self._html_marks:
                        self._html_marks.remove(mark)
                elif tag in ('<br>', '<br/>', '<br />'):
                    span = self._create_simple_span('\n', current_marks.copy())
                    if span:
                        spans.append(span)
                elif literal:
                    # Unknown inline HTML: keep it visible as text rather
                    # than silently dropping the fragment.
                    span = self._create_simple_span(str(literal), current_marks.copy())
                    if span:
                        spans.append(span)
                        
            elif node_type == 'image':
                # Inline image mid-paragraph: remember it and emit a real
                # image block when the paragraph is flushed (the old literal
                # ![alt](url) placeholder span rendered as raw markdown text
                # on the site).
                self._pending_images.append(current_node)
                        
            else:
                # For unknown inline types, process children
                child = current_node.first_child
                while child:
                    process_node_inline(child, current_marks)
                    child = child.nxt
        
        # Start processing from the given node
        if node.t in ['paragraph', 'heading', 'block_quote']:
            # Process children of block elements
            child = node.first_child
            while child:
                process_node_inline(child)
                child = child.nxt
        else:
            # Process the node itself
            process_node_inline(node)
            
        self._debug_log(f"Generated {len(spans)} spans and {len(mark_defs)} mark definitions")
        return spans, mark_defs
    
    def _create_block(self, style: str, spans: List[Dict], mark_defs: List[Dict] = None):
        """Create a Sanity block."""
        return {
            "_key": self._create_block_key(),
            "_type": "block",
            "children": spans or [],
            "markDefs": mark_defs or [],
            "style": style
        }
    
    def _process_node(self, node):
        """Process a single node and convert to Sanity blocks."""
        if not node:
            return
            
        node_type = node.t
        self._debug_log(f"Processing block node: {node_type}")
        
        if node_type == 'document':
            # Process all children
            child = node.first_child
            while child:
                self._process_node(child)
                child = child.nxt
                
        elif node_type == 'paragraph':
            # Check if this paragraph contains only an image
            child = node.first_child
            if (child and child.t == 'image' and 
                not child.nxt and  # Only child
                hasattr(child, 'destination')):
                # This is an image paragraph, create an image block
                self._create_image_block(child)
            else:
                # Regular paragraph
                spans, mark_defs = self._parse_inline_content(node)
                if spans:
                    block = self._create_block('normal', spans, mark_defs)
                    self.blocks.append(block)
                    self._debug_log(f"Added paragraph block with {len(spans)} spans")
                else:
                    # Fallback: extract all text as plain text
                    text = self._extract_all_text_from_node(node)
                    if text.strip():
                        fallback_span = self._create_simple_span(text.strip())
                        if fallback_span:
                            block = self._create_block('normal', [fallback_span])
                            self.blocks.append(block)
                            self._debug_log(f"Added fallback paragraph block")
                # Inline images captured during parsing -> real image blocks
                # positioned directly after the paragraph they appeared in.
                for image_node in self._pending_images:
                    self._create_image_block(image_node)
                self._pending_images = []
                            
        elif node_type == 'heading':
            level = getattr(node, 'level', 1)
            style = f"h{min(max(level, 1), 6)}"
            spans, mark_defs = self._parse_inline_content(node)
            if spans:
                block = self._create_block(style, spans, mark_defs)
                self.blocks.append(block)
                self._debug_log(f"Added {style} heading block with {len(spans)} spans")
            else:
                # Fallback for headings
                text = self._extract_all_text_from_node(node)
                if text.strip():
                    fallback_span = self._create_simple_span(text.strip())
                    if fallback_span:
                        block = self._create_block(style, [fallback_span])
                        self.blocks.append(block)
                        self._debug_log(f"Added fallback {style} heading block")
                        
        elif node_type == 'block_quote':
            spans, mark_defs = self._parse_inline_content(node)
            if spans:
                block = self._create_block('blockquote', spans, mark_defs)
                self.blocks.append(block)
                self._debug_log(f"Added blockquote block")
            else:
                text = self._extract_all_text_from_node(node)
                if text.strip():
                    fallback_span = self._create_simple_span(text.strip())
                    if fallback_span:
                        block = self._create_block('blockquote', [fallback_span])
                        self.blocks.append(block)
                        
        elif node_type == 'code_block':
            literal = getattr(node, 'literal', '')
            info = getattr(node, 'info', '')
            if literal is not None:
                code_text = literal.rstrip('\n') if isinstance(literal, str) else str(literal)
                if code_text:
                    # Emit the dedicated `code` object type the site's
                    # renderer (EditorialCodeBlock) and /raw route already
                    # expect: {code, language, filename}. The old shape
                    # (normal block + code-marked span + language) collapsed
                    # multi-line code into one <p> line on the site.
                    language = (info or '').split()[0] if info else ''
                    block = {
                        "_key": self._create_block_key(),
                        "_type": "code",
                        "code": code_text,
                    }
                    if language:
                        block["language"] = language
                    self.blocks.append(block)
                    self._debug_log(f"Added code block (language={language or 'none'})")
                        
        elif node_type == 'list':
            # Process list items with proper list type detection; the stack
            # drives nesting level so nested lists render as sub-lists on the
            # site (@portabletext/react nests by level) instead of flattening.
            self._list_stack.append(self._list_type_of(node))
            child = node.first_child
            while child:
                self._process_node(child)
                child = child.nxt
            self._list_stack.pop()

        elif node_type == 'item':
            # Inline children of THIS item only; nested lists are collected
            # and processed AFTER this item's block so document order is
            # preserved (parent item, then its sub-list).
            spans: List[Dict] = []
            mark_defs: List[Dict] = []
            nested_lists = []
            child = node.first_child
            while child:
                if child.t == 'list':
                    nested_lists.append(child)
                else:
                    child_spans, child_mark_defs = self._parse_inline_content(child)
                    spans.extend(child_spans)
                    mark_defs.extend(child_mark_defs)
                child = child.nxt

            list_type = 'bullet'
            parent = node.parent
            if parent and parent.t == 'list':
                list_type = self._list_type_of(parent)

            if spans:
                block = self._create_block('normal', spans, mark_defs)
                block["listItem"] = "number" if list_type == 'ordered' else "bullet"
                if len(self._list_stack) > 1:
                    block["level"] = len(self._list_stack)
                self.blocks.append(block)
                self._debug_log(
                    f"Added list item block (type={block['listItem']}, "
                    f"level={block.get('level', 1)})"
                )
            else:
                # Fallback: extract text from THIS item's non-list children
                # (never the nested list's text -- it becomes its own blocks)
                # and keep list identity; the old fallback dropped listItem,
                # turning items into plain paragraphs.
                text_parts = []
                part = node.first_child
                while part:
                    if part.t != 'list':
                        text_parts.append(self._extract_all_text_from_node(part))
                    part = part.nxt
                text = "".join(text_parts)
                if text.strip():
                    text_span = self._create_simple_span(text.strip())
                    if text_span:
                        block = self._create_block('normal', [text_span])
                        block["listItem"] = "number" if list_type == 'ordered' else "bullet"
                        if len(self._list_stack) > 1:
                            block["level"] = len(self._list_stack)
                        self.blocks.append(block)

            for nested_list in nested_lists:
                self._process_node(nested_list)
                        
        elif node_type == 'thematic_break':
            span = self._create_simple_span('---')
            if span:
                block = self._create_block('normal', [span])
                self.blocks.append(block)
                self._debug_log(f"Added thematic break block")
                
        elif node_type == 'image':
            # Handle standalone image nodes
            self._create_image_block(node)
                
        elif node_type == 'link':
            # Handle standalone link nodes (though these should be rare in CommonMark)
            # Usually links will be processed as inline elements within blocks
            spans, mark_defs = self._parse_inline_content(node)
            if spans:
                block = self._create_block('normal', spans, mark_defs)
                self.blocks.append(block)
                
        else:
            # For unknown block types, try to extract text
            text = self._extract_all_text_from_node(node)
            if text.strip():
                span = self._create_simple_span(text.strip())
                if span:
                    block = self._create_block('normal', [span])
                    self.blocks.append(block)
                    self._debug_log(f"Added unknown block type: {node_type}")
    
    def _create_image_block(self, image_node):
        """Create a Sanity image block from a markdown image node."""
        destination = getattr(image_node, 'destination', '')
        title = getattr(image_node, 'title', '')
        alt_text = ''
        
        # Extract alt text from the first child if it's text
        if image_node.first_child and image_node.first_child.t == 'text':
            alt_text = getattr(image_node.first_child, 'literal', '')
        
        if destination:
            # Create image block with URL directly (Sanity adapter will process this)
            image_block = {
                "_key": self._create_block_key(),
                "_type": "image",
                "asset": {
                    "url": destination
                }
            }
            
            # Add alt text if available
            if alt_text:
                image_block["alt"] = alt_text
                
            # Add title if available
            if title:
                image_block["title"] = title
                
            self.blocks.append(image_block)
            self._debug_log(f"Added image block: {destination}")
    
    def _preprocess_extensions(self, markdown_text: str) -> str:
        """GFM/HTML extensions commonmark-py doesn't parse natively.

        Only applied OUTSIDE fenced code blocks so code samples stay literal:
        - ``==text==``  -> ``<mark>text</mark>`` (site renders `highlight`)
        - ``~~text~~``  -> ``<s>text</s>``      (site renders `strike-through`)
        """
        lines = markdown_text.split('\n')
        out: List[str] = []
        in_fence = False
        fence_marker = ''
        for line in lines:
            stripped = line.lstrip()
            if not in_fence and (stripped.startswith('```') or stripped.startswith('~~~')):
                in_fence = True
                fence_marker = stripped[:3]
                out.append(line)
                continue
            if in_fence and stripped.startswith(fence_marker):
                in_fence = False
                out.append(line)
                continue
            if in_fence:
                out.append(line)
                continue
            line = re.sub(r'==([^=\n]+?)==', r'<mark>\1</mark>', line)
            line = re.sub(r'~~([^~\n]+?)~~', r'<s>\1</s>', line)
            out.append(line)
        return '\n'.join(out)

    def _parse_cell_spans(self, text: str, key_prefix: str) -> List[Dict[str, Any]]:
        """Minimal inline parse for table cells: bold, italic, code, highlight."""
        spans: List[Dict[str, Any]] = []
        token = re.compile(r'(\*\*(.+?)\*\*|(?<!\*)\*([^*\n]+?)\*(?!\*)|`([^`\n]+?)`|<mark>(.+?)</mark>)')
        pos = 0
        counter = 0

        def add_span(value: str, marks: List[str]):
            nonlocal counter
            if not value:
                return
            span = {
                "_key": f"{key_prefix}-{counter}",
                "_type": "span",
                "text": value,
            }
            counter += 1
            if marks:
                span["marks"] = list(marks)
            spans.append(span)

        for match in token.finditer(text):
            add_span(text[pos:match.start()], [])
            if match.group(2) is not None:
                add_span(match.group(2), ['strong'])
            elif match.group(3) is not None:
                add_span(match.group(3), ['em'])
            elif match.group(4) is not None:
                add_span(match.group(4), ['code'])
            elif match.group(5) is not None:
                add_span(match.group(5), ['highlight'])
            pos = match.end()
        add_span(text[pos:], [])
        if not spans:
            add_span('', [])
        return spans

    def _build_table_block(self, rows: List[List[str]]) -> Dict[str, Any]:
        """GFM pipe table -> Sanity table object (site schema + renderer).

        Structure: {type: table, rows: [{type: tableRow, cells: [{type:
        tableCell, children: [block...]}]}]} -- cells hold a single `block`
        child (array-of-block, Studio-schema-shaped); row 0 is the header.
        """
        table_rows = []
        for r_idx, row in enumerate(rows):
            cells = []
            for c_idx, cell_text in enumerate(row):
                spans = self._parse_cell_spans(
                    cell_text.strip(), f"t{self.mark_def_counter}-{r_idx}-{c_idx}"
                )
                cells.append({
                    "_key": f"cell-{self._create_block_key()}",
                    "_type": "tableCell",
                    "children": [self._create_block('normal', spans, [])],
                })
            table_rows.append({
                "_key": f"row-{self._create_block_key()}",
                "_type": "tableRow",
                "cells": cells,
            })
        return {
            "_key": self._create_block_key(),
            "_type": "table",
            "rows": table_rows,
        }

    def _extract_tables(self, markdown_text: str) -> tuple:
        """Pull GFM pipe tables out of the markdown (commonmark-py has no
        table extension) and leave numbered placeholder paragraphs behind;
        after block conversion the placeholders are swapped for table blocks.
        Returns (text_without_tables, table_blocks).
        """
        lines = markdown_text.split('\n')
        out: List[str] = []
        tables: List[Dict[str, Any]] = []
        placeholders: Dict[str, Dict[str, Any]] = {}
        i = 0
        sep_re = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$')

        def split_row(line: str) -> List[str]:
            line = line.strip()
            if line.startswith('|'):
                line = line[1:]
            if line.endswith('|'):
                line = line[:-1]
            return [c.strip() for c in line.split('|')]

        while i < len(lines):
            line = lines[i]
            if ('|' in line and i + 1 < len(lines)
                    and sep_re.match(lines[i + 1] or '')
                    and '-' in lines[i + 1]):
                header = split_row(line)
                i += 2
                body: List[List[str]] = [header]
                while i < len(lines) and '|' in lines[i] and lines[i].strip():
                    body.append(split_row(lines[i]))
                    i += 1
                table_block = self._build_table_block(body)
                placeholder = f"TABL€PLACEHOLD€R{len(tables)}"
                placeholders[placeholder] = table_block
                # Placeholder must be its own paragraph for clean swapping
                out.append('')
                out.append(placeholder)
                out.append('')
                tables.append(table_block)
                continue
            out.append(line)
            i += 1
        return '\n'.join(out), list(placeholders.values()), placeholders

    def _swap_table_placeholders(self, placeholders: Dict[str, Dict[str, Any]]):
        """Replace placeholder paragraphs with their table blocks in order."""
        if not placeholders:
            return
        for idx, block in enumerate(self.blocks):
            if block.get('_type') != 'block' or block.get('style') != 'normal':
                continue
            children = block.get('children') or []
            text = ''.join(c.get('text', '') for c in children)
            if text in placeholders:
                self.blocks[idx] = placeholders[text]
                del placeholders[text]
        for leftover in placeholders.values():
            self.blocks.append(leftover)

    def convert(self, markdown_text: str, debug: bool = False) -> List[Dict[str, Any]]:
        """Convert markdown text to Sanity blocks."""
        if not markdown_text or not isinstance(markdown_text, str) or not markdown_text.strip():
            return []
            
        self.debug = debug
        try:
            # Reset state
            self.blocks = []
            self.mark_def_counter = 0
            self._list_stack = []
            self._pending_images = []
            self._html_marks = []
            self._debug_log(f"Starting conversion of {len(markdown_text)} characters")
            
            # Clean the content: uniform deep indent (>=4 everywhere) is
            # removed; relative indentation (nested lists) is preserved.
            if markdown_text:
                cleaned_content = self._uniform_dedent(markdown_text).strip()
            else:
                cleaned_content = ""

            # GFM/HTML extensions commonmark-py can't parse (==highlight==,
            # ~~strike~~) then pull pipe tables out before the CommonMark pass
            # (they'd otherwise land as literal-pipe paragraphs).
            cleaned_content = self._preprocess_extensions(cleaned_content)
            cleaned_content, _tables, table_placeholders = self._extract_tables(cleaned_content)

            self._debug_log(f"Original content length: {len(markdown_text)}")
            self._debug_log(f"Cleaned content length: {len(cleaned_content)}")
            
            # Parse markdown with CommonMark
            parser = commonmark.Parser()
            ast = parser.parse(cleaned_content)
            
            if self.debug:
                print("\n=== AST STRUCTURE ===")
                self._walk_ast_and_print(ast)
                print("=== END AST ===\n")
            
            # Convert to Sanity blocks
            if ast:
                self._process_node(ast)

            # Swap table placeholder paragraphs for real table blocks
            self._swap_table_placeholders(table_placeholders)
                
            self._debug_log(f"Successfully converted to {len(self.blocks)} Sanity blocks")
            
            if len(self.blocks) == 0:
                self._debug_log("No blocks generated, creating fallback")
                # Create fallback block with original text
                fallback_span = self._create_simple_span(markdown_text)
                if fallback_span:
                    fallback_block = self._create_block('normal', [fallback_span])
                    self.blocks.append(fallback_block)
                    
            return self.blocks
            
        except Exception as e:
            logger.error(f"Error converting markdown to Sanity blocks: {e}", exc_info=True)
            # Return error block
            error_span = self._create_simple_span(f"[Conversion Error: {str(e)}]")
            if error_span:
                error_block = self._create_block('normal', [error_span])
                return [error_block]
            return []

def markdown_to_sanity_blocks(markdown_text: str, debug: bool = False) -> List[Dict[str, Any]]:
    """
    Convert Markdown text to Sanity's blockContent (Portable Text) structure.
    
    Args:
        markdown_text (str): The markdown content to convert
        debug (bool): Enable debug logging to see what's happening
        
    Returns:
        List[Dict[str, Any]]: List of Sanity block objects
    """
    converter = MarkdownToSanityConverter(debug=debug)
    return converter.convert(markdown_text, debug=debug)

# Example usage and testing
if __name__ == "__main__":
    import json
    
    # Test markdown with all supported features
    test_markdown = """# Main Heading
This is a **bold** paragraph with *italic* text and a ~~strikethrough~~ and <u>underline</u>.

## Subheading
Here's a list:
- Item 1 with `inline code`
- Item 2 with more text

![Alt text for image](https://example.com/test-image.jpg "Image title")

> This is a blockquote with **bold** text.

Final paragraph with some text.

![Another image](/local/path/image.png)

```python
a + b = c
a = 10
```
"""
    
    print("Testing markdown conversion with images...")
    blocks = markdown_to_sanity_blocks(test_markdown, debug=True)
    print(f"\nGenerated {len(blocks)} blocks:")
    print(json.dumps(blocks, indent=2))