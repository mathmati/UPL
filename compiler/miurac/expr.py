"""The Miura expression language: parsing, name resolution, and
compilation to Python source. Used by contracts (requires/ensures),
field validation rules, computed effect values, and query filters."""

from __future__ import annotations

from dataclasses import dataclass

from .sexpr import Sym, dumps


class ExprError(Exception):
    pass


@dataclass(frozen=True)
class Lit:
    value: object  # str | int | bool


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class FieldRef:
    base: str  # a bound row name: result, current, or a row alias
    field: str


@dataclass(frozen=True)
class Call:
    op: str
    args: tuple


# op -> (min_arity, max_arity or None for variadic)
OPS = {
    "=": (2, 2),
    "!=": (2, 2),
    "<": (2, 2),
    "<=": (2, 2),
    ">": (2, 2),
    ">=": (2, 2),
    "and": (2, None),
    "or": (2, None),
    "not": (1, 1),
    "len": (1, 1),
    "+": (2, None),
    "-": (2, 2),
    "*": (2, None),
}


def parse_expr(node):
    if isinstance(node, bool) or isinstance(node, int) or (isinstance(node, str) and not isinstance(node, Sym)):
        return Lit(node)
    if isinstance(node, Sym):
        return Ref(str(node))
    if isinstance(node, list):
        if not node:
            raise ExprError("empty expression ()")
        head = node[0]
        if not isinstance(head, Sym):
            raise ExprError(f"expression head must be an operator: {dumps(node)}")
        if head == ".":
            if len(node) != 3 or not isinstance(node[1], Sym) or not isinstance(node[2], Sym):
                raise ExprError(f"field access must be (. row field): {dumps(node)}")
            return FieldRef(str(node[1]), str(node[2]))
        if head not in OPS:
            raise ExprError(f"unknown operator '{head}' in {dumps(node)}")
        lo, hi = OPS[str(head)]
        args = node[1:]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise ExprError(f"operator '{head}' takes {lo}{'' if hi == lo else '+' if hi is None else f'..{hi}'} args, got {len(args)}: {dumps(node)}")
        return Call(str(head), tuple(parse_expr(a) for a in args))
    raise ExprError(f"cannot parse expression: {node!r}")


def free_names(expr) -> set:
    """All Ref names and FieldRef base names used by the expression."""
    if isinstance(expr, Lit):
        return set()
    if isinstance(expr, Ref):
        return {expr.name}
    if isinstance(expr, FieldRef):
        return {expr.base}
    if isinstance(expr, Call):
        out = set()
        for a in expr.args:
            out |= free_names(a)
        return out
    raise AssertionError(expr)


def field_refs(expr) -> set:
    """All (base, field) pairs used by the expression."""
    if isinstance(expr, FieldRef):
        return {(expr.base, expr.field)}
    if isinstance(expr, Call):
        out = set()
        for a in expr.args:
            out |= field_refs(a)
        return out
    return set()


_PY_BINOPS = {"=": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">=", "+": "+", "-": "-", "*": "*"}


def to_python(expr, names: dict) -> str:
    """Compile to a Python expression string.

    `names` maps a UPL name to the Python expression that yields it,
    e.g. {"title": 'inp["title"]', "current": "current"}. FieldRef
    bases must map to a dict-valued Python expression."""
    if isinstance(expr, Lit):
        return repr(expr.value)
    if isinstance(expr, Ref):
        if expr.name not in names:
            raise ExprError(f"unbound name '{expr.name}'")
        return names[expr.name]
    if isinstance(expr, FieldRef):
        if expr.base not in names:
            raise ExprError(f"unbound row '{expr.base}'")
        return f'{names[expr.base]}[{expr.field!r}]'
    if isinstance(expr, Call):
        args = [to_python(a, names) for a in expr.args]
        if expr.op in _PY_BINOPS:
            return "(" + f" {_PY_BINOPS[expr.op]} ".join(args) + ")"
        if expr.op in ("and", "or"):
            return "(" + f" {expr.op} ".join(args) + ")"
        if expr.op == "not":
            return f"(not {args[0]})"
        if expr.op == "len":
            return f"len({args[0]})"
    raise AssertionError(expr)


def to_source(node) -> str:
    """Render the original s-expression for contract failure messages."""
    return dumps(node)
