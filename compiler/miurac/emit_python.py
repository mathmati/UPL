"""Deterministic Python server emitter.

Generates a zero-dependency stdlib server (http.server + sqlite3) with
one function per action/query and contracts enforced at runtime:
requires/field-require violations -> 400, ensures violations -> 500.
"""

from __future__ import annotations

from . import expr as E
from .model import App, Delete, Insert, Update
from .emit_sql import emit_sql, table_name

_COERCE = {"text": "_coerce_text", "int": "_coerce_int", "bool": "_coerce_bool", "id": "_coerce_id", "timestamp": "_coerce_text"}
_QCOERCE = {"text": "_qcoerce_text", "int": "_qcoerce_int", "bool": "_qcoerce_bool", "id": "_qcoerce_text", "timestamp": "_qcoerce_text"}


def _emit_ref_checks(lines, app, entity, values_py: str, assigned=None):
    """Referential-integrity checks for assigned (ref ...) fields."""
    for f in entity.fields:
        if f.type != "ref":
            continue
        if assigned is not None and f.name not in assigned:
            continue
        ref_table = table_name(f.ref_entity)
        lines.append(f'        if conn.execute("SELECT 1 FROM {ref_table} WHERE id = ?", ({values_py}[{f.name!r}],)).fetchone() is None:')
        lines.append(f"            raise ContractViolation('{entity.name}.{f.name}: no {f.ref_entity} with id ' + str({values_py}[{f.name!r}]))")


def _input_names(action):
    names = {name: f'inp[{name!r}]' for name, _ in action.inputs}
    names["@user"] = 'ctx["user"]["id"]'
    return names


def _allow_cond(allow):
    if allow.kind == "signed-in":
        return 'ctx["user"] is not None'
    if allow.kind == "role":
        return f'(ctx["user"] is not None and ctx["user"]["role"] == {allow.arg!r})'
    raise AssertionError(allow)


def _emit_allow_checks(lines, allows, what):
    """Emit pre-effect permission checks. Owner rules are deferred (they
    need the current row); returns the owner rules for the caller."""
    if any(a.kind == "anyone" for a in allows):
        return []
    owner_rules = [a for a in allows if a.kind == "owner"]
    plain = [a for a in allows if a.kind in ("signed-in", "role")]
    if owner_rules and not plain:
        # owner implies signed-in; the row check happens after the fetch
        lines.append('    if ctx["user"] is None:')
        lines.append("        raise PermissionDenied('sign in required')")
    elif plain:
        cond = " or ".join(_allow_cond(a) for a in plain)
        if owner_rules:
            # defer the final decision, but reject anonymous callers early
            lines.append('    if ctx["user"] is None:')
            lines.append("        raise PermissionDenied('sign in required')")
        else:
            lines.append(f"    if not ({cond}):")
            lines.append(f"        raise PermissionDenied('sign in required' if ctx['user'] is None else 'not allowed: {what}')")
    return owner_rules


def _emit_owner_check(lines, owner_rules, allows, what, cur_var="current"):
    """Emit the post-fetch owner check (inside the conn block, after the
    current row exists). ORs the plain rules back in. Owner rules only
    occur on single-effect actions (enforced by the validator)."""
    if not owner_rules:
        return
    conds = [_allow_cond(a) for a in allows if a.kind in ("signed-in", "role")]
    conds += [f'{cur_var}[{a.arg!r}] == ctx["user"]["id"]' for a in owner_rules]
    lines.append(f"        if not ({' or '.join(conds)}):")
    lines.append(f"            raise PermissionDenied('not allowed: {what}')")


def _emit_field_requires(lines, entity, values_py: str, assigned=None):
    """Emit field (require ...) checks against a dict-valued expression."""
    for f in entity.fields:
        if f.require is None:
            continue
        if assigned is not None and f.name not in assigned:
            continue
        cond = E.to_python(f.require, {f.name: f"{values_py}[{f.name!r}]"})
        lines.append(f"    if not {cond}:")
        lines.append(f"        raise ContractViolation('field {entity.name}.{f.name} require failed: ' + {f.require_src!r})")


def _agg_resolver(app):
    def resolve(entity_name):
        e = app.entity(entity_name)
        return (table_name(e.name), {f.name for f in e.fields})
    return resolve


def _emit_action(app: App, action) -> list:
    inames = _input_names(action)
    agg = _agg_resolver(app)
    lines = [f"def action_{action.name}(inp, ctx):"]
    intent_inputs = ", ".join(f"{n} {t}" for n, t in action.inputs) or "none"
    lines.append(f'    """Miura action {action.name} (inputs: {intent_inputs})."""')

    # Permission checks run before any DB work (may raise PermissionDenied).
    owner_rules = _emit_allow_checks(lines, action.allows, action.name)
    single = len(action.effects) == 1

    lines.append("    conn = _db()")
    lines.append("    _aggconn = conn")  # aggregates in requires/ensures see this txn
    lines.append("    try:")

    # requires: preconditions over inputs; may read committed state via aggregates
    for expr, src in action.requires:
        cond = E.to_python(expr, inames, agg)
        lines.append(f"        if not {cond}:")
        lines.append(f"            raise ContractViolation('requires failed: ' + {src!r})")

    # Effects run in order, no intermediate commit. Bindings from earlier
    # effects (as/was) are visible to later effects and to ensures.
    names = dict(inames)
    last_result = None   # python expr for the row after the last insert/update
    last_current = None  # python expr for the pre-image of the last update/delete

    for i, eff in enumerate(action.effects):
        ent = app.entity(eff.entity)
        table = table_name(ent.name)
        if isinstance(eff, Insert):
            assigns = dict((f, e) for f, e, _ in eff.assigns)
            row_items = []
            for f in ent.fields:
                if f.name in assigns:
                    value = E.to_python(assigns[f.name], names, agg)
                elif f.auto_user:
                    value = 'ctx["user"]["id"]'
                elif f.auto and f.type == "id":
                    value = "str(uuid.uuid4())"
                elif f.auto and f.type == "timestamp":
                    value = "_now()"
                else:
                    value = repr(f.default)
                row_items.append(f"{f.name!r}: {value}")
            row_var = f"_row{i}"
            lines.append(f"        {row_var} = {{" + ", ".join(row_items) + "}")
            _emit_field_requires_indented(lines, ent, row_var)
            _emit_ref_checks(lines, app, ent, row_var)
            cols = ", ".join(f.name for f in ent.fields)
            marks = ", ".join("?" for _ in ent.fields)
            params = ", ".join(f"{row_var}[{f.name!r}]" for f in ent.fields)
            lines.append("        try:")
            lines.append(f'            conn.execute("INSERT INTO {table} ({cols}) VALUES ({marks})", ({params},))')
            lines.append("        except sqlite3.IntegrityError as err:")
            lines.append("            raise ContractViolation('unique constraint violated: ' + str(err))")
            lines.append(f'        _res{i} = conn.execute("SELECT * FROM {table} WHERE id = ?", ({row_var}["id"],)).fetchone()')
            if eff.bind_as:
                names[eff.bind_as] = f"_res{i}"
            last_result, last_current = f"_res{i}", None
        elif isinstance(eff, Update):
            id_py = E.to_python(eff.id_expr, names, agg)
            lines.append(f'        _cur{i} = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
            lines.append(f"        if _cur{i} is None:")
            lines.append(f"            raise ContractViolation('no {ent.name} with id ' + str({id_py}))")
            if single:
                _emit_owner_check(lines, owner_rules, action.allows, action.name, f"_cur{i}")
            unames = dict(names)
            unames["current"] = f"_cur{i}"
            assigned = set()
            update_items = []
            for fname, expr, _src in eff.assigns:
                update_items.append(f"{fname!r}: {E.to_python(expr, unames, agg)}")
                assigned.add(fname)
            upd_var = f"_upd{i}"
            lines.append(f"        {upd_var} = {{" + ", ".join(update_items) + "}")
            _emit_field_requires_indented(lines, ent, upd_var, assigned)
            _emit_ref_checks(lines, app, ent, upd_var, assigned)
            set_clause = ", ".join(f"{fname} = ?" for fname, _, _ in eff.assigns)
            set_params = ", ".join(f"{upd_var}[{fname!r}]" for fname, _, _ in eff.assigns)
            lines.append("        try:")
            lines.append(f'            conn.execute("UPDATE {table} SET {set_clause} WHERE id = ?", ({set_params}, {id_py}))')
            lines.append("        except sqlite3.IntegrityError as err:")
            lines.append("            raise ContractViolation('unique constraint violated: ' + str(err))")
            lines.append(f'        _res{i} = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
            if eff.bind_was:
                names[eff.bind_was] = f"_cur{i}"
            if eff.bind_as:
                names[eff.bind_as] = f"_res{i}"
            last_result, last_current = f"_res{i}", f"_cur{i}"
        else:  # Delete
            id_py = E.to_python(eff.id_expr, names, agg)
            lines.append(f'        _cur{i} = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
            lines.append(f"        if _cur{i} is None:")
            lines.append(f"            raise ContractViolation('no {ent.name} with id ' + str({id_py}))")
            if single:
                _emit_owner_check(lines, owner_rules, action.allows, action.name, f"_cur{i}")
            ref_children = [(child, f) for child in app.entities for f in child.fields if f.type == "ref" and f.ref_entity == ent.name]
            for child, f in ref_children:  # all restrict checks before any cascade deletes
                if f.on_delete == "restrict":
                    lines.append(f'        if conn.execute("SELECT 1 FROM {table_name(child.name)} WHERE {f.name} = ?", ({id_py},)).fetchone() is not None:')
                    lines.append(f"            raise ContractViolation('cannot delete {ent.name} ' + str({id_py}) + ': referenced by {child.name}.{f.name}')")
            for child, f in ref_children:
                if f.on_delete == "cascade":
                    lines.append(f'        conn.execute("DELETE FROM {table_name(child.name)} WHERE {f.name} = ?", ({id_py},))')
            lines.append(f'        conn.execute("DELETE FROM {table} WHERE id = ?", ({id_py},))')
            if eff.bind_was:
                names[eff.bind_was] = f"_cur{i}"
            last_result, last_current = None, f"_cur{i}"

    ensure_names = dict(names)
    if last_result is not None:
        ensure_names["result"] = last_result
    if last_current is not None:
        ensure_names["current"] = last_current

    for expr, src in action.ensures:
        cond = E.to_python(expr, ensure_names, agg)
        lines.append(f"        if not {cond}:")
        lines.append("            conn.rollback()")
        lines.append(f"            raise EnsuresViolation('ensures failed: ' + {src!r})")

    lines.append("        conn.commit()")
    return_value = last_result if last_result is not None else '{"ok": True}'
    lines.append(f"        return {return_value}")
    lines.append("    finally:")
    lines.append("        conn.close()")
    return lines


def _emit_field_requires_indented(lines, entity, values_py: str, assigned=None):
    inner = []
    _emit_field_requires(inner, entity, values_py, assigned)
    lines.extend("    " + line for line in inner)


def _emit_query(app: App, query) -> list:
    table = table_name(query.entity)
    sql = f"SELECT * FROM {table}"
    if query.order_by is not None:
        sql += f" ORDER BY {query.order_by[0]} {query.order_by[1].upper()}, id ASC"
    else:
        sql += " ORDER BY id ASC"
    intent_inputs = ", ".join(f"{n} {t}" for n, t in query.inputs)
    lines = [f"def query_{query.name}(inp, ctx, offset=0):"]
    doc = f"Miura query {query.name} over {query.entity}"
    lines.append(f'    """{doc}{" (inputs: " + intent_inputs + ")" if intent_inputs else ""}."""')
    _emit_allow_checks(lines, query.allows, query.name)
    lines.append("    conn = _db()")
    lines.append("    try:")
    lines.append(f'        rows = conn.execute("{sql}").fetchall()')
    lines.append("    finally:")
    lines.append("        conn.close()")
    if query.where is not None:
        ent = app.entity(query.entity)
        names = {f.name: f"row[{f.name!r}]" for f in ent.fields}
        names["@user"] = 'ctx["user"]["id"]'
        for iname, _ in query.inputs:
            names[iname] = f"inp[{iname!r}]"
        cond = E.to_python(query.where, names, _agg_resolver(app))
        lines.append(f"    rows = [row for row in rows if {cond}]")
    if query.page_size:
        lines.append(f"    rows = rows[offset:offset + {query.page_size}]")
    lines.append("    return rows")
    return lines


def emit_python(app: App, header: str) -> str:
    out = []
    out.extend(f"# {line}" for line in header.splitlines())
    out.append('"""' + app.intent.replace('"""', r"\"\"\"") + '"""')
    out.append("")
    out.append("import json")
    if app.auth:
        out.append("import hashlib")
    out.append("import os")
    if app.auth:
        out.append("import secrets")
    out.append("import sqlite3")
    out.append("import urllib.parse")
    out.append("import uuid")
    out.append("from datetime import datetime, timezone")
    out.append("from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer")
    out.append("")
    out.append('DB_PATH = os.environ.get("MIURA_DB") or os.environ.get("UPL_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db"))')
    out.append('WEB_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))')
    out.append("")
    out.append("SCHEMA_SQL = '''\\")
    out.append(emit_sql(app, header).replace("\\", "\\\\").replace("'''", "\\'\\'\\'") + "'''")
    out.append("")
    out.append("")
    out.append("class ContractViolation(Exception):")
    out.append('    """A requires/field-require contract failed: client error (400)."""')
    out.append("")
    out.append("")
    out.append("class PermissionDenied(Exception):")
    out.append('    """An (allow ...) rule rejected the caller: 401 anonymous, 403 signed-in."""')
    out.append("")
    out.append("")
    out.append("class EnsuresViolation(Exception):")
    out.append('    """An ensures contract failed after the effect: server bug (500)."""')
    out.append("")
    out.append("")
    out.append("def _db():")
    out.append("    conn = sqlite3.connect(DB_PATH)")
    out.append("    conn.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}")
    out.append("    return conn")
    out.append("")
    out.append("")
    out.append("def _now():")
    out.append('    return datetime.now(timezone.utc).isoformat()')
    out.append("")
    out.append("")
    out.append("def _agg_count(conn, table, pred):")
    out.append('    """(count Entity pred?) — rows matching pred. conn=None opens its own."""')
    out.append("    own = conn is None")
    out.append("    if own:")
    out.append("        conn = _db()")
    out.append("    try:")
    out.append('        return sum(1 for _r in conn.execute("SELECT * FROM " + table).fetchall() if pred(_r))')
    out.append("    finally:")
    out.append("        if own:")
    out.append("            conn.close()")
    out.append("")
    out.append("")
    out.append("def _agg_sum(conn, table, field, pred):")
    out.append('    """(sum Entity field pred?) — sum of field over matching rows."""')
    out.append("    own = conn is None")
    out.append("    if own:")
    out.append("        conn = _db()")
    out.append("    try:")
    out.append('        return sum(_r[field] for _r in conn.execute("SELECT * FROM " + table).fetchall() if pred(_r))')
    out.append("    finally:")
    out.append("        if own:")
    out.append("            conn.close()")
    out.append("")
    out.append("")
    out.append("def _coerce_text(name, value):")
    out.append("    if not isinstance(value, str):")
    out.append("        raise ContractViolation('input ' + name + ' must be a string')")
    out.append("    return value")
    out.append("")
    out.append("")
    out.append("def _coerce_id(name, value):")
    out.append("    if not isinstance(value, str) or not value:")
    out.append("        raise ContractViolation('input ' + name + ' must be a non-empty id string')")
    out.append("    return value")
    out.append("")
    out.append("")
    out.append("def _coerce_int(name, value):")
    out.append("    if isinstance(value, bool) or not isinstance(value, int):")
    out.append("        raise ContractViolation('input ' + name + ' must be an integer')")
    out.append("    return value")
    out.append("")
    out.append("")
    out.append("def _coerce_bool(name, value):")
    out.append("    if not isinstance(value, bool):")
    out.append("        raise ContractViolation('input ' + name + ' must be a boolean')")
    out.append("    return value")
    out.append("")
    out.append("")
    out.append("def _qcoerce_text(name, value):")
    out.append("    if not value:")
    out.append("        raise ContractViolation('query param ' + name + ' must not be empty')")
    out.append("    return value")
    out.append("")
    out.append("")
    out.append("def _qcoerce_int(name, value):")
    out.append("    try:")
    out.append("        return int(value)")
    out.append("    except ValueError:")
    out.append("        raise ContractViolation('query param ' + name + ' must be an integer')")
    out.append("")
    out.append("")
    out.append("def _qcoerce_bool(name, value):")
    out.append("    if value not in ('true', 'false'):")
    out.append("        raise ContractViolation('query param ' + name + \" must be 'true' or 'false'\")")
    out.append("    return value == 'true'")
    out.append("")

    if app.auth:
        out.append("")
        out.append("# ------------------------------------------------------------ auth runtime")
        out.append("")
        out.append(f"AUTH_ROLES = {app.auth.roles!r}")
        out.append(f"AUTH_DEFAULT_ROLE = {app.auth.default_role!r}")
        out.append(f"AUTH_FIRST_USER_ROLE = {app.auth.first_user_role!r}")
        out.append("")
        out.append("")
        out.append("def _hash_password(password, salt):")
        out.append("    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000).hex()")
        out.append("")
        out.append("")
        out.append("def _public_user(row):")
        out.append("    return {'id': row['id'], 'email': row['email'], 'role': row['role']}")
        out.append("")
        out.append("")
        out.append("def auth_create_user(email, password, role=None):")
        out.append("    if not isinstance(email, str) or '@' not in email or not (3 <= len(email) <= 200):")
        out.append("        raise ContractViolation('email must look like an email address')")
        out.append("    if not isinstance(password, str) or len(password) < 8:")
        out.append("        raise ContractViolation('password must be at least 8 characters')")
        out.append("    conn = _db()")
        out.append("    try:")
        out.append("        if role is None:")
        out.append("            has_users = conn.execute('SELECT 1 FROM user LIMIT 1').fetchone() is not None")
        out.append("            role = AUTH_DEFAULT_ROLE if has_users else AUTH_FIRST_USER_ROLE")
        out.append("        if role not in AUTH_ROLES:")
        out.append("            raise ContractViolation('unknown role: ' + str(role))")
        out.append("        salt = secrets.token_hex(16)")
        out.append("        row = {'id': str(uuid.uuid4()), 'email': email, 'password_hash': _hash_password(password, salt), 'salt': salt, 'role': role, 'created_at': _now()}")
        out.append("        try:")
        out.append("            conn.execute('INSERT INTO user (id, email, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?, ?)',")
        out.append("                         (row['id'], row['email'], row['password_hash'], row['salt'], row['role'], row['created_at']))")
        out.append("        except sqlite3.IntegrityError:")
        out.append("            raise ContractViolation('email already registered')")
        out.append("        conn.commit()")
        out.append("    finally:")
        out.append("        conn.close()")
        out.append("    return _public_user(row)")
        out.append("")
        out.append("")
        out.append("def _auth_login(email, password):")
        out.append("    conn = _db()")
        out.append("    try:")
        out.append("        row = conn.execute('SELECT * FROM user WHERE email = ?', (email,)).fetchone()")
        out.append("        if row is None or _hash_password(password, row['salt']) != row['password_hash']:")
        out.append("            raise ContractViolation('invalid email or password')")
        out.append("        token = secrets.token_hex(32)")
        out.append("        conn.execute('INSERT INTO session (token, user_id, created_at) VALUES (?, ?, ?)', (token, row['id'], _now()))")
        out.append("        conn.commit()")
        out.append("    finally:")
        out.append("        conn.close()")
        out.append("    return token, _public_user(row)")
        out.append("")
        out.append("")
        out.append("def _auth_logout(token):")
        out.append("    conn = _db()")
        out.append("    try:")
        out.append("        conn.execute('DELETE FROM session WHERE token = ?', (token,))")
        out.append("        conn.commit()")
        out.append("    finally:")
        out.append("        conn.close()")
        out.append("")
        out.append("")
        out.append("def _auth_user_for_token(token):")
        out.append("    if not token:")
        out.append("        return None")
        out.append("    conn = _db()")
        out.append("    try:")
        out.append("        row = conn.execute('SELECT u.* FROM user u JOIN session s ON s.user_id = u.id WHERE s.token = ?', (token,)).fetchone()")
        out.append("    finally:")
        out.append("        conn.close()")
        out.append("    return _public_user(row) if row else None")
        out.append("")

    for action in app.actions:
        out.append("")
        out.extend(_emit_action(app, action))
        out.append("")

    for query in app.queries:
        out.append("")
        out.extend(_emit_query(app, query))
        out.append("")

    action_entries = []
    for action in app.actions:
        specs = ", ".join(f"({n!r}, {_COERCE[t]})" for n, t in action.inputs)
        action_entries.append(f"    {action.name!r}: (action_{action.name}, [{specs}]),")
    query_entries = []
    for q in app.queries:
        specs = ", ".join(f"({n!r}, {_QCOERCE[t]})" for n, t in q.inputs)
        query_entries.append(f"    {q.name!r}: (query_{q.name}, [{specs}]),")
    routes = sorted({p.route for p in app.pages})

    out.append("")
    out.append("ACTIONS = {")
    out.extend(action_entries)
    out.append("}")
    out.append("")
    out.append("QUERIES = {")
    out.extend(query_entries)
    out.append("}")
    out.append("")
    out.append(f"PAGE_ROUTES = {routes!r}")
    out.append("")
    out.append("")
    out.append("class Handler(BaseHTTPRequestHandler):")
    out.append("    server_version = 'miura/0.6'")
    out.append("")
    out.append("    def _send_json(self, status, payload, extra_headers=()):")
    out.append("        body = json.dumps(payload).encode('utf-8')")
    out.append("        self.send_response(status)")
    out.append("        self.send_header('Content-Type', 'application/json')")
    out.append("        self.send_header('Content-Length', str(len(body)))")
    out.append("        for key, value in extra_headers:")
    out.append("            self.send_header(key, value)")
    out.append("        self.end_headers()")
    out.append("        self.wfile.write(body)")
    out.append("")
    if app.auth:
        out.append("    def _session_token(self):")
        out.append("        cookie = self.headers.get('Cookie') or ''")
        out.append("        for part in cookie.split(';'):")
        out.append("            name, _, value = part.strip().partition('=')")
        out.append("            if name == 'miura_session':")
        out.append("                return value")
        out.append("        return ''")
        out.append("")
        out.append("    def _ctx(self):")
        out.append("        return {'user': _auth_user_for_token(self._session_token())}")
        out.append("")
        out.append("    @staticmethod")
        out.append("    def _cookie(token):")
        out.append("        return ('Set-Cookie', 'miura_session=' + token + '; Path=/; HttpOnly; SameSite=Lax')")
        out.append("")
    else:
        out.append("    def _ctx(self):")
        out.append("        return {'user': None}")
        out.append("")
    out.append("    def _send_denied(self, ctx, err):")
    out.append("        self._send_json(401 if ctx['user'] is None else 403, {'error': str(err)})")
    out.append("")
    out.append("    def do_GET(self):")
    out.append("        path, _, query_string = self.path.partition('?')")
    out.append("        ctx = self._ctx()")
    if app.auth:
        out.append("        if path == '/api/auth/me':")
        out.append("            self._send_json(200, ctx['user'])")
        out.append("            return")
    out.append("        if path.startswith('/api/'):")
    out.append("            name = path[len('/api/'):]")
    out.append("            if name not in QUERIES:")
    out.append("                self._send_json(404, {'error': 'unknown query: ' + name})")
    out.append("                return")
    out.append("            fn, input_spec = QUERIES[name]")
    out.append("            try:")
    out.append("                params = dict(urllib.parse.parse_qsl(query_string))")
    out.append("                try:")
    out.append("                    offset = max(0, int(params.get('offset', 0)))")
    out.append("                except ValueError:")
    out.append("                    raise ContractViolation('offset must be an integer')")
    out.append("                inp = {}")
    out.append("                for iname, coerce in input_spec:")
    out.append("                    if iname not in params:")
    out.append("                        raise ContractViolation('missing query param: ' + iname)")
    out.append("                    inp[iname] = coerce(iname, params[iname])")
    out.append("                self._send_json(200, fn(inp, ctx, offset))")
    out.append("            except PermissionDenied as err:")
    out.append("                self._send_denied(ctx, err)")
    out.append("            except ContractViolation as err:")
    out.append("                self._send_json(400, {'error': str(err)})")
    out.append("            return")
    out.append("        if path in PAGE_ROUTES:")
    out.append("            with open(os.path.join(WEB_DIR, 'index.html'), 'rb') as fh:")
    out.append("                body = fh.read()")
    out.append("            self.send_response(200)")
    out.append("            self.send_header('Content-Type', 'text/html; charset=utf-8')")
    out.append("            self.send_header('Content-Length', str(len(body)))")
    out.append("            self.end_headers()")
    out.append("            self.wfile.write(body)")
    out.append("            return")
    out.append("        self._send_json(404, {'error': 'not found'})")
    out.append("")
    out.append("    def _read_body(self):")
    out.append("        length = int(self.headers.get('Content-Length') or 0)")
    out.append("        raw = self.rfile.read(length) if length else b'{}'")
    out.append("        try:")
    out.append("            payload = json.loads(raw)")
    out.append("        except ValueError:")
    out.append("            raise ContractViolation('request body must be JSON')")
    out.append("        if not isinstance(payload, dict):")
    out.append("            raise ContractViolation('request body must be a JSON object')")
    out.append("        return payload")
    out.append("")
    out.append("    def do_POST(self):")
    out.append("        path = self.path.split('?', 1)[0]")
    out.append("        ctx = self._ctx()")
    if app.auth:
        out.append("        if path in ('/api/auth/signup', '/api/auth/login', '/api/auth/logout'):")
        out.append("            try:")
        out.append("                if path == '/api/auth/logout':")
        out.append("                    _auth_logout(self._session_token())")
        out.append("                    self._send_json(200, {'ok': True}, [self._cookie('')])")
        out.append("                    return")
        out.append("                payload = self._read_body()")
        out.append("                email = payload.get('email')")
        out.append("                password = payload.get('password')")
        out.append("                if path == '/api/auth/signup':")
        out.append("                    auth_create_user(email, password)")
        out.append("                token, user = _auth_login(email, password)")
        out.append("                self._send_json(200, user, [self._cookie(token)])")
        out.append("            except ContractViolation as err:")
        out.append("                self._send_json(400, {'error': str(err)})")
        out.append("            return")
    out.append("        if not path.startswith('/api/'):")
    out.append("            self._send_json(404, {'error': 'not found'})")
    out.append("            return")
    out.append("        name = path[len('/api/'):]")
    out.append("        if name not in ACTIONS:")
    out.append("            self._send_json(404, {'error': 'unknown action: ' + name})")
    out.append("            return")
    out.append("        fn, input_spec = ACTIONS[name]")
    out.append("        try:")
    out.append("            payload = self._read_body()")
    out.append("            inp = {}")
    out.append("            for iname, coerce in input_spec:")
    out.append("                if iname not in payload:")
    out.append("                    raise ContractViolation('missing input: ' + iname)")
    out.append("                inp[iname] = coerce(iname, payload[iname])")
    out.append("            self._send_json(200, fn(inp, ctx))")
    out.append("        except PermissionDenied as err:")
    out.append("            self._send_denied(ctx, err)")
    out.append("        except ContractViolation as err:")
    out.append("            self._send_json(400, {'error': str(err)})")
    out.append("        except EnsuresViolation as err:")
    out.append("            self._send_json(500, {'error': str(err)})")
    out.append("")
    out.append("    def log_message(self, fmt, *args):")
    out.append("        pass")
    out.append("")
    out.append("")
    out.append("def init_db():")
    out.append("    conn = sqlite3.connect(DB_PATH)")
    out.append("    try:")
    out.append("        conn.executescript(SCHEMA_SQL)")
    out.append("        conn.commit()")
    out.append("    finally:")
    out.append("        conn.close()")
    out.append("")
    out.append("")
    out.append("def main():")
    out.append("    init_db()")
    out.append("    port = int(os.environ.get('MIURA_PORT') or os.environ.get('UPL_PORT') or '8000')")
    out.append("    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)")
    out.append("    print('miura app listening on http://127.0.0.1:%d' % port, flush=True)")
    out.append("    server.serve_forever()")
    out.append("")
    out.append("")
    out.append("if __name__ == '__main__':")
    out.append("    main()")
    return "\n".join(out) + "\n"
