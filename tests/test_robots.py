from detran_leilao_crawler.robots import RobotsPolicy


def test_robots_allows_by_default_when_unavailable(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("net down")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    rp = RobotsPolicy("https://leilao.detran.mg.gov.br/")
    rp.load()
    assert rp.can_fetch("https://leilao.detran.mg.gov.br/") is True
