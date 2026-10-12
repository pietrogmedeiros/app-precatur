"""Séries de índices versionadas + aplicação ao valor originário.

Exporta:

- `INDICES_SUPORTADOS`: set de índices canônicos cobertos pela v1.
- `load_serie(nome)`: carrega CSV em memória (cache).
- `fator_periodo(serie, de, ate)`: fator multiplicativo acumulado entre
  duas datas (mês de início exclusivo, mês final inclusivo — convenção
  Manual JF).
- `aplicar_regime(valor_originario, data_base, regime, ate)`: aplica um
  regime composto (`list[PeriodoIndice]`) ao valor.
- `IndiceNaoSuportado`: exceção quando o regime cita TR/IGP-M/etc (ver
  README dos índices).
"""

from precaturia.pipeline.indices.aplicar import (
    IndiceNaoSuportado,
    aplicar_regime,
    fator_ipca_e,
    fator_periodo,
)
from precaturia.pipeline.indices.historico import (
    HistoricoForaDeCobertura,
    coef,
    cobertura_historico,
    fator_historico,
    indice_label,
)
from precaturia.pipeline.indices.series import INDICES_SUPORTADOS, cobertura, load_serie


__all__ = [
    "INDICES_SUPORTADOS",
    "IndiceNaoSuportado",
    "HistoricoForaDeCobertura",
    "aplicar_regime",
    "coef",
    "cobertura",
    "cobertura_historico",
    "fator_historico",
    "fator_ipca_e",
    "fator_periodo",
    "indice_label",
    "load_serie",
]
