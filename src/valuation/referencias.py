"""Onde cada indicador cai na base brasileira, medido e nao arbitrado.

Por que isto existe
-------------------

O app usa cortes de leitura -- conversao de caixa "boa" acima de 90%, "fraca"
abaixo de 60%; margem confortavel; alavancagem alta. Todos vinham de convencao
de mercado, e convencao de mercado costuma ser convencao de **outro** mercado.
Perguntado sobre isso, o dono do projeto foi direto: "absoluto ou vs peers?"

A resposta honesta e **os dois**, e por motivos diferentes.

O corte absoluto tem significado economico: converter menos de 60% do EBITDA em
caixa quer dizer que quatro de cada dez reais de lucro ficaram no giro ou no
imobilizado, e isso e verdade em qualquer pais. O percentil diz outra coisa,
igualmente necessaria: se a mediana brasileira converte 85%, uma companhia a 77%
esta abaixo do esperado **e** perto da metade da base -- o que muda a urgencia
da conversa sem mudar o diagnostico.

Ler so o absoluto faz o analista brasileiro estranhar o normal do seu mercado.
Ler so o percentil faz o pior quartil parecer aceitavel porque alguem tinha que
estar la.

Como foi medido
---------------

Mediana historica de cada indicador em cada companhia com DFP consolidada, cinco
exercicios, bancos e seguradoras de fora. A unidade e a companhia, nao o ano:
uma empresa nao pesa cinco vezes mais por ter publicado cinco anos.

O que isto **nao** e: uma base viva. Sao numeros de um momento, e a data esta
declarada em ``MEDIDO_EM``. Refazer e rodar ``python -m valuation.pares`` e
``gerar_referencias`` sobre o universo resultante.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MEDIDO_EM = "exercícios 2020 a 2024, DFP consolidada"
COMPANHIAS_MEDIDAS = 447

QUANTIS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

# indicador -> (n, valores nos quantis acima)
BASE: dict[str, tuple[int, tuple[float, ...]]] = {
    "Conversao de caixa (FCO / EBITDA)": (420, (-1.227, -0.503, 0.327, 0.847, 1.269, 2.124, 2.866)),
    "Margem EBITDA": (445, (-0.414, -0.073, 0.058, 0.143, 0.243, 0.452, 0.601)),
    "Margem liquida": (445, (-0.671, -0.196, -0.001, 0.061, 0.138, 0.288, 0.435)),
    "Crescimento da receita": (435, (-0.101, -0.032, 0.056, 0.151, 0.268, 0.458, 0.718)),
    "Capex / Receita": (414, (0.003, 0.007, 0.020, 0.049, 0.124, 0.276, 0.487)),
    "ROIC": (419, (-0.200, -0.010, 0.033, 0.101, 0.173, 0.272, 0.408)),
    "Investimento em giro (DFC) / Receita": (440, (-0.312, -0.109, -0.005, 0.040, 0.097, 0.215, 0.411)),
    "Divida liquida / EBITDA": (420, (-1.898, -0.696, 0.616, 2.829, 5.353, 11.085, 15.593)),
    "Liquidez corrente": (447, (0.338, 0.562, 1.065, 1.519, 2.140, 2.983, 4.341)),
    "Payout (dividendos / lucro)": (342, (0.000, 0.000, 0.129, 0.326, 0.567, 0.884, 1.107)),
}

# Descolamento entre o juro de competencia (DRE) e o juro pago (DFC), medido nas
# mesmas 368 companhias que publicam os dois. **A mediana e +8,2 p.p.**, e nao
# perto de zero: a linha 3.06.02 da CVM junta variacao cambial e monetaria de
# todo o passivo, nao so juro. Um corte em 2 p.p. -- que era o do app -- acusa
# 82,3% da base, e sinal que dispara em quatro de cada cinco companhias nao e
# sinal. Os cortes agora sao os quartis observados.
DESCOLAMENTO_DO_JURO = (368, (-0.006, 0.036, 0.082, 0.169, 0.345, 0.633))
DESCOLAMENTO_QUANTIS = (0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

def tabela() -> pd.DataFrame:
    """A base medida, para mostrar na tela ou conferir a mao."""
    linhas = {}
    for indicador, (n, valores) in BASE.items():
        registro = {f"P{int(q * 100)}": v for q, v in zip(QUANTIS, valores)}
        registro["n"] = n
        linhas[indicador] = registro
    return pd.DataFrame(linhas).T


def posicao(indicador: str, valor: float) -> float:
    """Percentil aproximado de ``valor`` na base, entre 0 e 1.

    Interpola entre os quantis guardados. Fora das pontas devolve 0,05 ou 0,95
    em vez de extrapolar: a cauda de uma distribuicao com margem de 300% nao se
    aproxima por reta, e fingir precisao ali seria pior do que dizer "no
    extremo".
    """
    if indicador not in BASE or not np.isfinite(valor):
        return float("nan")
    _, valores = BASE[indicador]
    return float(np.interp(valor, valores, QUANTIS))


def descrever(indicador: str, valor: float) -> str:
    """Uma frase com o percentil, para colar no texto de um sinal."""
    p = posicao(indicador, valor)
    if not np.isfinite(p):
        return ""
    n = BASE[indicador][0]
    if p <= 0.05:
        return f"entre os 5% menores de {n} companhias brasileiras"
    if p >= 0.95:
        return f"entre os 5% maiores de {n} companhias brasileiras"
    return f"no percentil {p * 100:.0f} de {n} companhias brasileiras"


def gerar_referencias(perfis: pd.DataFrame, indicadores: list[str] | None = None) -> str:
    """Devolve o bloco ``BASE`` pronto para colar, a partir de um universo medido.

    Existe para que refazer a medicao seja um comando e nao um trabalho manual
    -- numero de referencia que da trabalho para atualizar nao se atualiza.
    """
    alvos = indicadores or [c for c in BASE if c in perfis.columns]
    linhas = ["BASE: dict[str, tuple[int, tuple[float, ...]]] = {"]
    for indicador in alvos:
        serie = perfis[indicador].replace([np.inf, -np.inf], np.nan).dropna()
        if serie.empty:
            continue
        valores = ", ".join(f"{serie.quantile(q):.3f}" for q in QUANTIS)
        linhas.append(f'    "{indicador}": ({len(serie)}, ({valores})),')
    linhas.append("}")
    return "\n".join(linhas)
