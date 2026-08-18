"""Qualidade dos lucros: o lucro vira caixa, ou nao vira e por que.

Os sinais ja existiam espalhados como indicadores -- conversao de caixa, juro
pago contra despesa de competencia, giro medido pelo caixa. Indicador solto
numa tabela nao e leitura: exige que o analista lembre a faixa de cada um e
junte tudo de cabeca, que e exatamente a parte bracal que este projeto existe
para tirar da mao.

Aqui eles viram um veredito com o porque. Nao substitui julgamento -- a
conclusao e sempre "isto merece explicacao", nunca "compre" ou "venda" --, mas
poupa a montagem.

**O sinal central e o accrual.** Lucro que nao aparece no caixa operacional foi
reconhecido antes de ser recebido, ou o caixa foi consumido pelo giro. Nenhum
dos dois e defeito por si: empresa que cresce rapido prende caixa em recebivel
e estoque. Vira defeito quando persiste sem crescimento que o explique, e e
essa distincao que a leitura precisa fazer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import referencias
from .historico import KD_MAXIMO_PLAUSIVEL, AnaliseHistorica

# Faixas de referencia, deliberadamente largas: servem para separar o normal do
# que precisa de explicacao, nao para reprovar empresa.
# Medidos em 429 companhias, ja depois da auditoria de leitura: P25 = 15,2%,
# mediana = 52,1%, P75 = 77,6%.
#
# Os cortes sao os quartis observados, e nao mais os 90%/60% de convencao. A
# razao e que os absolutos perderam sentido aqui: o FCO brasileiro e liquido de
# imposto (34%) e de juro, e o EBITDA e antes dos dois -- 90% era referencia
# importada de um mercado de imposto e juro baixos. O que resta de absoluto e a
# leitura de cada empresa contra a base, que o sinal reporta em percentil.
#
# Historico das calibracoes, porque cada uma corrigiu um erro de leitura: 0,60
# acusava 47,3% da base antes da correcao da D&A; depois dela, ainda 30%; a
# padronizacao do juro derrubou a mediana de 64% para 54%; e a D&A somada da DFC
# a levou a 52%.
CONVERSAO_BOA = 0.78
CONVERSAO_FRACA = 0.15
# Crescimento acima disto justifica caixa preso no giro sem que seja sinal ruim.
CRESCIMENTO_QUE_EXPLICA_GIRO = 0.15
# Diferenca entre juro de competencia e juro pago que sugere capitalizacao.
# Descolamento entre o juro da DRE e o juro pago que merece atencao.
#
# Era 0,02, e **acusava 82,3% da base** -- a linha 3.06.02 da CVM junta variacao
# cambial e monetaria de todo o passivo, entao a mediana brasileira ja descola
# 8,2 p.p. sem que nada de errado tenha acontecido. Sinal que dispara em quatro
# de cada cinco companhias nao dirige atencao: gasta ela.
#
# Os cortes agora sao o P75 (16,9 p.p.) e o P90 (34,5 p.p.) medidos em 368
# companhias -- ver ``referencias.DESCOLAMENTO_DO_JURO``.
JURO_DESCOLADO = 0.169
JURO_MUITO_DESCOLADO = 0.345
# Acima disto, o resultado depende demais de coligada que nao gera caixa aqui.
EQUIVALENCIA_RELEVANTE = 0.20

BOM, ATENCAO, RUIM, SEM_DADOS = "bom", "atencao", "ruim", "sem_dados"

_ORDEM = {RUIM: 0, ATENCAO: 1, BOM: 2, SEM_DADOS: 3}


@dataclass(frozen=True)
class Sinal:
    """Um teste de qualidade, com o que foi medido e o que isso quer dizer."""

    codigo: str
    veredito: str
    titulo: str
    detalhe: str
    valor: float = float("nan")

    @property
    def icone(self) -> str:
        return {BOM: "🟢", ATENCAO: "🟡", RUIM: "🔴", SEM_DADOS: "⚪"}[self.veredito]


@dataclass(frozen=True)
class QualidadeDosLucros:
    """Leitura da distancia entre o lucro contabil e o caixa."""

    sinais: list[Sinal] = field(default_factory=list)
    conversao_mediana: float = float("nan")

    @property
    def por_severidade(self) -> list[Sinal]:
        return sorted(self.sinais, key=lambda s: _ORDEM[s.veredito])

    @property
    def veredito(self) -> str:
        """O pior sinal manda: uma boa conversao nao cancela juro capitalizado."""
        medidos = [s.veredito for s in self.sinais if s.veredito != SEM_DADOS]
        if not medidos:
            return SEM_DADOS
        for nivel in (RUIM, ATENCAO):
            if nivel in medidos:
                return nivel
        return BOM

    @property
    def resumo(self) -> str:
        return {
            BOM: "O lucro se converte em caixa e os sinais periféricos estão limpos.",
            ATENCAO: "O lucro se converte, mas há pontos que pedem explicação.",
            RUIM: "A distância entre lucro e caixa é grande o bastante para "
            "mudar a leitura do resultado.",
            SEM_DADOS: "Faltam dados de fluxo de caixa para avaliar a qualidade "
            "dos lucros.",
        }[self.veredito]


def _mediana(analise: AnaliseHistorica, indicador: str) -> float:
    if indicador not in analise.indicadores.index:
        return float("nan")
    return float(analise.mediana(indicador))


def _conversao(analise: AnaliseHistorica) -> Sinal:
    conversao = _mediana(analise, "Conversao de caixa (FCO / EBITDA)")
    crescimento = _mediana(analise, "Crescimento da receita")

    if not np.isfinite(conversao):
        return Sinal(
            "conversao", SEM_DADOS,
            "Sem DFC para medir a conversão",
            "A origem não trouxe o caixa operacional, então a distância entre "
            "lucro e caixa não pode ser medida.",
        )

    texto = (
        f"A mediana do período converte {conversao:.0%} do EBITDA em caixa. "
        "O FCO é líquido de imposto e de juros pagos, e o EBITDA é antes dos "
        "dois — parte da distância é estrutural e não fala de qualidade do lucro."
    )

    # A padronizacao precisa aparecer no texto: quem compara este numero com o
    # da demonstracao publicada da companhia vai achar diferenca, e tem que
    # saber de onde ela vem.
    reclassificado = analise.demonstracoes.serie("juros_pagos_no_financiamento")
    anos_movidos = [str(a) for a in reclassificado.dropna().index]
    if anos_movidos:
        todos = len(anos_movidos) == len(analise.anos)
        quando = "no período" if todos else f"em {', '.join(anos_movidos)}"
        texto += (
            f" Esta companhia classificou juros pagos no financiamento {quando}, e o "
            "app os trouxe para o operacional."
        )
        if not todos:
            # Companhia que troca a propria classificacao no meio da serie fica
            # incomparavel consigo mesma: a WEG fez isso entre 2022 e 2023, e o
            # FCO dos dois primeiros anos apareceria inflado ao lado dos outros.
            texto += (
                " Ela mudou de classificação no meio do período — sem a "
                "padronização, a série dela não seria comparável nem consigo mesma."
            )
    onde = referencias.descrever("Conversao de caixa (FCO / EBITDA)", conversao)
    if onde:
        # O corte absoluto diz o que a conta significa; o percentil diz se o
        # numero e incomum aqui. Faltando um dos dois, o leitor ou estranha o
        # normal do mercado ou aceita o pior quartil por ele existir.
        texto += f" Isso a coloca {onde}."
    if conversao >= CONVERSAO_BOA:
        return Sinal("conversao", BOM, "O EBITDA vira caixa", texto, conversao)

    if conversao >= CONVERSAO_FRACA:
        return Sinal(
            "conversao", ATENCAO, "Parte do EBITDA não chega ao caixa",
            texto + " A diferença costuma estar no capital de giro; confira se "
            "ela acompanha crescimento ou se é perene.",
            conversao,
        )

    if np.isfinite(crescimento) and crescimento >= CRESCIMENTO_QUE_EXPLICA_GIRO:
        return Sinal(
            "conversao", ATENCAO,
            "Conversão baixa, mas a empresa está crescendo rápido",
            texto + f" Com receita crescendo {crescimento:.0%} ao ano, prender "
            "caixa em recebível e estoque é esperado — o sinal só preocupa se "
            "persistir quando o crescimento parar.",
            conversao,
        )

    return Sinal(
        "conversao", RUIM, "O EBITDA não está virando caixa",
        texto + " Sem crescimento que justifique, isso aponta resultado "
        "reconhecido antes de ser recebido ou giro consumindo a operação.",
        conversao,
    )


def _juros(analise: AnaliseHistorica) -> Sinal:
    competencia = _mediana(analise, "Custo da divida efetivo")
    caixa = _mediana(analise, "Custo da divida pelo caixa")
    if not (np.isfinite(competencia) and np.isfinite(caixa)):
        return Sinal(
            "juros", SEM_DADOS, "Sem juro pago para comparar",
            "A DFC não trouxe o juro efetivamente pago.",
        )

    # Acima de KD_MAXIMO_PLAUSIVEL a razao deixou de medir custo de divida: e o
    # caso da WEG, que tem caixa liquido e cujo denominador minusculo faz a
    # despesa financeira -- cambio incluso -- dar 45% "da divida". Comparar isso
    # com o juro pago produz um descolamento de 40 p.p. que nao fala de credito
    # nenhum, e acusar a companhia por um artefato de denominador seria pior do
    # que nao medir. Mesmo criterio que ``historico.py`` usa para descartar o Kd.
    if competencia > KD_MAXIMO_PLAUSIVEL:
        return Sinal(
            "juros", SEM_DADOS, "Despesa financeira grande demais para ser custo de dívida",
            f"A despesa financeira equivale a {competencia:.1%} da dívida média, o "
            "que não é custo de dívida: a companhia tem pouca dívida e a linha "
            "carrega variação cambial de todo o passivo. Sem denominador que "
            "signifique alguma coisa, o descolamento não é medível.",
        )

    diferenca = competencia - caixa
    medida = (
        f"A despesa financeira equivale a {competencia:.1%} da dívida média e o "
        f"juro pago a {caixa:.1%} — um descolamento de {diferenca:.1%}."
    )
    # A mediana brasileira descola 8,2 p.p., entao a frase precisa dizer isso:
    # sem a referencia, o leitor toma o normal do mercado por irregularidade.
    normal = (
        " A mediana de 368 companhias brasileiras descola 8,2 p.p., porque a linha "
        "de despesa financeira da CVM junta variação cambial e monetária de todo o "
        "passivo — descolar não é, por si, sinal de nada."
    )

    if diferenca <= JURO_DESCOLADO:
        return Sinal(
            "juros", BOM, "O descolamento do juro está dentro do normal",
            medida + normal, diferenca,
        )

    severidade = RUIM if diferenca > JURO_MUITO_DESCOLADO else ATENCAO
    onde = "10% maiores" if diferenca > JURO_MUITO_DESCOLADO else "25% maiores"
    return Sinal(
        "juros", severidade, "Descolamento incomum entre o juro devido e o pago",
        medida
        + f" Isso põe a companhia entre os {onde} da base."
        + " Pode ser exposição cambial da dívida, juro capitalizado em obra ou "
        "acúmulo para pagar depois. As três adiam caixa, e as três mudam o Kd que "
        "deve entrar no WACC — vale abrir a nota de despesa financeira antes de "
        "projetar.",
        diferenca,
    )


def _giro(analise: AnaliseHistorica) -> Sinal:
    giro = _mediana(analise, "Investimento em giro (DFC) / Receita")
    crescimento = _mediana(analise, "Crescimento da receita")
    if not np.isfinite(giro):
        return Sinal(
            "giro", SEM_DADOS, "Sem a variação de giro da DFC",
            "A origem não trouxe a linha 6.01.02.",
        )

    texto = f"O capital de giro consumiu {giro:.1%} da receita ao ano, na mediana."
    if giro <= 0:
        return Sinal(
            "giro", BOM, "O giro liberou caixa",
            "O capital de giro devolveu caixa no período em vez de consumir.",
            giro,
        )
    if giro < 0.05:
        return Sinal("giro", BOM, "O giro consome pouco caixa", texto, giro)
    if np.isfinite(crescimento) and crescimento >= CRESCIMENTO_QUE_EXPLICA_GIRO:
        return Sinal(
            "giro", ATENCAO, "O giro consome caixa, acompanhando o crescimento",
            texto + f" A receita cresce {crescimento:.0%} ao ano, o que explica "
            "parte disso — mas é caixa que não chega ao acionista.",
            giro,
        )
    return Sinal(
        "giro", ATENCAO, "O giro consome caixa sem crescimento que explique",
        texto + " Vale olhar prazo de recebimento e estoque antes de projetar "
        "margem estável.",
        giro,
    )


def avaliar_qualidade(analise: AnaliseHistorica) -> QualidadeDosLucros:
    """Junta os sinais de caixa num veredito sobre a qualidade do lucro."""
    sinais = [_conversao(analise), _giro(analise), _juros(analise)]
    return QualidadeDosLucros(
        sinais=sinais,
        conversao_mediana=_mediana(analise, "Conversao de caixa (FCO / EBITDA)"),
    )
