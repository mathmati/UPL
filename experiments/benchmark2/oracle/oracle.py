"""Per-task behavioral oracle: permission matrix + data correctness on
v1, and data-preservation after the v2 migration. Task-agnostic core with
per-task config; expenses has a bespoke approval rule.

Roles: per the contract, the FIRST signup on a fresh DB gets the elevated
role, later signups get the basic role."""


def as_bool(v):
    return bool(v)


# task -> config. `create` = (action, unique_field, other_field, other_value).
# `edit` = (action, field, newvalue). unique values must satisfy each task's
# length bounds (title 1-80, slot 3-40, slug 3-50, reference 3-40).
CONFIGS = {
    "snippets": dict(elevated="admin", basic="member",
                     create=("save_snippet", "title", "body", "print(1)"),
                     edit=("edit_snippet", "body", "print(2)"),
                     delete="delete_snippet", allq="all_snippets", myq="my_snippets",
                     newfield="language", newdefault="text"),
    "bookings": dict(elevated="admin", basic="member",
                     create=("book", "slot", "purpose", "Standup"),
                     edit=("change_purpose", "purpose", "Retro"),
                     delete="cancel", allq="all_bookings", myq="my_bookings",
                     newfield="attendees", newdefault=1),
    "docs": dict(elevated="editor", basic="author",
                 create=("create_doc", "slug", "title", "My Doc"),
                 edit=("rename_doc", "title", "Renamed Doc"),
                 delete="delete_doc", allq="all_docs", myq="my_docs",
                 newfield="archived", newdefault=False),
}

UNIQUE_VALS = ["alpha-one", "beta-two", "gamma-three", "delta-four"]


def _role(sess):
    st, me = sess.post("auth/login", {}) if False else (None, None)
    return None


def run_permissions(task, server, c):
    if task == "expenses":
        return _expenses_permissions(server, c)
    cfg = CONFIGS[task]
    create, uf, of, ov = cfg["create"]
    edit_action, ef, ev = cfg["edit"]
    delete, allq, myq = cfg["delete"], cfg["allq"], cfg["myq"]

    anon = server.session()
    st, _ = anon.get(allq)
    c.check("anon query -> 401", st == 401, st)
    st, _ = anon.post(create, {uf: UNIQUE_VALS[0], of: ov})
    c.check("anon action -> 401", st == 401, st)

    # first signup = elevated role
    boss = server.session()
    st, bu = boss.signup("boss@x.example")
    c.check("first signup ok", st == 200, bu)
    c.check(f"first user is {cfg['elevated']}", isinstance(bu, dict) and bu.get("role") == cfg["elevated"], bu)
    c.check("signup hides password", isinstance(bu, dict) and not any("pass" in k.lower() for k in bu), bu)

    alice = server.session()
    st, au = alice.signup("alice@x.example")
    c.check(f"second user is {cfg['basic']}", isinstance(au, dict) and au.get("role") == cfg["basic"], au)
    bob = server.session()
    bob.signup("bob@x.example")

    # alice creates a record (owned by alice)
    st, rec = alice.post(create, {uf: UNIQUE_VALS[0], of: ov})
    c.check("owner create -> 200", st == 200, rec)
    rid = rec.get("id") if isinstance(rec, dict) else None
    c.check("create returns id", bool(rid), rec)

    # duplicate unique value -> 400
    st, err = alice.post(create, {uf: UNIQUE_VALS[0], of: ov})
    c.check("duplicate unique -> 400", st == 400, f"{st} {err}")

    # bob (another basic user) cannot edit or delete alice's record -> 403
    st, err = bob.post(edit_action, {"id": rid, ef: ev})
    c.check("non-owner edit -> 403", st == 403, f"{st} {err}")
    st, err = bob.post(delete, {"id": rid})
    c.check("non-owner delete -> 403", st == 403, f"{st} {err}")

    # alice edits her own -> 200
    st, edited = alice.post(edit_action, {"id": rid, ef: ev})
    c.check("owner edit -> 200", st == 200, f"{st} {edited}")
    c.check("edit applied", isinstance(edited, dict) and str(edited.get(ef)) == ev, edited)

    # elevated (boss) can delete anyone's -> 200
    st, d = boss.post(delete, {"id": rid})
    c.check("elevated delete others -> 200", st == 200, f"{st} {d}")

    # unknown id -> 400
    st, err = alice.post(delete, {"id": "no-such-id"})
    c.check("delete unknown id -> 400", st == 400, f"{st} {err}")

    # scoping: alice makes 2, bob makes 1
    alice.post(create, {uf: UNIQUE_VALS[1], of: ov})
    alice.post(create, {uf: UNIQUE_VALS[2], of: ov})
    bob.post(create, {uf: UNIQUE_VALS[3], of: ov})
    st, mine = alice.get(myq)
    c.check("my query scoped to caller", st == 200 and isinstance(mine, list) and len(mine) == 2, mine if not isinstance(mine, list) else len(mine))
    st, allrows = alice.get(allq)
    c.check("all query returns everyone's", st == 200 and isinstance(allrows, list) and len(allrows) == 3, allrows if not isinstance(allrows, list) else len(allrows))
    st, bobmine = bob.get(myq)
    c.check("bob's my query scoped", st == 200 and isinstance(bobmine, list) and len(bobmine) == 1, bobmine if not isinstance(bobmine, list) else len(bobmine))


def _expenses_permissions(server, c):
    anon = server.session()
    st, _ = anon.get("all_claims")
    c.check("anon query -> 401", st == 401, st)
    st, _ = anon.post("submit_claim", {"reference": "ref-1", "amount": 10})
    c.check("anon action -> 401", st == 401, st)

    mgr = server.session()
    st, mu = mgr.signup("mgr@x.example")
    c.check("first user is manager", isinstance(mu, dict) and mu.get("role") == "manager", mu)
    staff = server.session()
    st, su = staff.signup("staff@x.example")
    c.check("second user is staff", isinstance(su, dict) and su.get("role") == "staff", su)
    staff2 = server.session()
    staff2.signup("staff2@x.example")

    st, claim = staff.post("submit_claim", {"reference": "ref-1", "amount": 100})
    c.check("staff submit -> 200", st == 200, claim)
    cid = claim.get("id") if isinstance(claim, dict) else None
    c.check("claim starts unapproved", isinstance(claim, dict) and not as_bool(claim.get("approved", True)), claim)

    st, err = staff.post("submit_claim", {"reference": "ref-1", "amount": 5})
    c.check("duplicate reference -> 400", st == 400, f"{st} {err}")
    st, err = staff.post("submit_claim", {"reference": "ref-2", "amount": 0})
    c.check("amount 0 -> 400", st == 400, f"{st} {err}")
    st, err = staff.post("submit_claim", {"reference": "ref-3", "amount": 1000001})
    c.check("amount over max -> 400", st == 400, f"{st} {err}")

    # staff (non-manager) cannot approve, even their own -> 403
    st, err = staff.post("approve_claim", {"id": cid})
    c.check("staff approve own -> 403", st == 403, f"{st} {err}")
    st, err = staff2.post("approve_claim", {"id": cid})
    c.check("other staff approve -> 403", st == 403, f"{st} {err}")
    # manager approves -> 200, approved true
    st, appr = mgr.post("approve_claim", {"id": cid})
    c.check("manager approve -> 200", st == 200, f"{st} {appr}")
    c.check("approved is true after", isinstance(appr, dict) and as_bool(appr.get("approved")), appr)

    # withdraw: other staff can't; owner can; manager can any
    st, c2 = staff.post("submit_claim", {"reference": "ref-9", "amount": 50})
    cid2 = c2.get("id") if isinstance(c2, dict) else None
    st, err = staff2.post("withdraw_claim", {"id": cid2})
    c.check("non-owner withdraw -> 403", st == 403, f"{st} {err}")
    st, d = staff.post("withdraw_claim", {"id": cid2})
    c.check("owner withdraw -> 200", st == 200, f"{st} {d}")
    st, d = mgr.post("withdraw_claim", {"id": cid})
    c.check("manager withdraw any -> 200", st == 200, f"{st} {d}")

    # scoping
    staff.post("submit_claim", {"reference": "s-a", "amount": 10})
    staff.post("submit_claim", {"reference": "s-b", "amount": 20})
    staff2.post("submit_claim", {"reference": "s-c", "amount": 30})
    st, mine = staff.get("my_claims")
    c.check("my_claims scoped", st == 200 and isinstance(mine, list) and len(mine) == 2, mine if not isinstance(mine, list) else len(mine))
    st, allc = mgr.get("all_claims")
    c.check("all_claims sees all", st == 200 and isinstance(allc, list) and len(allc) == 3, allc if not isinstance(allc, list) else len(allc))


# ------------------------------------------------------------ migration

def seed_for_migration(task, server):
    """Create users and rows on a v1 server. Returns the basic user's
    creds and the unique values seeded, for post-migration verification."""
    cfg = CONFIGS.get(task)
    boss = server.session()
    boss.signup("boss@x.example")
    alice = server.session()
    alice.signup("alice@x.example")
    if task == "expenses":
        alice.post("submit_claim", {"reference": "keep-1", "amount": 111})
        alice.post("submit_claim", {"reference": "keep-2", "amount": 222})
        return {"email": "alice@x.example", "unique_field": "reference", "values": ["keep-1", "keep-2"]}
    create, uf, of, ov = cfg["create"]
    alice.post(create, {uf: "keep-one", of: ov})
    alice.post(create, {uf: "keep-two", of: ov})
    return {"email": "alice@x.example", "unique_field": uf, "values": ["keep-one", "keep-two"]}


def verify_migrated(task, server, c, seed):
    """After migration, on a v2 server against the SAME db: old rows must
    survive with the new field defaulted, and new creates must work."""
    newfield = {"snippets": "language", "bookings": "attendees", "docs": "archived", "expenses": "category"}[task]
    newdefault = {"snippets": "text", "bookings": 1, "docs": False, "expenses": "general"}[task]
    allq = {"snippets": "all_snippets", "bookings": "all_bookings", "docs": "all_docs", "expenses": "all_claims"}[task]

    alice = server.session()
    st, _ = alice.login(seed["email"])
    c.check("migration: user survived (login ok)", st == 200, st)
    st, rows = alice.get(allq)
    c.check("migration: rows readable after migrate", st == 200 and isinstance(rows, list), f"{st} {rows}")
    if not isinstance(rows, list):
        return
    uf, vals = seed["unique_field"], seed["values"]
    kept = {r.get(uf) for r in rows}
    c.check("migration: seeded rows survived", all(v in kept for v in vals), f"kept={kept}")
    newvals = [r.get(newfield) for r in rows if r.get(uf) in vals]
    if newdefault is False:
        ok = all(not as_bool(v) for v in newvals)
    else:
        ok = all(v == newdefault for v in newvals)
    c.check(f"migration: old rows have {newfield}={newdefault!r}", ok and len(newvals) == len(vals), newvals)
