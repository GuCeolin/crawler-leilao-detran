from __future__ import annotations

import logging
import urllib.parse
import urllib.robotparser
import urllib.request


logger = logging.getLogger(__name__)


class RobotsPolicy:
    def __init__(self, base_url: str, user_agent: str = "detran-leilao-crawler") -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self._rp = urllib.robotparser.RobotFileParser()
        self._loaded = False

    def load(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.base_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            req = urllib.request.Request(
                robots_url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/plain,*/*;q=0.8",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                content = resp.read().decode("utf-8", errors="replace")
            self._rp.parse(content.splitlines())
            self._loaded = True
            logger.info("robots.txt loaded from %s", robots_url)
        except Exception as exc:  # noqa: BLE001
            # Fail-open but log it; user can enforce stricter policy if desired.
            logger.warning("robots.txt unavailable (%s). Proceeding fail-open.", exc)
            self._loaded = False

    def can_fetch(self, url: str) -> bool:
        if not self._loaded:
            return True
        return self._rp.can_fetch(self.user_agent, url)
