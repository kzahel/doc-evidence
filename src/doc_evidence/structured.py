"""Normalize current Docling and Marker JSON into page text."""

from __future__ import annotations

import html
import re
from collections import defaultdict
from html.parser import HTMLParser
from typing import Any

from doc_evidence.extraction import NormalizedPage
from doc_evidence.util import non_whitespace_character_count


class _TextHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")


def strip_html(value: str) -> str:
    parser = _TextHtmlParser()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", html.unescape("".join(parser.parts))).strip()


def _page_number(item: dict[str, Any], fallback: int = 1) -> int:
    page_id = item.get("page_id")
    if isinstance(page_id, int):
        return page_id + 1 if page_id >= 0 else fallback
    item_id = item.get("id")
    if isinstance(item_id, str):
        match = re.search(r"(?:^|/)page/(\d+)(?:/|$)", item_id, re.IGNORECASE)
        if match:
            return int(match.group(1)) + 1
    prov = item.get("prov")
    if isinstance(prov, list) and prov and isinstance(prov[0], dict):
        raw = prov[0].get("page_no")
        if isinstance(raw, int):
            return raw
    return fallback


def _make_pages(
    page_text: dict[int, list[str]], page_count: int
) -> tuple[NormalizedPage, ...]:
    pages = []
    for page_number in range(1, max(page_count, max(page_text, default=0)) + 1):
        text = "\n\n".join(part for part in page_text[page_number] if part.strip())
        pages.append(
            NormalizedPage(
                page_number=page_number,
                text=text,
                character_count=len(text),
                non_whitespace_character_count=non_whitespace_character_count(text),
            )
        )
    return tuple(pages)


def _resolve_json_pointer(root: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        return None
    current: Any = root
    for part in pointer[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def docling_pages(document: dict[str, Any]) -> tuple[tuple[NormalizedPage, ...], int]:
    """Traverse Docling's body references and retain page provenance."""

    page_text: dict[int, list[str]] = defaultdict(list)
    seen_refs: set[str] = set()
    table_count = (
        len(document.get("tables", []))
        if isinstance(document.get("tables"), list)
        else 0
    )

    def table_text(item: dict[str, Any]) -> str:
        data = item.get("data")
        if not isinstance(data, dict):
            return ""
        cells = data.get("table_cells") or data.get("grid")
        if not isinstance(cells, list):
            return ""
        rows: dict[int, dict[int, str]] = defaultdict(dict)
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            row = cell.get("start_row_offset_idx", cell.get("row", 0))
            col = cell.get("start_col_offset_idx", cell.get("col", 0))
            value = cell.get("text", "")
            if isinstance(row, int) and isinstance(col, int) and isinstance(value, str):
                rows[row][col] = value
        return "\n".join(
            "\t".join(columns[index] for index in sorted(columns))
            for _, columns in sorted(rows.items())
        )

    def visit(item: Any, inherited_page: int = 1) -> None:
        if not isinstance(item, dict):
            return
        ref = item.get("$ref") or item.get("self_ref")
        if isinstance(ref, str) and "$ref" in item:
            if ref in seen_refs:
                return
            seen_refs.add(ref)
            target = _resolve_json_pointer(document, ref)
            visit(target, inherited_page)
            return
        page_number = _page_number(item, inherited_page)
        label = str(item.get("label", ""))
        value = item.get("text")
        if not isinstance(value, str) or not value.strip():
            value = table_text(item) if label == "table" else ""
        if value.strip():
            page_text[page_number].append(value.strip())
        children = item.get("children")
        if isinstance(children, list):
            for child in children:
                visit(child, page_number)

    body = document.get("body")
    if isinstance(body, dict):
        visit(body)
    if not any(page_text.values()):
        for collection in ("texts", "tables", "pictures", "key_value_items"):
            items = document.get(collection)
            if isinstance(items, list):
                for item in items:
                    visit(item)

    pages_value = document.get("pages")
    page_count = (
        len(pages_value)
        if isinstance(pages_value, (dict, list))
        else max(page_text, default=0)
    )
    return _make_pages(page_text, page_count), table_count


def marker_pages(document: dict[str, Any]) -> tuple[tuple[NormalizedPage, ...], int]:
    """Traverse Marker's block tree and normalize leaf HTML by page."""

    page_text: dict[int, list[str]] = defaultdict(list)
    table_count = 0

    def visit(item: Any, inherited_page: int = 1) -> None:
        nonlocal table_count
        if not isinstance(item, dict):
            return
        page_number = _page_number(item, inherited_page)
        block_type = str(item.get("block_type", item.get("type", ""))).lower()
        if "table" in block_type and "cell" not in block_type:
            table_count += 1
        children = item.get("children")
        if isinstance(children, list) and children:
            for child in children:
                visit(child, page_number)
            return
        value = item.get("html") or item.get("text") or item.get("markdown")
        if isinstance(value, str) and value.strip():
            cleaned = strip_html(value) if "<" in value else value.strip()
            if cleaned:
                page_text[page_number].append(cleaned)

    visit(document)
    page_count = max(page_text, default=0)
    children = document.get("children")
    if isinstance(children, list):
        page_blocks = [
            item
            for item in children
            if isinstance(item, dict)
            and str(item.get("block_type", "")).lower() == "page"
        ]
        page_count = max(page_count, len(page_blocks))
    return _make_pages(page_text, page_count), table_count
