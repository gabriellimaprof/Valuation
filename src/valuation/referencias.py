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

**A tabela ja foi refeita duas vezes, e por bons motivos.** A primeira medicao saiu
com a D&A quebrada, e como o EBITDA vinha igual ao EBIT, tudo que o divide saiu
torto: a conversao de caixa mediana aparecia como 85% quando e **64%**, e a
margem EBITDA mediana como 14,3% quando e **17,2%**. Numero de referencia
medido sobre leitura errada e pior do que nenhum, porque parece autoridade.

Na segunda, o juro pago foi padronizado para o operacional (ver
``cvm._padronizar_juros_no_fco``). A conversao mediana caiu de 64% para **54%**:
121 companhias classificavam juro no financiamento e o FCO delas era, ate
entao, um numero que nao se comparava com o das outras.

Na terceira, depois da auditoria de leitura. A D&A passou a ser somada da DFC
em vez de escolhida por rotulo, e a margem EBITDA mediana subiu de 17,2% para
**19,9%**; os pagamentos sairam do capital de giro, e o investimento em giro
mediano caiu de 4,0% para **2,8%** da receita. Cada uma dessas medicoes anteriores
descrevia uma leitura que hoje se sabe incompleta.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MEDIDO_EM = (
    "exercícios 2021 a 2025, DFP consolidada, depois da auditoria de leitura: "
    "D&A da DFC (e não da linha da DRE, que só traz o pedaço do SG&A), juro pago "
    "padronizado no operacional, pagamentos retirados do capital de giro, sinal "
    "do IR vindo da identidade e lucro dos controladores derivado quando a "
    "companhia zera 3.11.01"
)
COMPANHIAS_MEDIDAS = 421

# O ultimo exercicio que entrou na medicao, em forma de numero e nao de prosa.
# ``BASE`` e um instantaneo **colado**: ela nao se atualiza quando sai DFP nova,
# e nada na tela dizia isso. O app passava a citar percentis de uma safra antiga
# com a mesma aparencia de atual, que e o pior tipo de numero desatualizado --
# o que nao se anuncia. Ao regenerar ``BASE``, atualize tambem esta linha.
ANO_MAIS_RECENTE_MEDIDO = 2025


def safra(cache=None):
    """Se os percentis citados ainda descrevem a base publicada.

    Devolve ``None`` quando nao ha DFP no cache para comparar -- sem base local
    nao ha como afirmar que a medicao envelheceu, e afirmar assim mesmo seria
    inventar.
    """
    from .pares import _anos_de_dfp_no_cache

    disponiveis = _anos_de_dfp_no_cache(cache)
    if not disponiveis:
        return None
    mais_novo = disponiveis[-1]
    return SafraDaMedicao(
        ano_medido=ANO_MAIS_RECENTE_MEDIDO,
        ano_mais_novo=mais_novo,
        companhias=COMPANHIAS_MEDIDAS,
    )


@dataclass(frozen=True)
class SafraDaMedicao:
    """A idade dos percentis que a tela cita."""

    ano_medido: int
    ano_mais_novo: int
    companhias: int

    @property
    def desatualizada(self) -> bool:
        return self.ano_mais_novo > self.ano_medido

    @property
    def exercicios_atras(self) -> int:
        return max(0, self.ano_mais_novo - self.ano_medido)

    def resumo(self) -> str:
        if not self.desatualizada:
            return (
                f"Percentis medidos em {self.companhias} companhias, exercício "
                f"{self.ano_medido} — a safra mais nova publicada."
            )
        plural = "exercícios" if self.exercicios_atras > 1 else "exercício"
        return (
            f"**Os percentis estão {self.exercicios_atras} {plural} atrás.** Eles "
            f"foram medidos até {self.ano_medido} e a CVM já publicou "
            f"{self.ano_mais_novo}. A comparação continua útil como ordem de "
            "grandeza, mas o número exato descreve a base antiga."
        )

QUANTIS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

# indicador -> (n, valores nos quantis acima)
BASE: dict[str, tuple[int, tuple[float, ...]]] = {
    "Conversao de caixa (FCO / EBITDA)": (409, (-0.824, -0.394, 0.166, 0.530, 0.785, 1.021, 1.295)),
    # A conversao **operacional** -- caixa gerado pelas operacoes sobre EBITDA,
    # antes de giro, imposto e juro. Medida na mesma safra e com a mesma
    # metodologia (mediana por companhia, quantis entre companhias).
    #
    # Repare na mediana **acima de 100%**: nao e anomalia. O caixa gerado devolve
    # ao lucro despesas que nao foram caixa e que o EBITDA nao captura --
    # provisao, impairment. E a distancia para a conversao final, na mediana, e
    # de **48,9 pontos**: e o que giro, imposto e juro consomem.
    "Conversao operacional (CGO / EBITDA)": (398, (0.191, 0.537, 0.859, 1.029, 1.159, 1.421, 1.738)),
    "Margem EBITDA": (418, (-0.214, 0.035, 0.103, 0.208, 0.399, 0.598, 0.733)),
    "Margem liquida": (418, (-0.410, -0.161, -0.004, 0.062, 0.140, 0.283, 0.417)),
    "Crescimento da receita": (412, (-0.088, -0.036, 0.018, 0.093, 0.199, 0.371, 0.515)),
    "Capex / Receita": (389, (0.003, 0.008, 0.021, 0.047, 0.112, 0.262, 0.381)),
    "ROIC": (397, (-0.088, 0.001, 0.044, 0.101, 0.165, 0.255, 0.401)),
    "Investimento em giro (DFC) / Receita": (396, (-0.232, -0.077, -0.009, 0.026, 0.078, 0.152, 0.258)),
    "Divida liquida / EBITDA": (409, (-1.478, -0.566, 0.572, 2.051, 3.554, 5.963, 10.455)),
    "Liquidez corrente": (421, (0.324, 0.638, 1.087, 1.546, 2.167, 2.943, 4.022)),
    "Payout (dividendos / lucro)": (334, (0.000, 0.000, 0.151, 0.364, 0.603, 0.858, 1.082)),
}# Descolamento entre o juro de competencia (DRE) e o juro pago (DFC), medido nas
# mesmas 368 companhias que publicam os dois. **A mediana e +8,2 p.p.**, e nao
# perto de zero: a linha 3.06.02 da CVM junta variacao cambial e monetaria de
# todo o passivo, nao so juro. Um corte em 2 p.p. -- que era o do app -- acusa
# 82,3% da base, e sinal que dispara em quatro de cada cinco companhias nao e
# sinal. Os cortes agora sao os quartis observados.
# Medido na safra 2021-2025, nas 260 companhias que publicam os dois juros **e**
# tem denominador que significa custo de credito -- 90 ficam de fora por Kd acima
# de ``KD_MAXIMO_PLAUSIVEL`` e 85 por nao abrirem juro pago.
#
# A distribuicao **encolheu** em relacao a 2020-2024: a mediana caiu de 8,2 para
# 5,9 p.p. e o P90 de 34,5 para 13,8. Duas causas plausiveis, e nenhuma medida
# em separado: 2020 saiu da janela -- foi ano de desvalorizacao forte do real, e
# a linha 3.06.02 carrega variacao cambial de todo o passivo -- e as correcoes de
# leitura do juro pago entraram.
#
# O efeito nos cortes antigos e que eles **pararam de disparar**: 16,9 p.p.
# acusava 4,2% da amostra nova e 34,5 p.p. acusava **zero**. Sinal que nunca
# dispara e tao inutil quanto o que dispara sempre, que foi o problema oposto do
# corte original de 2 p.p. (82,3%).
DESCOLAMENTO_DO_JURO = (260, (-0.001, 0.026, 0.059, 0.100, 0.138, 0.160))
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
