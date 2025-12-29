from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .models import Lot


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


@dataclass(frozen=True)
class FiltersConfig:
    ignore_requires_login: bool = True
    ignore_sucata: bool = True

    tipo_veiculo: Optional[str] = None  # carro | moto
    marcas_permitidas: Optional[list[str]] = None

    ano_min: Optional[int] = None
    ano_max: Optional[int] = None
    valor_max: Optional[float] = None

    descricao_keywords_all: Optional[list[str]] = None
    descricao_keywords_any: Optional[list[str]] = None


class FilterEngine:
    def __init__(self, cfg: FiltersConfig) -> None:
        self.cfg = cfg

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "FilterEngine":
        cfg = FiltersConfig(
            ignore_requires_login=bool(d.get("ignore_requires_login", True)),
            ignore_sucata=bool(d.get("ignore_sucata", True)),
            tipo_veiculo=d.get("tipo_veiculo"),
            marcas_permitidas=d.get("marcas_permitidas"),
            ano_min=d.get("ano_min"),
            ano_max=d.get("ano_max"),
            valor_max=d.get("valor_max"),
            descricao_keywords_all=d.get("descricao_keywords_all"),
            descricao_keywords_any=d.get("descricao_keywords_any"),
        )
        return FilterEngine(cfg)

    def accept(self, lot: Lot) -> bool:
        if self.cfg.ignore_requires_login and lot.requires_login:
            return False

        desc = _norm(lot.description_short) + " " + _norm(lot.raw_text)

        if self.cfg.ignore_sucata and "sucata" in desc:
            return False

        if self.cfg.tipo_veiculo:
            tv = _norm(self.cfg.tipo_veiculo)
            if tv == "moto" and "moto" not in desc:
                return False
            if tv == "carro" and any(k in desc for k in ["moto", "motocic"]):
                return False

        if self.cfg.marcas_permitidas:
            allowed = {_norm(x) for x in self.cfg.marcas_permitidas if _norm(x)}
            bm = _norm(lot.brand_model) + " " + _norm(lot.description_short)
            if allowed and not any(a in bm for a in allowed):
                return False

        if self.cfg.ano_min is not None and lot.year is not None and lot.year < self.cfg.ano_min:
            return False
        if self.cfg.ano_max is not None and lot.year is not None and lot.year > self.cfg.ano_max:
            return False

        if self.cfg.valor_max is not None and lot.start_bid is not None and lot.start_bid > self.cfg.valor_max:
            return False

        if self.cfg.descricao_keywords_all:
            kws = [_norm(k) for k in self.cfg.descricao_keywords_all if _norm(k)]
            if any(k not in desc for k in kws):
                return False

        if self.cfg.descricao_keywords_any:
            kws = [_norm(k) for k in self.cfg.descricao_keywords_any if _norm(k)]
            if kws and not any(k in desc for k in kws):
                return False

        return True


def filter_lots(lots: Iterable[Lot], engine: FilterEngine) -> list[Lot]:
    return [l for l in lots if engine.accept(l)]
