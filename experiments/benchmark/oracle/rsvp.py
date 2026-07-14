from lib import as_bool, pause


def run(app, c):
    st, body = app.page()
    c.check("page serves html", st == 200 and "<" in body, f"status {st}")

    st, e1 = app.post("create_event", {"name": "Launch party"})
    c.check("create_event -> 200", st == 200, f"{st} {e1}")
    pause()
    st, e2 = app.post("create_event", {"name": "Retro"})
    c.check("second event -> 200", st == 200, f"{st} {e2}")

    st, err = app.post("create_event", {"name": ""})
    c.check("empty event name -> 400", st == 400, f"{st} {err}")

    st, rows = app.get("list_events")
    c.check("events newest first", st == 200 and isinstance(rows, list) and len(rows) == 2 and rows[0].get("id") == e2["id"], rows)

    st, g1 = app.post("add_guest", {"event_id": e1["id"], "name": "Ada"})
    c.check("add_guest -> 200", st == 200, f"{st} {g1}")
    c.check("guest attending defaults true", isinstance(g1, dict) and as_bool(g1.get("attending")), g1)
    pause()
    st, g2 = app.post("add_guest", {"event_id": e1["id"], "name": "Grace"})
    c.check("second guest -> 200", st == 200, f"{st} {g2}")
    st, g3 = app.post("add_guest", {"event_id": e2["id"], "name": "Linus"})
    c.check("guest on other event -> 200", st == 200, f"{st} {g3}")

    st, err = app.post("add_guest", {"event_id": "ghost-event", "name": "Nobody"})
    c.check("guest on missing event -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_guest", {"event_id": e1["id"], "name": ""})
    c.check("empty guest name -> 400", st == 400, f"{st} {err}")

    st, guests = app.get("guests_for_event", {"event_id": e1["id"]})
    c.check("guests scoped to event 1", st == 200 and isinstance(guests, list) and len(guests) == 2, guests)
    c.check("guests oldest first", isinstance(guests, list) and len(guests) == 2 and guests[0].get("name") == "Ada", guests)
    st, guests2 = app.get("guests_for_event", {"event_id": e2["id"]})
    c.check("guests scoped to event 2", st == 200 and isinstance(guests2, list) and len(guests2) == 1 and guests2[0].get("name") == "Linus", guests2)

    st, t = app.post("toggle_attending", {"id": g1["id"]})
    c.check("toggle attending -> false", st == 200 and isinstance(t, dict) and not as_bool(t.get("attending", True)), f"{st} {t}")
    st, err = app.post("toggle_attending", {"id": "ghost-guest"})
    c.check("toggle unknown guest -> 400", st == 400, f"{st} {err}")

    st, d = app.post("remove_guest", {"id": g2["id"]})
    c.check("remove_guest -> 200", st == 200, f"{st} {d}")
    st, guests = app.get("guests_for_event", {"event_id": e1["id"]})
    c.check("removed guest gone", st == 200 and isinstance(guests, list) and len(guests) == 1, guests)

    st, d = app.post("delete_event", {"id": e1["id"]})
    c.check("delete_event -> 200", st == 200, f"{st} {d}")
    st, guests = app.get("guests_for_event", {"event_id": e1["id"]})
    c.check("event's guests cascaded away", st == 200 and guests == [], guests)
    st, guests2 = app.get("guests_for_event", {"event_id": e2["id"]})
    c.check("other event's guests intact", st == 200 and isinstance(guests2, list) and len(guests2) == 1, guests2)
    st, rows = app.get("list_events")
    c.check("event deleted from list", st == 200 and isinstance(rows, list) and len(rows) == 1, rows)
