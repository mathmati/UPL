"""The UPL v0.1 bundle model: dataclasses, the loader from
s-expressions, and whole-bundle validation.

A bundle is:

  (upl 0.1
    (intent "...")
    (schema (entity ...) ...)
    (workflow (action ...) (query ...) ...)
    (ui (page ...) ...))
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dc_field

from . import expr as E
from .sexpr import Sym, dumps, parse

TYPES = ("id", "text", "int", "bool", "timestamp")
AUTO_TYPES = ("id", "timestamp")


class BundleError(Exception):
    """A validation error, with a path into the bundle for context."""

    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


@dataclass
class Field:
    name: str
    type: str
    auto: bool = False
    default: object = None
    has_default: bool = False
    require: object = None  # parsed expr
    require_src: str = ""


@dataclass
class Entity:
    name: str
    fields: list


@dataclass
class Insert:
    entity: str
    assigns: list  # [(field, expr, src)]


@dataclass
class Update:
    entity: str
    id_expr: object
    assigns: list  # [(field, expr, src)]


@dataclass
class Delete:
    entity: str
    id_expr: object


@dataclass
class Action:
    name: str
    inputs: list  # [(name, type)]
    requires: list  # [(expr, src)]
    effect: object  # Insert | Update | Delete
    ensures: list  # [(expr, src)]


@dataclass
class Query:
    name: str
    entity: str
    where: object = None  # parsed expr or None
    where_src: str = ""
    order_by: object = None  # (field, "asc"|"desc") or None


@dataclass
class Heading:
    text: str


@dataclass
class FormField:
    name: str
    label: str


@dataclass
class Form:
    action: str
    fields: list  # [FormField]


@dataclass
class Text:
    field: str


@dataclass
class Checkbox:
    bind: str
    action: str
    args: list  # [(input_name, row_field)]


@dataclass
class Button:
    label: str
    action: str
    args: list  # [(input_name, row_field)]


@dataclass
class List:
    query: str
    item: list  # item components


@dataclass
class Page:
    name: str
    route: str
    components: list


@dataclass
class App:
    intent: str
    entities: list
    actions: list
    queries: list
    pages: list
    canonical: str = ""
    bundle_hash: str = ""

    def entity(self, name):
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def action(self, name):
        for a in self.actions:
            if a.name == name:
                return a
        return None

    def query(self, name):
        for q in self.queries:
            if q.name == name:
                return q
        return None


def load(text: str) -> App:
    """Parse + validate a bundle. Raises BundleError / ParseError."""
    tree = parse(text)
    app = _load_tree(tree)
    _validate(app)
    app.canonical = dumps(tree) + "\n"
    app.bundle_hash = hashlib.sha256(app.canonical.encode("utf-8")).hexdigest()
    return app


def _expect(cond, path, message):
    if not cond:
        raise BundleError(path, message)


def _sym(node, path, what) -> str:
    _expect(isinstance(node, Sym), path, f"{what} must be a symbol, got {node!r}")
    return str(node)


def _str(node, path, what) -> str:
    _expect(isinstance(node, str) and not isinstance(node, Sym), path, f'{what} must be a string literal, got {node!r}')
    return node


def _sections(items, path, allowed):
    out = {}
    for item in items:
        _expect(isinstance(item, list) and item and isinstance(item[0], Sym), path, f"expected a ({'/'.join(allowed)} ...) form, got {dumps(item)}")
        key = str(item[0])
        _expect(key in allowed, path, f"unknown section '{key}' (allowed: {', '.join(allowed)})")
        out.setdefault(key, []).append(item)
    return out


def _load_tree(tree) -> App:
    path = "bundle"
    _expect(isinstance(tree, list) and len(tree) >= 2 and tree[0] == Sym("upl"), path, "bundle must start with (upl 0.1 ...)")
    _expect(str(tree[1]) == "0.1", path, f"unsupported version {tree[1]!r}, expected 0.1")
    sections = _sections(tree[2:], path, ["intent", "schema", "workflow", "ui"])
    for required in ("intent", "schema", "workflow", "ui"):
        _expect(required in sections, path, f"missing ({required} ...) section")
        _expect(len(sections[required]) == 1, path, f"duplicate ({required} ...) section")

    intent = _str(sections["intent"][0][1] if len(sections["intent"][0]) == 2 else None, "intent", "intent")

    entities = [_load_entity(e) for e in _sections(sections["schema"][0][1:], "schema", ["entity"]).get("entity", [])]

    wf = _sections(sections["workflow"][0][1:], "workflow", ["action", "query"])
    actions = [_load_action(a) for a in wf.get("action", [])]
    queries = [_load_query(q) for q in wf.get("query", [])]

    pages = [_load_page(p) for p in _sections(sections["ui"][0][1:], "ui", ["page"]).get("page", [])]

    return App(intent=intent, entities=entities, actions=actions, queries=queries, pages=pages)


def _load_entity(node) -> Entity:
    path = "schema"
    _expect(len(node) >= 2, path, "entity needs a name")
    name = _sym(node[1], path, "entity name")
    path = f"entity {name}"
    fields = []
    for f in _sections(node[2:], path, ["field"]).get("field", []):
        _expect(len(f) >= 3, path, f"field needs a name and a (type): {dumps(f)}")
        fname = _sym(f[1], path, "field name")
        fpath = f"{path}.{fname}"
        _expect(isinstance(f[2], list) and len(f[2]) == 1, fpath, f"field type must be a (type) form, got {dumps(f[2])}")
        ftype = _sym(f[2][0], fpath, "field type")
        _expect(ftype in TYPES, fpath, f"unknown type '{ftype}' (allowed: {', '.join(TYPES)})")
        fld = Field(name=fname, type=ftype)
        for opt in f[3:]:
            _expect(isinstance(opt, list) and opt and isinstance(opt[0], Sym), fpath, f"bad field option {dumps(opt)}")
            key = str(opt[0])
            if key == "auto":
                _expect(len(opt) == 1, fpath, "(auto) takes no arguments")
                _expect(ftype in AUTO_TYPES, fpath, f"(auto) only applies to types {', '.join(AUTO_TYPES)}")
                fld.auto = True
            elif key == "default":
                _expect(len(opt) == 2, fpath, "(default value) takes one literal")
                _expect(not isinstance(opt[1], (list, Sym)), fpath, "default must be a literal")
                fld.default = opt[1]
                fld.has_default = True
            elif key == "require":
                _expect(len(opt) == 2, fpath, "(require expr) takes one expression")
                try:
                    fld.require = E.parse_expr(opt[1])
                except E.ExprError as err:
                    raise BundleError(fpath, str(err))
                fld.require_src = E.to_source(opt[1])
            else:
                raise BundleError(fpath, f"unknown field option '{key}'")
        fields.append(fld)
    return Entity(name=name, fields=fields)


def _load_assigns(items, path):
    assigns = []
    for a in items:
        _expect(isinstance(a, list) and len(a) == 2 and isinstance(a[0], Sym), path, f"assignment must be (field expr): {dumps(a)}")
        try:
            assigns.append((str(a[0]), E.parse_expr(a[1]), E.to_source(a[1])))
        except E.ExprError as err:
            raise BundleError(path, str(err))
    return assigns


def _load_action(node) -> Action:
    path = "workflow"
    _expect(len(node) >= 2, path, "action needs a name")
    name = _sym(node[1], path, "action name")
    path = f"action {name}"
    sections = _sections(node[2:], path, ["input", "requires", "effect", "ensures"])
    _expect("effect" in sections and len(sections["effect"]) == 1, path, "action needs exactly one (effect ...)")

    inputs = []
    for inp in sections.get("input", []):
        for spec in inp[1:]:
            _expect(isinstance(spec, list) and len(spec) == 2, path, f"input must be (name type): {dumps(spec)}")
            iname = _sym(spec[0], path, "input name")
            itype = _sym(spec[1], path, "input type")
            _expect(itype in TYPES, path, f"unknown input type '{itype}'")
            inputs.append((iname, itype))

    def _load_contracts(key):
        out = []
        for c in sections.get(key, []):
            _expect(len(c) == 2, path, f"({key} expr) takes one expression")
            try:
                out.append((E.parse_expr(c[1]), E.to_source(c[1])))
            except E.ExprError as err:
                raise BundleError(path, str(err))
        return out

    requires = _load_contracts("requires")
    ensures = _load_contracts("ensures")

    eff = sections["effect"][0]
    _expect(len(eff) == 2 and isinstance(eff[1], list) and eff[1] and isinstance(eff[1][0], Sym), path, "effect must be (effect (insert|update|delete ...))")
    ef = eff[1]
    kind = str(ef[0])
    if kind == "insert":
        _expect(len(ef) >= 2, path, "(insert Entity (field expr)...)")
        effect = Insert(entity=_sym(ef[1], path, "entity"), assigns=_load_assigns(ef[2:], path))
    elif kind == "update":
        _expect(len(ef) >= 3, path, "(update Entity id-expr (field expr)...)")
        try:
            id_expr = E.parse_expr(ef[2])
        except E.ExprError as err:
            raise BundleError(path, str(err))
        effect = Update(entity=_sym(ef[1], path, "entity"), id_expr=id_expr, assigns=_load_assigns(ef[3:], path))
    elif kind == "delete":
        _expect(len(ef) == 3, path, "(delete Entity id-expr)")
        try:
            id_expr = E.parse_expr(ef[2])
        except E.ExprError as err:
            raise BundleError(path, str(err))
        effect = Delete(entity=_sym(ef[1], path, "entity"), id_expr=id_expr)
    else:
        raise BundleError(path, f"unknown effect '{kind}' (allowed: insert, update, delete)")

    return Action(name=name, inputs=inputs, requires=requires, effect=effect, ensures=ensures)


def _load_query(node) -> Query:
    path = "workflow"
    _expect(len(node) >= 2, path, "query needs a name")
    name = _sym(node[1], path, "query name")
    path = f"query {name}"
    sections = _sections(node[2:], path, ["from", "where", "order-by"])
    _expect("from" in sections and len(sections["from"]) == 1 and len(sections["from"][0]) == 2, path, "query needs exactly one (from Entity)")
    q = Query(name=name, entity=_sym(sections["from"][0][1], path, "entity"))
    if "where" in sections:
        _expect(len(sections["where"]) == 1 and len(sections["where"][0]) == 2, path, "(where expr) takes one expression")
        try:
            q.where = E.parse_expr(sections["where"][0][1])
        except E.ExprError as err:
            raise BundleError(path, str(err))
        q.where_src = E.to_source(sections["where"][0][1])
    if "order-by" in sections:
        ob = sections["order-by"][0]
        _expect(len(ob) == 3 and str(ob[2]) in ("asc", "desc"), path, "(order-by field asc|desc)")
        q.order_by = (_sym(ob[1], path, "order-by field"), str(ob[2]))
    return q


def _load_args(items, path):
    args = []
    for a in items:
        _expect(isinstance(a, list) and len(a) == 2 and isinstance(a[0], Sym) and isinstance(a[1], Sym), path, f"action arg must be (input-name row-field): {dumps(a)}")
        args.append((str(a[0]), str(a[1])))
    return args


def _load_component(node, path):
    _expect(isinstance(node, list) and node and isinstance(node[0], Sym), path, f"bad component {dumps(node)}")
    kind = str(node[0])
    if kind == "heading":
        _expect(len(node) == 2, path, "(heading \"text\")")
        return Heading(text=_str(node[1], path, "heading text"))
    if kind == "form":
        sections = _sections(node[1:], path, ["action", "field"])
        _expect("action" in sections and len(sections["action"][0]) == 2, path, "form needs (action name)")
        fields = []
        for f in sections.get("field", []):
            _expect(len(f) >= 2, path, "form field needs a name")
            fname = _sym(f[1], path, "form field name")
            label = fname
            for opt in f[2:]:
                _expect(isinstance(opt, list) and len(opt) == 2 and opt[0] == Sym("label"), path, f"bad form field option {dumps(opt)}")
                label = _str(opt[1], path, "label")
            fields.append(FormField(name=fname, label=label))
        return Form(action=_sym(sections["action"][0][1], path, "form action"), fields=fields)
    if kind == "list":
        sections = _sections(node[1:], path, ["query", "item"])
        _expect("query" in sections and len(sections["query"][0]) == 2, path, "list needs (query name)")
        _expect("item" in sections and len(sections["item"]) == 1, path, "list needs exactly one (item ...)")
        item = [_load_component(c, path) for c in sections["item"][0][1:]]
        return List(query=_sym(sections["query"][0][1], path, "list query"), item=item)
    if kind == "text":
        _expect(len(node) == 2 and isinstance(node[1], Sym), path, "(text field)")
        return Text(field=str(node[1]))
    if kind == "checkbox":
        sections = _sections(node[1:], path, ["bind", "action"])
        _expect("bind" in sections and len(sections["bind"][0]) == 2, path, "checkbox needs (bind field)")
        _expect("action" in sections and len(sections["action"][0]) >= 2, path, "checkbox needs (action name (arg field)...)")
        act = sections["action"][0]
        return Checkbox(bind=_sym(sections["bind"][0][1], path, "bind field"), action=_sym(act[1], path, "action"), args=_load_args(act[2:], path))
    if kind == "button":
        sections = _sections(node[1:], path, ["label", "action"])
        _expect("label" in sections and len(sections["label"][0]) == 2, path, "button needs (label \"text\")")
        _expect("action" in sections and len(sections["action"][0]) >= 2, path, "button needs (action name (arg field)...)")
        act = sections["action"][0]
        return Button(label=_str(sections["label"][0][1], path, "label"), action=_sym(act[1], path, "action"), args=_load_args(act[2:], path))
    raise BundleError(path, f"unknown component '{kind}'")


def _load_page(node) -> Page:
    path = "ui"
    _expect(len(node) >= 3, path, "(page name \"/route\" components...)")
    name = _sym(node[1], path, "page name")
    path = f"page {name}"
    route = _str(node[2], path, "page route")
    _expect(route.startswith("/"), path, f"route must start with /, got {route!r}")
    return Page(name=name, route=route, components=[_load_component(c, path) for c in node[3:]])


# ---------------------------------------------------------------- validation


def _validate(app: App):
    _expect(app.entities, "schema", "at least one entity is required")

    seen = set()
    for e in app.entities:
        _expect(e.name not in seen, f"entity {e.name}", "duplicate entity name")
        seen.add(e.name)
        fnames = set()
        id_fields = [f for f in e.fields if f.type == "id"]
        _expect(len(id_fields) == 1 and id_fields[0].auto, f"entity {e.name}", "entity needs exactly one (field ... (id) (auto))")
        for f in e.fields:
            fpath = f"entity {e.name}.{f.name}"
            _expect(f.name not in fnames, fpath, "duplicate field name")
            fnames.add(f.name)
            _expect(not (f.auto and f.has_default), fpath, "(auto) and (default) are mutually exclusive")
            if f.require is not None:
                _expect(not f.auto, fpath, "(require) cannot apply to an (auto) field")
                bad = E.free_names(f.require) - {f.name}
                _expect(not bad, fpath, f"field require may only reference the field itself, found: {', '.join(sorted(bad))}")

    seen = set()
    for q in app.queries:
        qpath = f"query {q.name}"
        _expect(q.name not in seen, qpath, "duplicate query name")
        seen.add(q.name)
        ent = app.entity(q.entity)
        _expect(ent is not None, qpath, f"unknown entity '{q.entity}'")
        fnames = {f.name for f in ent.fields}
        if q.where is not None:
            bad = E.free_names(q.where) - fnames
            _expect(not bad, qpath, f"where references unknown fields: {', '.join(sorted(bad))}")
            _expect(not E.field_refs(q.where), qpath, "where uses bare field names, not (. row field)")
        if q.order_by is not None:
            _expect(q.order_by[0] in fnames, qpath, f"order-by references unknown field '{q.order_by[0]}'")

    seen = set()
    for a in app.actions:
        apath = f"action {a.name}"
        _expect(a.name not in seen, apath, "duplicate action name")
        seen.add(a.name)
        inames = set()
        for iname, _ in a.inputs:
            _expect(iname not in inames, apath, f"duplicate input '{iname}'")
            inames.add(iname)
        _expect(not {"result", "current"} & inames, apath, "inputs may not be named 'result' or 'current'")

        ent = app.entity(a.effect.entity)
        _expect(ent is not None, apath, f"effect references unknown entity '{a.effect.entity}'")
        fields = {f.name: f for f in ent.fields}

        for expr, src in a.requires:
            bad = E.free_names(expr) - inames
            _expect(not bad, apath, f"requires references unbound names: {', '.join(sorted(bad))} in {src}")

        def _check_assigns(assigns, allowed_names):
            assigned = set()
            for fname, expr, src in assigns:
                _expect(fname in fields, apath, f"effect assigns unknown field '{fname}'")
                _expect(not fields[fname].auto, apath, f"effect may not assign (auto) field '{fname}'")
                _expect(fname not in assigned, apath, f"effect assigns field '{fname}' twice")
                assigned.add(fname)
                bad = E.free_names(expr) - allowed_names
                _expect(not bad, apath, f"effect expr references unbound names: {', '.join(sorted(bad))} in {src}")
            return assigned

        if isinstance(a.effect, Insert):
            assigned = _check_assigns(a.effect.assigns, inames)
            for f in ent.fields:
                if not f.auto and not f.has_default:
                    _expect(f.name in assigned, apath, f"insert must assign field '{f.name}' (no default)")
            ensure_names = inames | {"result"}
        elif isinstance(a.effect, Update):
            bad = E.free_names(a.effect.id_expr) - inames
            _expect(not bad, apath, f"update id expr references unbound names: {', '.join(sorted(bad))}")
            _check_assigns(a.effect.assigns, inames | {"current"})
            ensure_names = inames | {"result", "current"}
        else:  # Delete
            bad = E.free_names(a.effect.id_expr) - inames
            _expect(not bad, apath, f"delete id expr references unbound names: {', '.join(sorted(bad))}")
            ensure_names = inames | {"current"}

        for expr, src in a.ensures:
            bad = E.free_names(expr) - ensure_names
            _expect(not bad, apath, f"ensures references unbound names: {', '.join(sorted(bad))} in {src}")
            for base, fname in E.field_refs(expr):
                if base in ("result", "current"):
                    _expect(fname in fields, apath, f"ensures references unknown field (. {base} {fname})")

    _expect(app.pages, "ui", "at least one page is required")
    seen_routes = set()
    for p in app.pages:
        ppath = f"page {p.name}"
        _expect(p.route not in seen_routes, ppath, f"duplicate route '{p.route}'")
        seen_routes.add(p.route)
        for c in p.components:
            _validate_component(app, c, ppath)


def _validate_component(app: App, c, ppath: str):
    if isinstance(c, Form):
        action = app.action(c.action)
        _expect(action is not None, ppath, f"form references unknown action '{c.action}'")
        inames = {n for n, _ in action.inputs}
        form_names = set()
        for f in c.fields:
            _expect(f.name in inames, ppath, f"form field '{f.name}' is not an input of action '{c.action}'")
            form_names.add(f.name)
        _expect(form_names == inames, ppath, f"form for '{c.action}' must cover all inputs: missing {', '.join(sorted(inames - form_names))}")
    elif isinstance(c, List):
        query = app.query(c.query)
        _expect(query is not None, ppath, f"list references unknown query '{c.query}'")
        ent = app.entity(query.entity)
        fnames = {f.name for f in ent.fields}
        for item in c.item:
            if isinstance(item, Text):
                _expect(item.field in fnames, ppath, f"text references unknown field '{item.field}'")
            elif isinstance(item, (Checkbox, Button)):
                if isinstance(item, Checkbox):
                    _expect(item.bind in fnames, ppath, f"checkbox binds unknown field '{item.bind}'")
                action = app.action(item.action)
                _expect(action is not None, ppath, f"component references unknown action '{item.action}'")
                inames = {n for n, _ in action.inputs}
                for arg_name, row_field in item.args:
                    _expect(arg_name in inames, ppath, f"arg '{arg_name}' is not an input of action '{item.action}'")
                    _expect(row_field in fnames, ppath, f"arg '{arg_name}' pulls from unknown row field '{row_field}'")
                _expect({n for n, _ in item.args} == inames, ppath, f"component for '{item.action}' must supply all inputs")
            else:
                raise BundleError(ppath, f"component {type(item).__name__} not allowed inside a list item")
