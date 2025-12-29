from bs4 import BeautifulSoup

html = open("codigofonte.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "lxml")

print("--- Current Selector: div.card.listaLotes ---")
current = soup.select("div.card.listaLotes")
print(f"Count: {len(current)}")
for c in current:
    print(f"  ID: {c.get('id')}")

print("\n--- New Selector: div.card[id] ---")
new_sel = soup.select("div.card[id]")
print(f"Count: {len(new_sel)}")
for c in new_sel:
    print(f"  ID: {c.get('id')} | Classes: {c.get('class')}")
    # Verify content
    text = c.get_text(" ", strip=True)
    if "Lote" in text:
        print("    -> Contains 'Lote'")
    else:
        print("    -> DOES NOT contain 'Lote' (Risk!)")
