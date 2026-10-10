"""Function-level code chunks via tree-sitter, with a line-window fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEF_NODES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "method_definition", "class_declaration",
                   "lexical_declaration"},
    "typescript": {"function_declaration", "method_definition", "class_declaration",
                   "lexical_declaration", "interface_declaration"},
    "tsx": {"function_declaration", "method_definition", "class_declaration",
            "lexical_declaration"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "java": {"method_declaration", "class_declaration", "constructor_declaration"},
}
WINDOW, OVERLAP, MAX_LINES = 60, 10, 120


@dataclass
class CodeSpan:
    symbol: str
    start_line: int  # 1-based, inclusive
    end_line: int
    text: str


def _windows(lines: list[str], symbol: str = "", offset: int = 0) -> list[CodeSpan]:
    spans, i = [], 0
    while i < len(lines):
        part = lines[i : i + WINDOW]
        spans.append(CodeSpan(symbol, offset + i + 1, offset + i + len(part), "\n".join(part)))
        if i + WINDOW >= len(lines):
            break
        i += WINDOW - OVERLAP
    return spans


def _parser(lang: str):
    try:
        import tree_sitter_language_pack as tslp

        return tslp.get_parser(lang)
    except Exception as exc:  # Grammar unavailable offline: fall back to line windows.
        log.debug("No tree-sitter grammar for %s: %s", lang, exc)
        return None


def chunk_code(source: str, lang: str) -> list[CodeSpan]:
    lines = source.splitlines()
    if not lines:
        return []
    parser = _parser(lang) if lang in DEF_NODES else None
    if parser is None:
        return _windows(lines)
    tree = parser.parse(source.encode())
    kinds = DEF_NODES[lang]
    spans: list[CodeSpan] = []
    covered: set[int] = set()

    def name_of(node) -> str:
        ident = node.child_by_field_name("name")
        return ident.text.decode(errors="replace") if ident is not None else node.type

    def visit(node, prefix: str = "") -> None:
        for child in node.children:
            target = child
            if child.type == "decorated_definition":
                target = child.child_by_field_name("definition") or child
            if target.type in kinds:
                start, end = child.start_point[0], child.end_point[0]
                symbol = f"{prefix}{name_of(target)}"
                if target.type in ("class_definition", "class_declaration") and end - start > MAX_LINES:
                    body = target.child_by_field_name("body")
                    if body is not None:
                        visit(body, prefix=f"{symbol}.")
                        continue
                text = "\n".join(lines[start : end + 1])
                if end - start + 1 > MAX_LINES:
                    spans.extend(_windows(lines[start : end + 1], symbol, start))
                else:
                    spans.append(CodeSpan(symbol, start + 1, end + 1, text))
                covered.update(range(start, end + 1))
            elif child.child_count and child.type in ("export_statement", "program", "module"):
                visit(child, prefix)

    visit(tree.root_node)
    # Module-level code outside any definition (config, constants, route tables).
    loose = [i for i in range(len(lines)) if i not in covered and lines[i].strip()]
    if loose:
        groups, cur = [], [loose[0]]
        for i in loose[1:]:
            if i - cur[-1] > 3:
                groups.append(cur)
                cur = []
            cur.append(i)
        groups.append(cur)
        for g in groups:
            a, b = g[0], g[-1]
            spans.extend(_windows(lines[a : b + 1], "<module>", a))
    return sorted(spans, key=lambda s: s.start_line)
