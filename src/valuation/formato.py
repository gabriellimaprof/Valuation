"""Numero no padrao brasileiro: milhar com ponto, decimal com virgula.

**Seis modulos do motor tinham a propria copia disto**, e elas nao eram iguais.
Divergiam no marcador de ausencia -- `n/d`, `n/a`, `—` -- e uma delas divergia no
que importa: `cli._pct` usava `f"{valor:.2%}"`, que produz **"12.34%" com ponto
decimal**, formatacao inglesa numa CLI em portugues.

Nenhum teste pegava, porque cada modulo testava a propria copia. E a divergencia
so aparecia para quem usasse os dois -- o relatorio dizendo "12,34%" e a CLI
dizendo "12.34%" do mesmo numero.

A regra que este arquivo carrega
--------------------------------

O marcador de ausencia **e parametro e nao constante**, porque os tres em uso
querem dizer coisas diferentes no seu contexto: num documento impresso o
travessao le melhor que "n/d", e numa tabela de terminal "n/d" e mais explicito
que um traco que pode passar por hifen. O que nao pode variar e o **numero**.
"""

from __future__ import annotations

import numpy as np

#: O que aparece no lugar de um numero que nao existe. Ausencia declarada e
#: melhor que zero, que se le como medida.
AUSENTE = "n/d"


def _vazio(valor) -> bool:
    if valor is None:
        return True
    try:
        return not np.isfinite(float(valor))
    except (TypeError, ValueError):
        return True


def pct(valor, casas: int = 1, ausente: str = AUSENTE) -> str:
    """Percentual a partir de um decimal: ``0.125`` vira ``"12,5%"``."""
    if _vazio(valor):
        return ausente
    return f"{float(valor) * 100:.{casas}f}%".replace(".", ",")


def num(valor, casas: int = 1, ausente: str = AUSENTE) -> str:
    """Numero com milhar em ponto e decimal em virgula."""
    if _vazio(valor):
        return ausente
    texto = f"{float(valor):,.{casas}f}"
    # O `@` e passagem: trocar "," por "." e depois "." por "," direto
    # transformaria os dois no mesmo caractere.
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


def multiplo(valor, casas: int = 2, ausente: str = AUSENTE) -> str:
    """Multiplo com o ``x`` colado: ``8.5`` vira ``"8,50x"``."""
    if _vazio(valor):
        return ausente
    return num(valor, casas) + "x"
