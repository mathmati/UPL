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


def _input_names(action):
    return {name: f'inp[{name!r}]' for name, _ in action.inputs}


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


def _emit_action(app: App, action) -> list:
    ent = app.entity(action.effect.entity)
    table = table_name(ent.name)
    inames = _input_names(action)
    lines = [f"def action_{action.name}(inp):"]
    intent_inputs = ", ".join(f"{n} {t}" for n, t in action.inputs) or "none"
    lines.append(f'    """UPL action {action.name} (inputs: {intent_inputs})."""')

    for expr, src in action.requires:
        cond = E.to_python(expr, inames)
        lines.append(f"    if not {cond}:")
        lines.append(f"        raise ContractViolation('requires failed: ' + {src!r})")

    lines.append("    conn = _db()")
    lines.append("    try:")

    if isinstance(action.effect, Insert):
        assigns = dict((f, e) for f, e, _ in action.effect.assigns)
        row_items = []
        for f in ent.fields:
            if f.name in assigns:
                value = E.to_python(assigns[f.name], inames)
            elif f.auto and f.type == "id":
                value = "str(uuid.uuid4())"
            elif f.auto and f.type == "timestamp":
                value = "_now()"
            else:
                value = repr(f.default)
            row_items.append(f"{f.name!r}: {value}")
        lines.append("        row = {" + ", ".join(row_items) + "}")
        _emit_field_requires_indented(lines, ent, "row")
        cols = ", ".join(f.name for f in ent.fields)
        marks = ", ".join("?" for _ in ent.fields)
        params = ", ".join(f"row[{f.name!r}]" for f in ent.fields)
        lines.append(f'        conn.execute("INSERT INTO {table} ({cols}) VALUES ({marks})", ({params},))')
        lines.append("        conn.commit()")
        lines.append(f'        result = conn.execute("SELECT * FROM {table} WHERE id = ?", (row["id"],)).fetchone()')
    elif isinstance(action.effect, Update):
        id_py = E.to_python(action.effect.id_expr, inames)
        lines.append(f'        current = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
        lines.append("        if current is None:")
        lines.append(f"            raise ContractViolation('no {ent.name} with id ' + str({id_py}))")
        names = dict(inames)
        names["current"] = "current"
        assigned = set()
        update_items = []
        for fname, expr, _src in action.effect.assigns:
            update_items.append(f"{fname!r}: {E.to_python(expr, names)}")
            assigned.add(fname)
        lines.append("        updates = {" + ", ".join(update_items) + "}")
        _emit_field_requires_indented(lines, ent, "updates", assigned)
        set_clause = ", ".join(f"{fname} = ?" for fname, _, _ in action.effect.assigns)
        set_params = ", ".join(f"updates[{fname!r}]" for fname, _, _ in action.effect.assigns)
        lines.append(f'        conn.execute("UPDATE {table} SET {set_clause} WHERE id = ?", ({set_params}, {id_py}))')
        lines.append("        conn.commit()")
        lines.append(f'        result = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
    else:  # Delete
        id_py = E.to_python(action.effect.id_expr, inames)
        lines.append(f'        current = conn.execute("SELECT * FROM {table} WHERE id = ?", ({id_py},)).fetchone()')
        lines.append("        if current is None:")
        lines.append(f"            raise ContractViolation('no {ent.name} with id ' + str({id_py}))")
        lines.append(f'        conn.execute("DELETE FROM {table} WHERE id = ?", ({id_py},))')
        lines.append("        conn.commit()")
        lines.append('        result = {"ok": True}')

    lines.append("    finally:")
    lines.append("        conn.close()")

    ensure_names = dict(inames)
    ensure_names["result"] = "result"
    if isinstance(action.effect, (Update, Delete)):
        ensure_names["current"] = "current"
    for expr, src in action.ensures:
        cond = E.to_python(expr, ensure_names)
        lines.append(f"    if not {cond}:")
        lines.append(f"        raise EnsuresViolation('ensures failed: ' + {src!r})")

    lines.append("    return result")
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
    lines = [f"def query_{query.name}():"]
    lines.append(f'    """UPL query {query.name} over {query.entity}."""')
    lines.append("    conn = _db()")
    lines.append("    try:")
    lines.append(f'        rows = conn.execute("{sql}").fetchall()')
    lines.append("    finally:")
    lines.append("        conn.close()")
    if query.where is not None:
        ent = app.entity(query.entity)
        names = {f.name: f"row[{f.name!r}]" for f in ent.fields}
        cond = E.to_python(query.where, names)
        lines.append(f"    rows = [row for row in rows if {cond}]")
    lines.append("    return rows")
    return lines


def emit_python(app: App, header: str) -> str:
    out = []
    out.extend(f"# {line}" for line in header.splitlines())
    out.append('"""' + app.intent.replace('"""', r"\"\"\"") + '"""')
    out.append("")
    out.append("import json")
    out.append("import os")
    out.append("import sqlite3")
    out.append("import uuid")
    out.append("from datetime import datetime, timezone")
    out.append("from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer")
    out.append("")
    out.append('DB_PATH = os.environ.get("UPL_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db"))')
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
    query_entries = [f"    {q.name!r}: query_{q.name}," for q in app.queries]
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
    out.append("    server_version = 'upl/0.1'")
    out.append("")
    out.append("    def _send_json(self, status, payload):")
    out.append("        body = json.dumps(payload).encode('utf-8')")
    out.append("        self.send_response(status)")
    out.append("        self.send_header('Content-Type', 'application/json')")
    out.append("        self.send_header('Content-Length', str(len(body)))")
    out.append("        self.end_headers()")
    out.append("        self.wfile.write(body)")
    out.append("")
    out.append("    def do_GET(self):")
    out.append("        path = self.path.split('?', 1)[0]")
    out.append("        if path.startswith('/api/'):")
    out.append("            name = path[len('/api/'):]")
    out.append("            if name in QUERIES:")
    out.append("                self._send_json(200, QUERIES[name]())")
    out.append("            else:")
    out.append("                self._send_json(404, {'error': 'unknown query: ' + name})")
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
    out.append("    def do_POST(self):")
    out.append("        path = self.path.split('?', 1)[0]")
    out.append("        if not path.startswith('/api/'):")
    out.append("            self._send_json(404, {'error': 'not found'})")
    out.append("            return")
    out.append("        name = path[len('/api/'):]")
    out.append("        if name not in ACTIONS:")
    out.append("            self._send_json(404, {'error': 'unknown action: ' + name})")
    out.append("            return")
    out.append("        fn, input_spec = ACTIONS[name]")
    out.append("        try:")
    out.append("            length = int(self.headers.get('Content-Length') or 0)")
    out.append("            raw = self.rfile.read(length) if length else b'{}'")
    out.append("            try:")
    out.append("                payload = json.loads(raw)")
    out.append("            except ValueError:")
    out.append("                raise ContractViolation('request body must be JSON')")
    out.append("            if not isinstance(payload, dict):")
    out.append("                raise ContractViolation('request body must be a JSON object')")
    out.append("            inp = {}")
    out.append("            for iname, coerce in input_spec:")
    out.append("                if iname not in payload:")
    out.append("                    raise ContractViolation('missing input: ' + iname)")
    out.append("                inp[iname] = coerce(iname, payload[iname])")
    out.append("            self._send_json(200, fn(inp))")
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
    out.append("    port = int(os.environ.get('UPL_PORT', '8000'))")
    out.append("    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)")
    out.append("    print('upl app listening on http://127.0.0.1:%d' % port, flush=True)")
    out.append("    server.serve_forever()")
    out.append("")
    out.append("")
    out.append("if __name__ == '__main__':")
    out.append("    main()")
    return "\n".join(out) + "\n"
