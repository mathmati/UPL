from lib import as_bool, pause


def run(app, c):
    st, body = app.page()
    c.check("page serves html", st == 200 and "<" in body, f"status {st}")

    st, t1 = app.post("open_ticket", {"title": "Printer on fire", "priority": 5})
    c.check("open valid -> 200", st == 200, f"{st} {t1}")
    c.check("open defaults open=true", isinstance(t1, dict) and as_bool(t1.get("open")), t1)

    st, err = app.post("open_ticket", {"title": "bad", "priority": 0})
    c.check("priority 0 -> 400", st == 400, f"{st} {err}")
    st, err = app.post("open_ticket", {"title": "bad", "priority": 6})
    c.check("priority 6 -> 400", st == 400, f"{st} {err}")
    st, err = app.post("open_ticket", {"title": "", "priority": 3})
    c.check("empty title -> 400", st == 400, f"{st} {err}")

    pause()
    st, t2 = app.post("open_ticket", {"title": "Low prio papercut", "priority": 1})
    c.check("second open -> 200", st == 200, f"{st} {t2}")
    pause()
    st, t3 = app.post("open_ticket", {"title": "Mid prio", "priority": 3})
    c.check("third open -> 200", st == 200, f"{st} {t3}")

    st, rows = app.get("list_tickets")
    c.check("list_tickets newest first", st == 200 and isinstance(rows, list) and len(rows) == 3 and rows[0].get("id") == t3["id"], rows)

    st, opens = app.get("list_open")
    c.check("list_open priority desc", st == 200 and isinstance(opens, list) and [r.get("priority") for r in opens] == [5, 3, 1], opens)

    st, closed = app.post("close_ticket", {"id": t1["id"]})
    c.check("close -> open false", st == 200 and isinstance(closed, dict) and not as_bool(closed.get("open", True)), f"{st} {closed}")
    st, opens = app.get("list_open")
    c.check("closed ticket left list_open", st == 200 and isinstance(opens, list) and all(r.get("id") != t1["id"] for r in opens) and len(opens) == 2, opens)

    st, reopened = app.post("reopen_ticket", {"id": t1["id"]})
    c.check("reopen -> open true", st == 200 and isinstance(reopened, dict) and as_bool(reopened.get("open")), f"{st} {reopened}")
    st, opens = app.get("list_open")
    c.check("reopened back in list_open", st == 200 and isinstance(opens, list) and len(opens) == 3, opens)

    st, err = app.post("close_ticket", {"id": "nope"})
    c.check("close unknown -> 400", st == 400, f"{st} {err}")

    st, d = app.post("delete_ticket", {"id": t2["id"]})
    c.check("delete -> 200", st == 200, f"{st} {d}")
    st, rows = app.get("list_tickets")
    c.check("deleted gone", st == 200 and isinstance(rows, list) and len(rows) == 2, rows)
