from detran_leilao_crawler.filters import FilterEngine
from detran_leilao_crawler.models import Lot


def test_filter_requires_login_default_true():
    engine = FilterEngine.from_dict({"ignore_requires_login": True})
    lot = Lot(auction_id="a1", lot_id="l1", description_short="Teste", requires_login=True)
    assert engine.accept(lot) is False


def test_filter_keywords_all():
    engine = FilterEngine.from_dict({"descricao_keywords_all": ["honda", "civic"]})
    lot_ok = Lot(auction_id="a1", lot_id="l1", description_short="Honda Civic 2018", requires_login=False)
    lot_no = Lot(auction_id="a1", lot_id="l2", description_short="Honda Fit 2018", requires_login=False)
    assert engine.accept(lot_ok) is True
    assert engine.accept(lot_no) is False
