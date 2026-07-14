"""Deterministic web frontend emitter.

The UI dialect is serialized to a JSON model embedded in a single
self-contained index.html; a fixed renderer runtime interprets it.
Keeping the runtime constant means bundle diffs produce minimal,
reviewable HTML diffs (only the UI_MODEL changes)."""

from __future__ import annotations

import json

from .model import App, Button, Checkbox, Form, Heading, List, Text


def _component_json(c):
    if isinstance(c, Heading):
        return {"kind": "heading", "text": c.text}
    if isinstance(c, Form):
        return {
            "kind": "form", "action": c.action,
            "fields": [{"name": f.name, "label": f.label, "from": f.from_field} for f in c.fields],
            "binds": [{"input": a, "from": b} for a, b in c.binds],
        }
    if isinstance(c, List):
        return {
            "kind": "list", "query": c.query,
            "args": [{"input": a, "from": b} for a, b in c.args],
            "item": [_component_json(i) for i in c.item],
        }
    if isinstance(c, Text):
        return {"kind": "text", "field": c.field}
    if isinstance(c, Checkbox):
        return {"kind": "checkbox", "bind": c.bind, "action": c.action, "args": [{"input": a, "from": b} for a, b in c.args]}
    if isinstance(c, Button):
        return {"kind": "button", "label": c.label, "action": c.action, "args": [{"input": a, "from": b} for a, b in c.args]}
    raise AssertionError(c)


def _ui_model(app: App) -> dict:
    input_types = {a.name: {n: t for n, t in a.inputs} for a in app.actions}
    page_sizes = {q.name: q.page_size for q in app.queries if q.page_size}
    return {
        "pages": [
            {"name": p.name, "route": p.route, "components": [_component_json(c) for c in p.components]}
            for p in app.pages
        ],
        "inputTypes": input_types,
        "pageSizes": page_sizes,
        "auth": bool(app.auth),
    }


_RUNTIME_CSS = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
h1 { font-size: 1.4rem; }
form { display: flex; gap: 0.5rem; margin: 1rem 0; flex-wrap: wrap; }
form label { display: flex; flex-direction: column; font-size: 0.85rem; gap: 0.15rem; }
input[type=text], input[type=number] { padding: 0.4rem 0.6rem; font-size: 1rem; }
button { padding: 0.4rem 0.8rem; font-size: 0.95rem; cursor: pointer; }
.miura-list { display: flex; flex-direction: column; gap: 0.35rem; margin: 1rem 0; }
.miura-item { display: flex; align-items: center; gap: 0.6rem; padding: 0.45rem 0.6rem; border: 1px solid color-mix(in srgb, currentColor 25%, transparent); border-radius: 6px; flex-wrap: wrap; }
.miura-item .miura-text { flex: 1; overflow-wrap: anywhere; }
.miura-item .miura-nested, .miura-item form, .miura-item .miura-subheading { flex-basis: 100%; }
.miura-nested { margin-left: 1.2rem; }
.miura-subheading { font-size: 1rem; margin: 0.3rem 0 0; }
#miura-error { color: #b3261e; min-height: 1.4em; font-size: 0.9rem; }
.miura-more { align-self: flex-start; margin-top: 0.4rem; }
#miura-auth { display: flex; gap: 0.5rem; align-items: center; justify-content: flex-end; margin-bottom: 0.5rem; font-size: 0.9rem; }
#miura-auth form { display: flex; gap: 0.4rem; margin: 0; }
#miura-auth input { padding: 0.3rem 0.5rem; }
.miura-nav { display: flex; gap: 1rem; margin-bottom: 1rem; }
"""

_RUNTIME_JS = """\
'use strict';

const $error = () => document.getElementById('miura-error');
let errorTimer = null;

function showError(message) {
  $error().textContent = message;
  clearTimeout(errorTimer);
  errorTimer = setTimeout(() => { $error().textContent = ''; }, 6000);
}

async function api(path, options) {
  const res = await fetch(path, options);
  let payload = null;
  try { payload = await res.json(); } catch (e) { /* non-JSON error body */ }
  if (!res.ok) {
    throw new Error((payload && payload.error) || (res.status + ' ' + res.statusText));
  }
  return payload;
}

async function callAction(name, args) {
  return api('/api/' + name, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
}

const topLists = [];

async function refreshAll() {
  for (const inst of topLists) {
    try {
      await renderList(inst.c, inst.el, null);
    } catch (err) {
      showError(err.message);
    }
  }
}

function actionArgs(args, row) {
  const out = {};
  for (const a of args) out[a.input] = row[a.from];
  return out;
}

function queryUrl(c, row, offset) {
  const parts = [];
  if (c.args) for (const a of c.args) parts.push(encodeURIComponent(a.input) + '=' + encodeURIComponent(row[a.from]));
  if (offset) parts.push('offset=' + offset);
  return '/api/' + c.query + (parts.length ? '?' + parts.join('&') : '');
}

async function renderList(c, el, row) {
  const pageSize = UI_MODEL.pageSizes[c.query] || 0;
  const rows = await api(queryUrl(c, row, 0));
  const items = [];
  for (const r of rows) items.push(await renderItem(c.item, r));
  el.replaceChildren(...items);
  if (pageSize && rows.length === pageSize) {
    const more = document.createElement('button');
    more.className = 'miura-more';
    more.textContent = 'Load more';
    let offset = pageSize;
    more.addEventListener('click', async () => {
      try {
        const next = await api(queryUrl(c, row, offset));
        for (const r of next) el.insertBefore(await renderItem(c.item, r), more);
        offset += next.length;
        if (!pageSize || next.length < pageSize) more.remove();
      } catch (err) { showError(err.message); }
    });
    el.appendChild(more);
  }
}

async function renderItem(components, row) {
  const item = document.createElement('div');
  item.className = 'miura-item';
  for (const c of components) {
    if (c.kind === 'text') {
      const span = document.createElement('span');
      span.className = 'miura-text';
      span.textContent = String(row[c.field]);
      item.appendChild(span);
    } else if (c.kind === 'checkbox') {
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = Boolean(row[c.bind]);
      box.addEventListener('change', async () => {
        try { await callAction(c.action, actionArgs(c.args, row)); } catch (err) { showError(err.message); }
        refreshAll();
      });
      item.appendChild(box);
    } else if (c.kind === 'button') {
      const btn = document.createElement('button');
      btn.textContent = c.label;
      btn.addEventListener('click', async () => {
        try { await callAction(c.action, actionArgs(c.args, row)); } catch (err) { showError(err.message); }
        refreshAll();
      });
      item.appendChild(btn);
    } else if (c.kind === 'heading') {
      const h = document.createElement('h2');
      h.className = 'miura-subheading';
      h.textContent = c.text;
      item.appendChild(h);
    } else if (c.kind === 'form') {
      item.appendChild(buildForm(c, row));
    } else if (c.kind === 'list') {
      const el = document.createElement('div');
      el.className = 'miura-list miura-nested';
      await renderList(c, el, row);
      item.appendChild(el);
    }
  }
  return item;
}

function buildForm(c, row) {
  const form = document.createElement('form');
  const types = UI_MODEL.inputTypes[c.action] || {};
  let prefilled = false;
  for (const f of c.fields) {
    const label = document.createElement('label');
    label.append(f.label);
    const input = document.createElement('input');
    const t = types[f.name] || 'text';
    input.type = t === 'int' ? 'number' : t === 'bool' ? 'checkbox' : 'text';
    input.name = f.name;
    if (f.from && row) {
      prefilled = true;
      if (t === 'bool') input.checked = Boolean(row[f.from]);
      else input.value = row[f.from];
    }
    label.appendChild(input);
    form.appendChild(label);
  }
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = prefilled ? 'Save' : 'Add';
  form.appendChild(submit);
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const args = {};
    for (const f of c.fields) {
      const input = form.elements[f.name];
      const t = types[f.name] || 'text';
      args[f.name] = t === 'int' ? Number(input.value) : t === 'bool' ? input.checked : input.value;
    }
    for (const b of (c.binds || [])) args[b.input] = row[b.from];
    try {
      await callAction(c.action, args);
      form.reset();
    } catch (err) {
      showError(err.message);
    }
    refreshAll();
  });
  return form;
}

function renderComponent(c, root) {
  if (c.kind === 'heading') {
    const h = document.createElement('h1');
    h.textContent = c.text;
    root.appendChild(h);
  } else if (c.kind === 'form') {
    root.appendChild(buildForm(c, null));
  } else if (c.kind === 'list') {
    const el = document.createElement('div');
    el.className = 'miura-list';
    topLists.push({ c, el });
    root.appendChild(el);
  }
}

async function renderAuthBar() {
  const bar = document.getElementById('miura-auth');
  bar.replaceChildren();
  let me = null;
  try { me = await api('/api/auth/me'); } catch (err) { showError(err.message); }
  if (me) {
    const who = document.createElement('span');
    who.textContent = me.email + ' (' + me.role + ')';
    const out = document.createElement('button');
    out.textContent = 'Log out';
    out.addEventListener('click', async () => {
      try { await api('/api/auth/logout', { method: 'POST' }); } catch (err) { showError(err.message); }
      location.reload();
    });
    bar.append(who, out);
  } else {
    const form = document.createElement('form');
    const email = document.createElement('input');
    email.type = 'email'; email.name = 'email'; email.placeholder = 'email'; email.required = true;
    const password = document.createElement('input');
    password.type = 'password'; password.name = 'password'; password.placeholder = 'password (8+ chars)'; password.required = true;
    const login = document.createElement('button');
    login.type = 'submit'; login.textContent = 'Log in';
    const signup = document.createElement('button');
    signup.type = 'button'; signup.textContent = 'Sign up';
    const submit = async (path) => {
      try {
        await api(path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email.value, password: password.value }),
        });
        location.reload();
      } catch (err) {
        showError(err.message);
      }
    };
    form.addEventListener('submit', (ev) => { ev.preventDefault(); submit('/api/auth/login'); });
    signup.addEventListener('click', () => submit('/api/auth/signup'));
    form.append(email, password, login, signup);
    bar.appendChild(form);
  }
}

function main() {
  if (UI_MODEL.auth) renderAuthBar();
  const root = document.getElementById('miura-root');
  const page = UI_MODEL.pages.find((p) => p.route === location.pathname) || UI_MODEL.pages[0];
  if (UI_MODEL.pages.length > 1) {
    const nav = document.createElement('nav');
    nav.className = 'miura-nav';
    for (const p of UI_MODEL.pages) {
      const link = document.createElement('a');
      link.href = p.route;
      link.textContent = p.name;
      nav.appendChild(link);
    }
    root.appendChild(nav);
  }
  for (const c of page.components) renderComponent(c, root);
  refreshAll();
}

main();
"""


def emit_web(app: App, header: str) -> str:
    model = json.dumps(_ui_model(app), indent=2, sort_keys=True)
    # </script> inside the JSON would close the tag early; escape defensively.
    model = model.replace("</", "<\\/")
    title = app.pages[0].components[0].text if app.pages and isinstance(app.pages[0].components[0], Heading) else "UPL App"
    comment = "\n".join(f"  {line}" for line in header.splitlines())
    return f"""<!DOCTYPE html>
<!--
{comment}
-->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{_RUNTIME_CSS}</style>
</head>
<body>
<div id="miura-error"></div>
<div id="miura-auth"></div>
<div id="miura-root"></div>
<script>
const UI_MODEL = {model};

{_RUNTIME_JS}</script>
</body>
</html>
"""
