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

from .historico import AnaliseHistorica

# Faixas de referencia, deliberadamente largas: servem para separar o normal do
# que precisa de explicacao, nao para reprovar empresa.
CONVERSAO_BOA = 0.90
CONVERSAO_FRACA = 0.60
# Crescimento acima disto justifica caixa preso no giro sem que seja sinal ruim.
CRESCIMENTO_QUE_EXPLICA_GIRO = 0.15
# Diferenca entre juro de competencia e juro pago que sugere capitalizacao.
JURO_DESCOLADO = 0.02
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

    texto = f"A mediana do período converte {conversao:.0%} do EBITDA em caixa."
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

    diferenca = competencia - caixa
    if diferenca <= JURO_DESCOLADO:
        return Sinal(
            "juros", BOM, "O juro da DRE sai do caixa",
            f"Despesa financeira de {competencia:.1%} da dívida contra "
            f"{caixa:.1%} pagos: o custo aparece no caixa no mesmo período.",
            diferenca,
        )
    return Sinal(
        "juros", ATENCAO, "Parte do juro não saiu do caixa",
        f"A despesa financeira equivale a {competencia:.1%} da dívida média e o "
        f"juro pago a {caixa:.1%}. A diferença pode ser variação monetária, juro "
        "capitalizado em obra ou acúmulo para pagar depois — as três adiam caixa.",
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
