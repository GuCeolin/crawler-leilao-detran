from detran_leilao_crawler.parsers import parse_lot_cards_from_html

def test_lot_collision_scenarios():
    scenarios = [
        (
            "Suffix no space",
            """
            <div class='card listaLotes'>
              <div class='card-body'><b><span>Lote 123</span></b><p>R$ 10</p></div>
            </div>
            <div class='card listaLotes'>
              <div class='card-body'><b><span>Lote 123A</span></b><p>R$ 20</p></div>
            </div>
            """,
            2
        ),
        (
            "Suffix with dash",
            """
            <div class='card listaLotes'>
              <div class='card-body'><b><span>Lote 123</span></b><p>R$ 10</p></div>
            </div>
            <div class='card listaLotes'>
              <div class='card-body'><b><span>Lote 123-A</span></b><p>R$ 20</p></div>
            </div>
            """,
            2
        )
    ]

    for name, html, expected_count in scenarios:
        lots = parse_lot_cards_from_html(html, auction_id="test", page_url="http://example.com")
        assert len(lots) == expected_count, f"Scenario '{name}' failed: Expected {expected_count}, got {len(lots)}"
        ids = [l.lot_id for l in lots]
        assert "123" in ids
        # Check that the suffix was captured
        assert any("A" in i or "a" in i for i in ids), f"Scenario '{name}': Suffix lost in IDs: {ids}"
