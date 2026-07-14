from lib import as_bool, pause


def run(app, c):
    st, body = app.page()
    c.check("page serves html", st == 200 and "<" in body, f"status {st}")

    st, b1 = app.post("add_bookmark", {"title": "Claude docs", "url": "https://docs.claude.com"})
    c.check("add valid -> 200", st == 200, f"{st} {b1}")
    c.check("add echoes title", isinstance(b1, dict) and b1.get("title") == "Claude docs", b1)
    c.check("favorite defaults false", isinstance(b1, dict) and not as_bool(b1.get("favorite", True)), b1)
    c.check("add returns id", isinstance(b1, dict) and b1.get("id") not in (None, ""), b1)

    st, err = app.post("add_bookmark", {"title": "", "url": "https://example.com"})
    c.check("empty title -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_bookmark", {"title": "x" * 101, "url": "https://example.com"})
    c.check("101-char title -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_bookmark", {"title": "ok", "url": "http://"})
    c.check("7-char url -> 400", st == 400, f"{st} {err}")

    pause()
    st, b2 = app.post("add_bookmark", {"title": "Second", "url": "https://second.example"})
    c.check("second add -> 200", st == 200, f"{st} {b2}")

    st, rows = app.get("list_bookmarks")
    c.check("list -> 200 array", st == 200 and isinstance(rows, list), f"{st} {rows}")
    c.check("list has 2", isinstance(rows, list) and len(rows) == 2, rows if not isinstance(rows, list) else len(rows))
    c.check("newest first", isinstance(rows, list) and len(rows) == 2 and rows[0].get("title") == "Second", rows)

    st, t = app.post("toggle_favorite", {"id": b1["id"]})
    c.check("toggle -> 200 and true", st == 200 and isinstance(t, dict) and as_bool(t.get("favorite")), f"{st} {t}")
    st, favs = app.get("list_favorites")
    c.check("favorites has exactly the toggled one", st == 200 and isinstance(favs, list) and len(favs) == 1 and favs[0].get("id") == b1["id"], favs)

    st, t = app.post("toggle_favorite", {"id": b1["id"]})
    c.check("toggle back -> false", st == 200 and isinstance(t, dict) and not as_bool(t.get("favorite", True)), f"{st} {t}")
    st, favs = app.get("list_favorites")
    c.check("favorites empty again", st == 200 and favs == [], favs)

    st, err = app.post("toggle_favorite", {"id": "definitely-not-real"})
    c.check("toggle unknown id -> 400", st == 400, f"{st} {err}")

    st, d = app.post("delete_bookmark", {"id": b2["id"]})
    c.check("delete -> 200", st == 200, f"{st} {d}")
    st, rows = app.get("list_bookmarks")
    c.check("deleted gone", st == 200 and isinstance(rows, list) and len(rows) == 1 and rows[0].get("id") == b1["id"], rows)
    st, err = app.post("delete_bookmark", {"id": "definitely-not-real"})
    c.check("delete unknown id -> 400", st == 400, f"{st} {err}")
