from detran_leilao_crawler.parsers import parse_lot_cards_from_html


def test_parse_lot_cards_extract_brand_model_year_start_bid_and_login():
    html = """
    <div class='card listaLotes' id='282156'>
      <span onclick="$(location).prop('href', '/lotes/detalhes/282156');">
        <img src='/../Imagens/visualizar/leiloes/leilao_2842/img_282156_1.jpg' />
      </span>
      <div class='card-body'>
        <div class='row'><div class='col-12'>
          <b><span>Lote 1</span> - <span>CONSERVADO</span></b>
        </div></div>
        <div class='row'><div class='col-12 text-center'><b>HONDA/CBX 250 TWISTER 2006</b></div></div>
        <p class='update_info_lote' id='valor_atual_lote_282156'>R$ 400,00</p>
        <a href='/ssc/login/login' class='btn'>Login Obrigatório</a>
      </div>
    </div>
    """

    lots = parse_lot_cards_from_html(html, auction_id="a1", page_url="https://leilao.detran.mg.gov.br/lotes/lista-lotes/2842/2026")
    assert len(lots) == 1

    lot = lots[0]
    assert lot.lot_id == "282156"
    assert lot.requires_login is True
    assert lot.situation.lower() == "conservado"
    assert lot.year == 2006
    assert lot.brand_model == "HONDA/CBX 250 TWISTER"
    assert abs((lot.start_bid or 0) - 400.0) < 0.001
    assert lot.lot_url.endswith("/lotes/detalhes/282156")
    assert len(lot.image_urls) == 1
    assert "img_282156_1.jpg" in lot.image_urls[0]
