from lib import as_bool, pause


def run(app, c):
    st, body = app.page()
    c.check("page serves html", st == 200 and "<" in body, f"status {st}")

    st, i1 = app.post("add_item", {"name": "Telescope", "priority": 9})
    c.check("add valid -> 200", st == 200, f"{st} {i1}")
    c.check("purchased defaults false", isinstance(i1, dict) and not as_bool(i1.get("purchased", True)), i1)

    st, err = app.post("add_item", {"name": "bad", "priority": 0})
    c.check("priority 0 -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_item", {"name": "bad", "priority": 11})
    c.check("priority 11 -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_item", {"name": "", "priority": 5})
    c.check("empty name -> 400", st == 400, f"{st} {err}")

    pause()
    st, i2 = app.post("add_item", {"name": "Socks", "priority": 2})
    c.check("second add -> 200", st == 200, f"{st} {i2}")
    pause()
    st, i3 = app.post("add_item", {"name": "Bike", "priority": 6})
    c.check("third add -> 200", st == 200, f"{st} {i3}")

    st, rows = app.get("list_items")
    c.check("list by priority desc", st == 200 and isinstance(rows, list) and [r.get("priority") for r in rows] == [9, 6, 2], rows)

    st, m = app.post("mark_purchased", {"id": i1["id"]})
    c.check("mark -> purchased true", st == 200 and isinstance(m, dict) and as_bool(m.get("purchased")), f"{st} {m}")
    st, todo = app.get("list_unpurchased")
    c.check("unpurchased excludes marked, priority desc", st == 200 and isinstance(todo, list) and [r.get("priority") for r in todo] == [6, 2], todo)

    st, m = app.post("unmark_purchased", {"id": i1["id"]})
    c.check("unmark -> purchased false", st == 200 and isinstance(m, dict) and not as_bool(m.get("purchased", True)), f"{st} {m}")
    st, todo = app.get("list_unpurchased")
    c.check("unmarked back in unpurchased", st == 200 and isinstance(todo, list) and len(todo) == 3, todo)

    st, err = app.post("mark_purchased", {"id": "ghost"})
    c.check("mark unknown -> 400", st == 400, f"{st} {err}")

    st, d = app.post("delete_item", {"id": i2["id"]})
    c.check("delete -> 200", st == 200, f"{st} {d}")
    st, rows = app.get("list_items")
    c.check("deleted gone", st == 200 and isinstance(rows, list) and len(rows) == 2, rows)
    st, err = app.post("delete_item", {"id": "ghost"})
    c.check("delete unknown -> 400", st == 400, f"{st} {err}")
