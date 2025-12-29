from detran_leilao_crawler.checkpoint import CrawlCheckpoint


def test_checkpoint_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    cp = CrawlCheckpoint(path=p)
    cp.mark_page_done("auction-1", 1)
    cp.save()

    cp2 = CrawlCheckpoint(path=p)
    cp2.load()
    assert cp2.is_page_done("auction-1", 1) is True
    assert cp2.is_page_done("auction-1", 2) is False
