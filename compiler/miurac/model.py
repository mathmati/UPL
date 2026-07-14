"""The Miura bundle model: dataclasses, the loader from
s-expressions, and whole-bundle validation.

A bundle is:

  (miura 0.1
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
    type: str  # one of TYPES, or "ref"
    ref_entity: str = ""  # set when type == "ref"
    on_delete: str = "restrict"  # ref fields: restrict | cascade
    auto: bool = False
    auto_user: bool = False  # (auto @user): ref User field filled from the session
    unique: bool = False
    default: object = None
    has_default: bool = False
    require: object = None  # parsed expr
    require_src: str = ""


@dataclass
class Entity:
    name: str
    fields: list


@dataclass
class Allow:
    kind: str  # "anyone" | "signed-in" | "role" | "owner"
    arg: str = ""  # role name (kind=role) or row field name (kind=owner)


@dataclass
class Auth:
    roles: list
    default_role: str
    first_user_role: str


@dataclass
class Insert:
    entity: str
    assigns: list  # [(field, expr, src)]
    bind_as: str = ""  # (as name): the inserted row, visible to later effects/ensures


@dataclass
class Update:
    entity: str
    id_expr: object
    assigns: list  # [(field, expr, src)]
    bind_as: str = ""  # (as name): the row after the update
    bind_was: str = ""  # (was name): the row before the update


@dataclass
class Delete:
    entity: str
    id_expr: object
    bind_was: str = ""  # (was name): the row before deletion


@dataclass
class Action:
    name: str
    inputs: list  # [(name, type)]
    requires: list  # [(expr, src)]
    effects: list  # [Insert | Update | Delete] — all run in ONE transaction
    ensures: list  # [(expr, src)] — checked before commit; failure rolls back
    allows: list = dc_field(default_factory=list)  # [Allow]; OR semantics


@dataclass
class Query:
    name: str
    entity: str
    inputs: list = dc_field(default_factory=list)  # [(name, type)] — query parameters
    where: object = None  # parsed expr or None
    where_src: str = ""
    order_by: object = None  # (field, "asc"|"desc") or None
    page_size: int = 0  # (page-size N): offset pagination; 0 = unpaginated
    allows: list = dc_field(default_factory=list)  # [Allow]; OR semantics; no "owner" kind


@dataclass
class Heading:
    text: str


@dataclass
class FormField:
    name: str
    label: str
    from_field: str = ""  # (from row-field): prefill from the enclosing row (list-item forms)


@dataclass
class Form:
    action: str
    fields: list  # [FormField]
    binds: list = dc_field(default_factory=list)  # [(input_name, row_field)] — row-scoped forms only


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
    args: list = dc_field(default_factory=list)  # [(query_input, row_field)] — nested lists only


@dataclass
class Page:
    name: str
    route: str
    components: list


@dataclass
class StepUser:
    name: str  # binding name; also becomes <name>@test as the email
    role: str


@dataclass
class StepDo:
    action: str
    args: list  # [(input_name, value_expr, src)]
    bind: str = ""  # (as name) — binds the result row
    expects: list = dc_field(default_factory=list)  # [(expr, src)]
    by: str = ""  # (by user-binding) — acting user; empty = anonymous


@dataclass
class StepFail:
    action: str
    args: list  # [(input_name, value_expr, src)]
    by: str = ""


@dataclass
class StepCheck:
    query: str
    parts: list  # ordered: ("expect", expr, src) | ("row", index, bind_name)
    args: list = dc_field(default_factory=list)  # [(query_input, value_expr, src)]
    by: str = ""


@dataclass
class TestCase:
    name: str
    steps: list


@dataclass
class App:
    intent: str
    entities: list
    actions: list
    queries: list
    pages: list
    auth: object = None  # Auth | None
    tests: list = dc_field(default_factory=list)
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
    # "upl" is the language's pre-rename head symbol, kept as a legacy alias
    # so historical bundles (e.g. experiments/benchmark/) still compile.
    _expect(isinstance(tree, list) and len(tree) >= 2 and tree[0] in (Sym("miura"), Sym("upl")), path, "bundle must start with (miura 0.1 ...)")
    _expect(str(tree[1]) == "0.1", path, f"unsupported version {tree[1]!r}, expected 0.1")
    sections = _sections(tree[2:], path, ["intent", "auth", "schema", "workflow", "ui", "tests"])
    for required in ("intent", "schema", "workflow", "ui"):
        _expect(required in sections, path, f"missing ({required} ...) section")
    for name in sections:
        _expect(len(sections[name]) == 1, path, f"duplicate ({name} ...) section")

    intent = _str(sections["intent"][0][1] if len(sections["intent"][0]) == 2 else None, "intent", "intent")

    entities = [_load_entity(e) for e in _sections(sections["schema"][0][1:], "schema", ["entity"]).get("entity", [])]

    wf = _sections(sections["workflow"][0][1:], "workflow", ["action", "query"])
    actions = [_load_action(a) for a in wf.get("action", [])]
    queries = [_load_query(q) for q in wf.get("query", [])]

    pages = [_load_page(p) for p in _sections(sections["ui"][0][1:], "ui", ["page"]).get("page", [])]

    auth = _load_auth(sections["auth"][0]) if "auth" in sections else None

    tests = []
    if "tests" in sections:
        tests = [_load_case(c) for c in _sections(sections["tests"][0][1:], "tests", ["case"]).get("case", [])]

    return App(intent=intent, entities=entities, actions=actions, queries=queries, pages=pages, auth=auth, tests=tests)


def _load_auth(node) -> Auth:
    path = "auth"
    sections = _sections(node[1:], path, ["roles", "default-role", "first-user-role"])
    _expect("roles" in sections and len(sections["roles"][0]) >= 2, path, "(auth ...) needs (roles name...)")
    roles = [_sym(r, path, "role name") for r in sections["roles"][0][1:]]
    _expect(len(roles) == len(set(roles)), path, "duplicate role names")

    def _role_opt(key, fallback):
        if key in sections:
            _expect(len(sections[key][0]) == 2, path, f"({key} role) takes one role name")
            role = _sym(sections[key][0][1], path, "role name")
            _expect(role in roles, path, f"({key} {role}): unknown role")
            return role
        return fallback

    default_role = _role_opt("default-role", roles[0] if len(roles) == 1 else None)
    _expect(default_role is not None, path, "(default-role name) is required when there is more than one role")
    first_user_role = _role_opt("first-user-role", default_role)
    return Auth(roles=roles, default_role=default_role, first_user_role=first_user_role)


def _load_allow(node, path, roles_hint="admin") -> Allow:
    _expect(len(node) == 2, path, "(allow rule) takes exactly one rule")
    rule = node[1]
    if isinstance(rule, Sym):
        _expect(str(rule) in ("anyone", "signed-in"), path, f"unknown allow rule '{rule}' (allowed: anyone, signed-in, (role name), (owner field))")
        return Allow(kind=str(rule))
    _expect(isinstance(rule, list) and len(rule) == 2 and isinstance(rule[0], Sym) and isinstance(rule[1], Sym), path, f"allow rule must be anyone, signed-in, (role name), or (owner field): {dumps(node)}")
    kind = str(rule[0])
    _expect(kind in ("role", "owner"), path, f"unknown allow rule '{kind}'")
    return Allow(kind=kind, arg=str(rule[1]))


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
        _expect(isinstance(f[2], list) and len(f[2]) in (1, 2), fpath, f"field type must be (type) or (ref Entity), got {dumps(f[2])}")
        ftype = _sym(f[2][0], fpath, "field type")
        if len(f[2]) == 2:
            _expect(ftype == "ref", fpath, f"two-part field type must be (ref Entity), got {dumps(f[2])}")
            fld = Field(name=fname, type="ref", ref_entity=_sym(f[2][1], fpath, "ref entity"))
        else:
            _expect(ftype in TYPES, fpath, f"unknown type '{ftype}' (allowed: {', '.join(TYPES)}, ref)")
            fld = Field(name=fname, type=ftype)
        for opt in f[3:]:
            _expect(isinstance(opt, list) and opt and isinstance(opt[0], Sym), fpath, f"bad field option {dumps(opt)}")
            key = str(opt[0])
            if key == "on-delete":
                _expect(fld.type == "ref", fpath, "(on-delete ...) only applies to (ref Entity) fields")
                _expect(len(opt) == 2 and str(opt[1]) in ("restrict", "cascade"), fpath, "(on-delete restrict|cascade)")
                fld.on_delete = str(opt[1])
            elif key == "unique":
                _expect(len(opt) == 1, fpath, "(unique) takes no arguments")
                _expect(fld.type in ("text", "int", "id") or fld.type == "ref", fpath, "(unique) applies to text, int, or ref fields")
                fld.unique = True
            elif key == "auto":
                if len(opt) == 2 and opt[1] == Sym("@user"):
                    _expect(fld.type == "ref" and fld.ref_entity == "User", fpath, "(auto @user) only applies to (ref User) fields")
                    fld.auto = True
                    fld.auto_user = True
                else:
                    _expect(len(opt) == 1, fpath, "(auto) takes no arguments (except (auto @user) on a (ref User) field)")
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
    sections = _sections(node[2:], path, ["allow", "input", "requires", "effect", "ensures"])
    _expect("effect" in sections, path, "action needs at least one (effect ...)")

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

    effects = []
    for eff in sections["effect"]:
        _expect(len(eff) >= 2 and isinstance(eff[1], list) and eff[1] and isinstance(eff[1][0], Sym), path, "effect must be (effect (insert|update|delete ...) (as name)? (was name)?)")
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
        for opt in eff[2:]:
            _expect(isinstance(opt, list) and len(opt) == 2 and isinstance(opt[0], Sym) and isinstance(opt[1], Sym), path, f"effect option must be (as name) or (was name): {dumps(opt)}")
            key = str(opt[0])
            if key == "as":
                _expect(not isinstance(effect, Delete), path, "(as name) applies to insert/update effects (delete has no resulting row)")
                effect.bind_as = str(opt[1])
            elif key == "was":
                _expect(isinstance(effect, (Update, Delete)), path, "(was name) applies to update/delete effects (insert has no prior row)")
                effect.bind_was = str(opt[1])
            else:
                raise BundleError(path, f"unknown effect option '{key}'")
        effects.append(effect)

    allows = [_load_allow(a, path) for a in sections.get("allow", [])]
    return Action(name=name, inputs=inputs, requires=requires, effects=effects, ensures=ensures, allows=allows)


def _load_query(node) -> Query:
    path = "workflow"
    _expect(len(node) >= 2, path, "query needs a name")
    name = _sym(node[1], path, "query name")
    path = f"query {name}"
    sections = _sections(node[2:], path, ["allow", "input", "from", "where", "order-by", "page-size"])
    _expect("from" in sections and len(sections["from"]) == 1 and len(sections["from"][0]) == 2, path, "query needs exactly one (from Entity)")
    q = Query(name=name, entity=_sym(sections["from"][0][1], path, "entity"))
    for inp in sections.get("input", []):
        for spec in inp[1:]:
            _expect(isinstance(spec, list) and len(spec) == 2, path, f"input must be (name type): {dumps(spec)}")
            iname = _sym(spec[0], path, "input name")
            itype = _sym(spec[1], path, "input type")
            _expect(itype in TYPES, path, f"unknown input type '{itype}'")
            q.inputs.append((iname, itype))
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
    if "page-size" in sections:
        ps = sections["page-size"][0]
        _expect(len(ps) == 2 and isinstance(ps[1], int) and not isinstance(ps[1], bool) and ps[1] >= 1, path, "(page-size N) takes a positive integer")
        q.page_size = ps[1]
    q.allows = [_load_allow(a, path) for a in sections.get("allow", [])]
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
        sections = _sections(node[1:], path, ["action", "field", "bind"])
        _expect("action" in sections and len(sections["action"][0]) == 2, path, "form needs (action name)")
        fields = []
        for f in sections.get("field", []):
            _expect(len(f) >= 2, path, "form field needs a name")
            fname = _sym(f[1], path, "form field name")
            label = fname
            from_field = ""
            for opt in f[2:]:
                _expect(isinstance(opt, list) and len(opt) == 2 and isinstance(opt[0], Sym), path, f"bad form field option {dumps(opt)}")
                key = str(opt[0])
                if key == "label":
                    label = _str(opt[1], path, "label")
                elif key == "from":
                    from_field = _sym(opt[1], path, "from row-field")
                else:
                    raise BundleError(path, f"unknown form field option '{key}' (allowed: label, from)")
            fields.append(FormField(name=fname, label=label, from_field=from_field))
        binds = []
        for b in sections.get("bind", []):
            _expect(len(b) == 3 and isinstance(b[1], Sym) and isinstance(b[2], Sym), path, f"bind must be (bind input row-field): {dumps(b)}")
            binds.append((str(b[1]), str(b[2])))
        return Form(action=_sym(sections["action"][0][1], path, "form action"), fields=fields, binds=binds)
    if kind == "list":
        sections = _sections(node[1:], path, ["query", "item"])
        _expect("query" in sections, path, "list needs (query name args...)")
        qspec = sections["query"][0]
        _expect(len(qspec) >= 2, path, "list needs (query name args...)")
        _expect("item" in sections and len(sections["item"]) == 1, path, "list needs exactly one (item ...)")
        item = [_load_component(c, path) for c in sections["item"][0][1:]]
        return List(query=_sym(qspec[1], path, "list query"), item=item, args=_load_args(qspec[2:], path))
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


def _load_case(node) -> TestCase:
    path = "tests"
    _expect(len(node) >= 3, path, "(case name step...) needs a name and at least one step")
    name = _sym(node[1], path, "case name")
    path = f"case {name}"
    steps = []
    for s in node[2:]:
        _expect(isinstance(s, list) and s and isinstance(s[0], Sym), path, f"bad step {dumps(s)}")
        kind = str(s[0])
        if kind == "user":
            _expect(len(s) == 3, path, "(user name role) takes a binding name and a role")
            steps.append(StepUser(name=_sym(s[1], path, "user binding"), role=_sym(s[2], path, "role")))
        elif kind in ("do", "fail"):
            _expect(len(s) >= 2, path, f"({kind} action ...) needs an action name")
            action = _sym(s[1], path, "action")
            args, bind, expects, by = [], "", [], ""
            for part in s[2:]:
                _expect(isinstance(part, list) and part and isinstance(part[0], Sym), path, f"bad step part {dumps(part)}")
                key = str(part[0])
                if key == "as":
                    _expect(kind == "do" and len(part) == 2, path, "(as name) applies to do steps only")
                    bind = _sym(part[1], path, "binding name")
                elif key == "by":
                    _expect(len(part) == 2, path, "(by user-binding) takes one name")
                    by = _sym(part[1], path, "acting user")
                elif key == "expect":
                    _expect(kind == "do" and len(part) == 2, path, "(expect expr) applies to do steps only")
                    try:
                        expects.append((E.parse_expr(part[1]), E.to_source(part[1])))
                    except E.ExprError as err:
                        raise BundleError(path, str(err))
                else:
                    _expect(len(part) == 2, path, f"action arg must be (input value): {dumps(part)}")
                    try:
                        args.append((key, E.parse_expr(part[1]), E.to_source(part[1])))
                    except E.ExprError as err:
                        raise BundleError(path, str(err))
            if kind == "do":
                steps.append(StepDo(action=action, args=args, bind=bind, expects=expects, by=by))
            else:
                steps.append(StepFail(action=action, args=args, by=by))
        elif kind == "check":
            _expect(len(s) >= 2, path, "(check query (expect expr)...) needs a query name")
            qargs = []
            if isinstance(s[1], list):
                # parameterized: (check (query (param value)...) part...)
                _expect(len(s[1]) >= 1, path, f"bad check query {dumps(s[1])}")
                query = _sym(s[1][0], path, "query")
                for a in s[1][1:]:
                    _expect(isinstance(a, list) and len(a) == 2 and isinstance(a[0], Sym), path, f"query arg must be (input value): {dumps(a)}")
                    try:
                        qargs.append((str(a[0]), E.parse_expr(a[1]), E.to_source(a[1])))
                    except E.ExprError as err:
                        raise BundleError(path, str(err))
            else:
                query = _sym(s[1], path, "query")
            parts = []
            check_by = ""
            for part in s[2:]:
                _expect(isinstance(part, list) and part and isinstance(part[0], Sym), path, f"bad check part {dumps(part)}")
                key = str(part[0])
                if key == "by":
                    _expect(len(part) == 2, path, "(by user-binding) takes one name")
                    check_by = _sym(part[1], path, "acting user")
                elif key == "expect":
                    _expect(len(part) == 2, path, f"(expect expr) takes one expression: {dumps(part)}")
                    try:
                        parts.append(("expect", E.parse_expr(part[1]), E.to_source(part[1])))
                    except E.ExprError as err:
                        raise BundleError(path, str(err))
                elif key == "row":
                    _expect(
                        len(part) == 3 and isinstance(part[1], int) and not isinstance(part[1], bool) and part[1] >= 0
                        and isinstance(part[2], list) and len(part[2]) == 2 and part[2][0] == Sym("as"),
                        path, f"row binding must be (row N (as name)) with N >= 0: {dumps(part)}",
                    )
                    parts.append(("row", part[1], _sym(part[2][1], path, "row binding name")))
                else:
                    raise BundleError(path, f"check only takes (expect expr), (row N (as name)), and (by user): {dumps(part)}")
            steps.append(StepCheck(query=query, parts=parts, args=qargs, by=check_by))
        else:
            raise BundleError(path, f"unknown step '{kind}' (allowed: user, do, fail, check)")
    return TestCase(name=name, steps=steps)


# ---------------------------------------------------------------- validation


def _signed_in_guaranteed(allows) -> bool:
    return bool(allows) and all(a.kind != "anyone" for a in allows)


def _check_aggregates(app, expr, outer_names, path, src, allowed):
    """Validate (count ...)/(sum ...) nodes: context, entity, field, and
    predicate scoping (bare names = the aggregated entity's fields first,
    then outer names)."""
    for agg in E.aggregates(expr):
        _expect(allowed, path, f"aggregates ((count ...)/(sum ...)) are only allowed in action requires, query where, and test expects: {src}")
        ent = app.entity(agg.entity)
        _expect(agg.entity != "User" and ent is not None, path, f"aggregate over unknown entity '{agg.entity}' in {src}")
        fields = {f.name: f for f in ent.fields}
        if agg.kind == "sum":
            _expect(agg.field in fields and fields[agg.field].type == "int", path, f"(sum {agg.entity} {agg.field} ...): field must exist and be (int)")
        if agg.pred is not None:
            _expect(not E.aggregates(agg.pred), path, f"aggregates cannot nest inside an aggregate predicate: {src}")
            bad = E.free_names(agg.pred) - set(fields) - set(outer_names)
            _expect(not bad, path, f"aggregate predicate references unknown names: {', '.join(sorted(bad))} in {src}")


def _validate(app: App):
    _expect(app.entities, "schema", "at least one entity is required")

    # --- auth normalization and gating -------------------------------------
    if app.auth:
        _expect(app.entity("User") is None, "schema", "'User' is a reserved entity name when (auth ...) is present")
        for a in app.actions:
            if not a.allows:
                a.allows = [Allow(kind="signed-in")]
        for q in app.queries:
            if not q.allows:
                q.allows = [Allow(kind="signed-in")]
    else:
        for a in app.actions:
            _expect(not a.allows, f"action {a.name}", "(allow ...) requires an (auth ...) section")
            a.allows = [Allow(kind="anyone")]
        for q in app.queries:
            _expect(not q.allows, f"query {q.name}", "(allow ...) requires an (auth ...) section")
            q.allows = [Allow(kind="anyone")]

    def _check_allows(allows, path, entity=None, effect=None):
        for al in allows:
            if al.kind == "role":
                _expect(app.auth and al.arg in app.auth.roles, path, f"(allow (role {al.arg})): unknown role")
            elif al.kind == "owner":
                _expect(effect is not None and isinstance(effect, (Update, Delete)), path, "(allow (owner field)) only applies to update/delete actions")
                fields = {f.name: f for f in entity.fields}
                _expect(al.arg in fields and fields[al.arg].type == "ref" and fields[al.arg].ref_entity == "User", path, f"(allow (owner {al.arg})): '{al.arg}' must be a (ref User) field of {entity.name}")

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
                _check_aggregates(app, f.require, {f.name}, fpath, f.require_src, allowed=False)
            if f.type == "ref":
                _expect(not f.has_default, fpath, "(ref ...) fields cannot have a (default)")
                _expect(not f.auto or f.auto_user, fpath, "(ref ...) fields cannot be (auto) — except (auto @user) on (ref User)")

    # ref targets can only be checked once all entities are known
    referenced_by = {}  # entity name -> [(child entity, field)]
    for e in app.entities:
        for f in e.fields:
            if f.type == "ref":
                fpath = f"entity {e.name}.{f.name}"
                if f.ref_entity == "User":
                    _expect(app.auth is not None, fpath, "(ref User) requires an (auth ...) section")
                    continue
                _expect(app.entity(f.ref_entity) is not None, fpath, f"(ref {f.ref_entity}) references unknown entity")
                _expect(not (f.on_delete == "cascade" and f.ref_entity == e.name), fpath, "(on-delete cascade) is not allowed on a self-reference")
                referenced_by.setdefault(f.ref_entity, []).append((e.name, f.name))
    for e in app.entities:
        for f in e.fields:
            if f.type == "ref" and f.on_delete == "cascade":
                _expect(f.ref_entity not in {e.name} or True, "", "")  # self-ref handled above
                # cascading into an entity that is itself referenced would require
                # transitive cascade planning; keep v0.3 one level deep
                _expect(e.name not in referenced_by, f"entity {e.name}.{f.name}",
                        f"(on-delete cascade) not allowed: {e.name} is itself referenced by another entity")

    seen = set()
    for q in app.queries:
        qpath = f"query {q.name}"
        _expect(q.name not in seen, qpath, "duplicate query name")
        seen.add(q.name)
        ent = app.entity(q.entity)
        _expect(ent is not None, qpath, f"unknown entity '{q.entity}'")
        fnames = {f.name for f in ent.fields}
        _check_allows(q.allows, qpath)
        inames = set()
        for iname, _ in q.inputs:
            _expect(iname not in inames, qpath, f"duplicate input '{iname}'")
            _expect(iname not in fnames, qpath, f"query input '{iname}' collides with a field of {q.entity}; rename the input")
            inames.add(iname)
        auth_names = {"@user"} if app.auth and _signed_in_guaranteed(q.allows) else set()
        if q.where is not None:
            bad = E.free_names(q.where) - fnames - inames - auth_names
            _expect(not bad, qpath, f"where references unknown fields/inputs: {', '.join(sorted(bad))}"
                    + (" (@user needs a signed-in guarantee: no (allow anyone))" if "@user" in bad else ""))
            _check_aggregates(app, q.where, fnames | inames | auth_names, qpath, q.where_src, allowed=True)
            _expect(not E.field_refs(q.where), qpath, "where uses bare field names, not (. row field)")
        else:
            _expect(not q.inputs, qpath, "query inputs require a (where ...) that uses them")
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

        primary = a.effects[0]
        primary_ent = app.entity(primary.entity)
        _expect(primary_ent is not None, apath, f"effect references unknown entity '{primary.entity}'")
        _check_allows(a.allows, apath, primary_ent, primary)
        if any(al.kind == "owner" for al in a.allows):
            _expect(len(a.effects) == 1, apath, "(allow (owner ...)) only applies to single-effect actions")
        auth_names = {"@user"} if app.auth and _signed_in_guaranteed(a.allows) else set()
        inames = inames | auth_names

        for expr, src in a.requires:
            bad = E.free_names(expr) - inames
            _expect(not bad, apath, f"requires references unbound names: {', '.join(sorted(bad))} in {src}")
            _check_aggregates(app, expr, inames, apath, src, allowed=True)

        bound_names = set()
        row_entities = {}  # binding name -> entity (for field-ref checks)
        for eff in a.effects:
            ent = app.entity(eff.entity)
            _expect(ent is not None, apath, f"effect references unknown entity '{eff.entity}'")
            fields = {f.name: f for f in ent.fields}
            scope = inames | bound_names

            def _check_assigns(assigns, allowed_names):
                assigned = set()
                for fname, expr, src in assigns:
                    _expect(fname in fields, apath, f"effect assigns unknown field '{fname}'")
                    _expect(not fields[fname].auto, apath, f"effect may not assign (auto) field '{fname}'")
                    _expect(fname not in assigned, apath, f"effect assigns field '{fname}' twice")
                    assigned.add(fname)
                    bad = E.free_names(expr) - allowed_names
                    _expect(not bad, apath, f"effect expr references unbound names: {', '.join(sorted(bad))} in {src}")
                    _check_aggregates(app, expr, allowed_names, apath, src, allowed=False)
                return assigned

            if isinstance(eff, Insert):
                if any(f.auto_user for f in ent.fields):
                    _expect(_signed_in_guaranteed(a.allows), apath, f"insert into {ent.name} fills an (auto @user) field, so the action needs a signed-in guarantee (no (allow anyone))")
                assigned = _check_assigns(eff.assigns, scope)
                for f in ent.fields:
                    if not f.auto and not f.has_default:
                        _expect(f.name in assigned, apath, f"insert must assign field '{f.name}' (no default)")
            else:  # Update | Delete
                bad = E.free_names(eff.id_expr) - scope
                _expect(not bad, apath, f"effect id expr references unbound names: {', '.join(sorted(bad))}")
                _check_aggregates(app, eff.id_expr, scope, apath, "effect id expr", allowed=False)
                if isinstance(eff, Update):
                    _check_assigns(eff.assigns, scope | {"current"})

            for bname in (getattr(eff, "bind_was", ""), getattr(eff, "bind_as", "")):
                if bname:
                    _expect(bname not in ("result", "current", "@user") and bname not in inames and bname not in bound_names, apath, f"effect binding '{bname}' collides with another name")
                    bound_names.add(bname)
                    row_entities[bname] = ent

        last = a.effects[-1]
        last_ent = app.entity(last.entity)
        ensure_names = inames | bound_names
        if not isinstance(last, Delete):
            ensure_names |= {"result"}
            row_entities["result"] = last_ent
        if isinstance(last, (Update, Delete)):
            ensure_names |= {"current"}
            row_entities["current"] = last_ent

        for expr, src in a.ensures:
            bad = E.free_names(expr) - ensure_names
            _expect(not bad, apath, f"ensures references unbound names: {', '.join(sorted(bad))} in {src}")
            _check_aggregates(app, expr, ensure_names, apath, src, allowed=False)
            for base, fname in E.field_refs(expr):
                if base in row_entities:
                    _expect(fname in {f.name for f in row_entities[base].fields}, apath, f"ensures references unknown field (. {base} {fname})")

    seen = set()
    for case in app.tests:
        cpath = f"case {case.name}"
        _expect(case.name not in seen, cpath, "duplicate case name")
        seen.add(case.name)
        bound = set()
        user_bindings = set()

        def _check_step_args(action, args, what):
            inames = {n for n, _ in action.inputs}
            given = set()
            for arg_name, value_expr, src in args:
                _expect(arg_name in inames, cpath, f"{what} arg '{arg_name}' is not an input of '{action.name}'")
                _expect(arg_name not in given, cpath, f"{what} supplies arg '{arg_name}' twice")
                given.add(arg_name)
                bad = E.free_names(value_expr) - bound
                _expect(not bad, cpath, f"{what} value references unbound names: {', '.join(sorted(bad))} in {src}")
                _check_aggregates(app, value_expr, bound, cpath, src, allowed=False)
            _expect(given == inames, cpath, f"{what} must supply all inputs of '{action.name}': missing {', '.join(sorted(inames - given))}")

        for step in case.steps:
            if isinstance(step, StepUser):
                _expect(app.auth is not None, cpath, "(user ...) steps require an (auth ...) section")
                _expect(step.role in app.auth.roles, cpath, f"(user {step.name} {step.role}): unknown role")
                _expect(step.name not in bound and step.name not in ("result", "current"), cpath, f"binding '{step.name}' already used")
                bound.add(step.name)
                user_bindings.add(step.name)
            elif isinstance(step, (StepDo, StepFail)):
                if step.by:
                    _expect(step.by in user_bindings, cpath, f"(by {step.by}): no prior (user {step.by} role) step")
                action = app.action(step.action)
                if action is None and isinstance(step, StepFail):
                    action = app.query(step.action)  # (fail query ...) asserts the query is rejected
                _expect(action is not None, cpath, f"unknown action '{step.action}'")
                _check_step_args(action, step.args, "do" if isinstance(step, StepDo) else "fail")
                if isinstance(step, StepDo):
                    for expr, src in step.expects:
                        bad = E.free_names(expr) - bound - {"result"}
                        _expect(not bad, cpath, f"expect references unbound names: {', '.join(sorted(bad))} in {src}")
                        _check_aggregates(app, expr, bound | {"result"}, cpath, src, allowed=True)
                    if step.bind:
                        _expect(step.bind not in ("result", "current"), cpath, "binding may not be named 'result' or 'current'")
                        _expect(step.bind not in bound, cpath, f"binding '{step.bind}' already used")
                        bound.add(step.bind)
            else:  # StepCheck
                if step.by:
                    _expect(step.by in user_bindings, cpath, f"(by {step.by}): no prior (user {step.by} role) step")
                query = app.query(step.query)
                _expect(query is not None, cpath, f"unknown query '{step.query}'")
                qinputs = {n for n, _ in query.inputs}
                given = set()
                for arg_name, value_expr, src in step.args:
                    _expect(arg_name in qinputs, cpath, f"check arg '{arg_name}' is not an input of query '{step.query}'")
                    _expect(arg_name not in given, cpath, f"check supplies arg '{arg_name}' twice")
                    given.add(arg_name)
                    bad = E.free_names(value_expr) - bound
                    _expect(not bad, cpath, f"check value references unbound names: {', '.join(sorted(bad))} in {src}")
                _expect(given == qinputs, cpath, f"check must supply all inputs of query '{step.query}': missing {', '.join(sorted(qinputs - given))}")
                for part in step.parts:
                    if part[0] == "expect":
                        _, expr, src = part
                        bad = E.free_names(expr) - bound - {"result"}
                        _expect(not bad, cpath, f"expect references unbound names: {', '.join(sorted(bad))} in {src}")
                        _check_aggregates(app, expr, bound | {"result"}, cpath, src, allowed=True)
                    else:  # row binding
                        _, _index, bind_name = part
                        _expect(bind_name not in ("result", "current"), cpath, "binding may not be named 'result' or 'current'")
                        _expect(bind_name not in bound, cpath, f"binding '{bind_name}' already used")
                        bound.add(bind_name)

    _expect(app.pages, "ui", "at least one page is required")
    seen_routes = set()
    for p in app.pages:
        ppath = f"page {p.name}"
        _expect(p.route not in seen_routes, ppath, f"duplicate route '{p.route}'")
        seen_routes.add(p.route)
        for c in p.components:
            _validate_component(app, c, ppath)


def _validate_component(app: App, c, ppath: str, row_fields=None):
    """Validate a component. row_fields is the parent row's field-name set
    when the component sits inside a list (item ...), else None."""
    if isinstance(c, Heading):
        return
    if isinstance(c, Form):
        action = app.action(c.action)
        _expect(action is not None, ppath, f"form references unknown action '{c.action}'")
        inames = {n for n, _ in action.inputs}
        covered = set()
        for f in c.fields:
            _expect(f.name in inames, ppath, f"form field '{f.name}' is not an input of action '{c.action}'")
            _expect(f.name not in covered, ppath, f"form covers input '{f.name}' twice")
            if f.from_field:
                _expect(row_fields is not None, ppath, f"(from ...) on field '{f.name}' is only allowed on forms inside a list (item ...)")
                _expect(f.from_field in row_fields, ppath, f"field '{f.name}' prefills (from {f.from_field}) but the row has no such field")
            covered.add(f.name)
        for input_name, row_field in c.binds:
            _expect(row_fields is not None, ppath, "(bind ...) is only allowed on forms inside a list (item ...)")
            _expect(input_name in inames, ppath, f"bind '{input_name}' is not an input of action '{c.action}'")
            _expect(input_name not in covered, ppath, f"form covers input '{input_name}' twice")
            _expect(row_field in row_fields, ppath, f"bind '{input_name}' pulls from unknown row field '{row_field}'")
            covered.add(input_name)
        _expect(covered == inames, ppath, f"form for '{c.action}' must cover all inputs: missing {', '.join(sorted(inames - covered))}")
        return
    if isinstance(c, List):
        query = app.query(c.query)
        _expect(query is not None, ppath, f"list references unknown query '{c.query}'")
        qinputs = {n for n, _ in query.inputs}
        given = set()
        for input_name, row_field in c.args:
            _expect(row_fields is not None, ppath, "a parameterized (query name (arg field)...) list is only allowed inside a list (item ...)")
            _expect(input_name in qinputs, ppath, f"arg '{input_name}' is not an input of query '{c.query}'")
            _expect(input_name not in given, ppath, f"list supplies query arg '{input_name}' twice")
            _expect(row_field in row_fields, ppath, f"query arg '{input_name}' pulls from unknown row field '{row_field}'")
            given.add(input_name)
        _expect(given == qinputs, ppath, f"list must supply all inputs of query '{c.query}': missing {', '.join(sorted(qinputs - given))}")
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
            elif isinstance(item, (Form, List, Heading)):
                _validate_component(app, item, ppath, row_fields=fnames)
            else:
                raise BundleError(ppath, f"component {type(item).__name__} not allowed inside a list item")
        return
    raise BundleError(ppath, f"component {type(c).__name__} not allowed here")
