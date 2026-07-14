"""S-expression reader and canonical printer for Miura bundles.

The canonical form is the single valid serialization of a bundle:
parse + dumps is idempotent, so `sha256(dumps(parse(text)))` is a
stable identity for a program regardless of incoming formatting.
"""

from __future__ import annotations


class Sym(str):
    """A symbol atom. Distinct from a string literal (plain str)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Sym({str.__repr__(self)})"


class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"{message} at line {line}, column {col}")
        self.line = line
        self.col = col


_DELIMS = set("()\"; \t\r\n")


def parse(text: str):
    """Parse a single top-level s-expression. Raises ParseError."""
    forms = parse_all(text)
    if len(forms) != 1:
        raise ParseError(f"expected exactly 1 top-level form, found {len(forms)}", 1, 1)
    return forms[0]


def parse_all(text: str):
    tokens = _tokenize(text)
    forms = []
    pos = [0]
    while pos[0] < len(tokens):
        forms.append(_read(tokens, pos))
    return forms


def _tokenize(text: str):
    tokens = []  # (kind, value, line, col); kind in {"(", ")", "atom", "str"}
    i, line, col = 0, 1, 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            i += 1
            line += 1
            col = 1
        elif ch in " \t\r":
            i += 1
            col += 1
        elif ch == ";":
            while i < n and text[i] != "\n":
                i += 1
        elif ch in "()":
            tokens.append((ch, ch, line, col))
            i += 1
            col += 1
        elif ch == '"':
            start_line, start_col = line, col
            i += 1
            col += 1
            out = []
            while True:
                if i >= n:
                    raise ParseError("unterminated string", start_line, start_col)
                c = text[i]
                if c == '"':
                    i += 1
                    col += 1
                    break
                if c == "\\":
                    if i + 1 >= n:
                        raise ParseError("unterminated escape", line, col)
                    esc = text[i + 1]
                    mapped = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc)
                    if mapped is None:
                        raise ParseError(f"invalid escape \\{esc}", line, col)
                    out.append(mapped)
                    i += 2
                    col += 2
                elif c == "\n":
                    raise ParseError("newline in string (use \\n)", line, col)
                else:
                    out.append(c)
                    i += 1
                    col += 1
            tokens.append(("str", "".join(out), start_line, start_col))
        else:
            start_line, start_col = line, col
            j = i
            while j < n and text[j] not in _DELIMS:
                j += 1
            tokens.append(("atom", text[i:j], start_line, start_col))
            col += j - i
            i = j
    return tokens


def _read(tokens, pos):
    if pos[0] >= len(tokens):
        raise ParseError("unexpected end of input", 0, 0)
    kind, value, line, col = tokens[pos[0]]
    pos[0] += 1
    if kind == "(":
        items = []
        while True:
            if pos[0] >= len(tokens):
                raise ParseError("unclosed (", line, col)
            if tokens[pos[0]][0] == ")":
                pos[0] += 1
                return items
            items.append(_read(tokens, pos))
    if kind == ")":
        raise ParseError("unexpected )", line, col)
    if kind == "str":
        return value
    return _atom(value)


def _atom(text: str):
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        return Sym(text)


def _atom_str(node) -> str:
    if node is True:
        return "true"
    if node is False:
        return "false"
    if isinstance(node, bool):  # unreachable, kept for clarity
        raise AssertionError
    if isinstance(node, int):
        return str(node)
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        escaped = node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    raise TypeError(f"not an atom: {node!r}")


def dumps(node, indent: int = 0, width: int = 100) -> str:
    """Canonical pretty-printer: a list fits on one line if <= width,
    otherwise the head stays on the first line and each remaining item
    is printed on its own line, indented by 2."""
    flat = _flat(node)
    if len(flat) + indent <= width or not isinstance(node, list):
        return flat
    if not node:
        return "()"
    head = _flat(node[0]) if not isinstance(node[0], list) else dumps(node[0], indent + 2, width)
    lines = [f"({head}"]
    pad = " " * (indent + 2)
    for item in node[1:]:
        lines.append(pad + dumps(item, indent + 2, width))
    return "\n".join(lines) + ")"


def _flat(node) -> str:
    if isinstance(node, list):
        return "(" + " ".join(_flat(x) for x in node) + ")"
    return _atom_str(node)
