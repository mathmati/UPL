from lib import pause


def run(app, c):
    st, body = app.page()
    c.check("page serves html", st == 200 and "<" in body, f"status {st}")

    st, d1 = app.post("create_deck", {"name": "Spanish"})
    c.check("create_deck -> 200", st == 200, f"{st} {d1}")
    pause()
    st, d2 = app.post("create_deck", {"name": "Chemistry"})
    c.check("second deck -> 200", st == 200, f"{st} {d2}")
    st, err = app.post("create_deck", {"name": ""})
    c.check("empty deck name -> 400", st == 400, f"{st} {err}")

    st, rows = app.get("list_decks")
    c.check("decks newest first", st == 200 and isinstance(rows, list) and len(rows) == 2 and rows[0].get("id") == d2["id"], rows)

    st, c1 = app.post("add_card", {"deck_id": d1["id"], "front": "hola", "back": "hello"})
    c.check("add_card -> 200", st == 200, f"{st} {c1}")
    c.check("reviews start at 0", isinstance(c1, dict) and c1.get("reviews") == 0, c1)
    pause()
    st, c2 = app.post("add_card", {"deck_id": d1["id"], "front": "gato", "back": "cat"})
    c.check("second card -> 200", st == 200, f"{st} {c2}")
    st, c3 = app.post("add_card", {"deck_id": d2["id"], "front": "H2O", "back": "water"})
    c.check("card in other deck -> 200", st == 200, f"{st} {c3}")

    st, err = app.post("add_card", {"deck_id": "ghost-deck", "front": "a", "back": "b"})
    c.check("card on missing deck -> 400", st == 400, f"{st} {err}")
    st, err = app.post("add_card", {"deck_id": d1["id"], "front": "", "back": "b"})
    c.check("empty front -> 400", st == 400, f"{st} {err}")

    st, cards = app.get("cards_for_deck", {"deck_id": d1["id"]})
    c.check("cards scoped to deck", st == 200 and isinstance(cards, list) and len(cards) == 2, cards)
    c.check("cards oldest first", isinstance(cards, list) and len(cards) == 2 and cards[0].get("front") == "hola", cards)

    st, r = app.post("review_card", {"id": c1["id"]})
    c.check("review increments to 1", st == 200 and isinstance(r, dict) and r.get("reviews") == 1, f"{st} {r}")
    st, r = app.post("review_card", {"id": c1["id"]})
    c.check("second review -> exactly 2", st == 200 and isinstance(r, dict) and r.get("reviews") == 2, f"{st} {r}")
    st, err = app.post("review_card", {"id": "ghost-card"})
    c.check("review unknown card -> 400", st == 400, f"{st} {err}")

    st, d = app.post("delete_card", {"id": c2["id"]})
    c.check("delete_card -> 200", st == 200, f"{st} {d}")
    st, cards = app.get("cards_for_deck", {"deck_id": d1["id"]})
    c.check("deleted card gone", st == 200 and isinstance(cards, list) and len(cards) == 1, cards)

    st, d = app.post("delete_deck", {"id": d1["id"]})
    c.check("delete_deck -> 200", st == 200, f"{st} {d}")
    st, cards = app.get("cards_for_deck", {"deck_id": d1["id"]})
    c.check("deck's cards cascaded away", st == 200 and cards == [], cards)
    st, cards = app.get("cards_for_deck", {"deck_id": d2["id"]})
    c.check("other deck's cards intact", st == 200 and isinstance(cards, list) and len(cards) == 1, cards)
