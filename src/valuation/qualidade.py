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
CONVERSAO_FRACA = 0.17
# Reconferidos depois que a conversao virou dois degraus: continuam sendo os
# quartis da safra 2021-2025 em `referencias.BASE` (P25 = 0,166 e P75 = 0,785,
# n = 409). A separacao entre CGO e FCO nao mudou a distribuicao do FCO -- ela
# mudou o que se **conclui** de um FCO baixo --, entao nao ha o que recalibrar
# aqui. O que faltava medir na safra era o corte da conversao operacional.
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
JURO_DESCOLADO = 0.100
JURO_MUITO_DESCOLADO = 0.138
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

    # **Antes de culpar a operacao, olhar o degrau de cima.** O FCO e liquido de
    # giro, imposto e juro; o CGO nao e. Medido em 2024, 190 das 371 companhias
    # com os dois numeros -- metade da base -- tem CGO acima de 78% do EBITDA e
    # FCO abaixo disso. Nelas o resultado **vira** caixa, e o que consome esta
    # abaixo da operacao. Dizer "o EBITDA nao vira caixa" ali manda o analista
    # procurar receita fictícia onde o que ha e divida cara.
    operacional = _mediana(analise, "Conversao operacional (CGO / EBITDA)")
    if np.isfinite(operacional) and operacional >= CGO_BOM:
        return Sinal(
            "conversao", ATENCAO,
            "A operação gera caixa; o consumo está abaixo dela",
            texto
            + f" Mas a conversão **até o caixa das operações** é de "
            f"{operacional:.0%}{_onde_na_base(operacional)}: o resultado vira "
            "caixa, e a distância até o FCO está no capital de giro, no imposto "
            "e no juro pagos — não na operação."
            + _culpado_da_ponte(analise),
            conversao,
        )

    # **A operação já não converte, e isso é diferente de "sobra pouco".** Quando
    # o caixa gerado pelas operações também está baixo, a distância não está no
    # giro, no imposto nem no juro: está antes deles, no resultado que não se
    # realiza. É o caso em que o sinal aponta para o lugar certo dizendo o nome.
    if np.isfinite(operacional) and operacional < CGO_FRACO:
        return Sinal(
            "conversao", RUIM,
            "Nem o caixa das operações acompanha o EBITDA",
            texto
            + f" E a conversão **até o caixa das operações** é de "
            f"{operacional:.0%}{_onde_na_base(operacional)}: a distância aparece "
            "**antes** de giro, imposto e juro, então não é consumo abaixo da "
            "operação — é resultado que não se realiza em caixa.",
            conversao,
        )

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




def _onde_na_base(operacional: float) -> str:
    """O percentil da conversao operacional, entre parenteses.

    O corte absoluto diz o que a conta significa; o percentil diz se o numero e
    incomum **aqui**. Numa conversao cuja mediana passa de 100%, o segundo
    importa mais que o normal: 90% parece otimo e e quartil inferior.
    """
    onde = referencias.descrever("Conversao operacional (CGO / EBITDA)", operacional)
    return f" ({onde})" if onde else ""

def _culpado_da_ponte(analise: AnaliseHistorica) -> str:
    """Qual dos tres degraus abaixo do CGO consumiu mais caixa, com o numero.

    "Esta no giro, no imposto ou no juro" nao dirige atencao -- sao tres lugares
    para procurar. O maior deles, com o tamanho em percentual do EBITDA, e uma
    frase so e manda o analista direto ao lugar certo.
    """
    ponte = ponte_do_caixa(analise)
    if ponte is None or not np.isfinite(ponte.ebitda) or ponte.ebitda == 0:
        return ""

    consumos = {
        "no capital de giro": -ponte.giro,
        "no imposto de renda pago": abs(ponte.imposto),
        "no juro pago": abs(ponte.juro),
    }
    onde, quanto = max(consumos.items(), key=lambda item: item[1])
    if quanto <= 0:
        return ""
    return f" O maior consumo está {onde}: {quanto / ponte.ebitda:.0%} do EBITDA."

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
        " A mediana de 260 companhias brasileiras descola 5,9 p.p., porque a linha "
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
    # Mesma regra da conversao: o corte absoluto diz o que a conta significa, o
    # percentil diz se o numero e incomum aqui. A mediana brasileira consome
    # 2,8% da receita em giro, entao 5% nao e o exagero que a intuicao sugere.
    onde = referencias.descrever("Investimento em giro (DFC) / Receita", giro)
    if onde:
        texto += f" Isso a coloca {onde}."
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


# ---------------------------------------------------------------------------
# A ponte EBITDA -> CGO -> FCO
# ---------------------------------------------------------------------------

# Cortes da conversao **operacional**, agora medidos na safra 2021-2025 -- a
# mesma de `referencias.BASE` e com a mesma metodologia (mediana por companhia,
# quantis entre companhias), em 398 companhias:
#
#     P10 = 53,7%   P25 = 85,9%   P50 = 102,9%   P75 = 115,9%
#
# Sairam de uma medicao de **um ano so** (0,89 e 0,60), que e o defeito que este
# projeto ja pagou duas vezes: corte de leitura calibrado fora da safra vira
# ruido. Na safra os quartis mudaram pouco, o que e uma boa noticia -- mas so da
# para dizer isso depois de medir.
#
# A mediana passa de 100% e nao e anomalia: o CGO devolve ao lucro despesas que
# nao foram caixa e que o EBITDA nao captura -- provisao, impairment.
#
# **Os quantis foram conferidos contra uma segunda medicao independente** -- uma
# amostra aleatoria de 180 companhias da mesma safra, n=161 depois dos descartes.
# Ela chega a P10 = 54,0%, P25 = 86,8% e mediana 104,2%, dentro de 1,5 ponto da
# medicao completa em todos os quantis; a distancia mediana ate o FCO da 49,6%
# contra 48,9%. Os cortes nao sao artefato de amostragem.
#
# `CGO_BOM` e o **P25**, e nao o P75 como em `CONVERSAO_BOA`, e a diferenca e
# proposital: ele nao pergunta "esta entre as melhores?", pergunta "a operacao
# converte?". Estar acima do quarto inferior ja responde que sim, e e por isso
# que ele alcanca 73% da base -- para a maioria das companhias o FCO fraco e
# mesmo giro, imposto e juro.
CGO_BOM = 0.86
# O P10. Um veredito **ruim** tem de ser mais raro que um de atencao: este
# acusa 10% da base, contra os 25% do quartil inferior do FCO.
CGO_FRACO = 0.54


@dataclass(frozen=True)
class PonteDoCaixa:
    """De EBITDA a FCO, com cada degrau nomeado e medido em % do EBITDA.

    A identidade que a DFC pelo metodo indireto publica::

        FCO = CGO + variacao do giro + outros - imposto pago - juro pago

    Ela existe para separar **tres perguntas que a conversao FCO/EBITDA junta
    numa so**: o resultado virou caixa? o giro prendeu caixa? quanto saiu para
    imposto e juro? Medido em 2024, metade da base (190 de 371) tem CGO acima de
    78% do EBITDA e FCO abaixo disso -- o sinal antigo acusava essas companhias
    de nao converter, quando a operacao converte e o consumo esta abaixo dela.
    """

    ebitda: float
    cgo: float
    giro: float
    outros: float
    imposto: float
    juro: float
    fco: float

    def _fracao(self, valor: float) -> float:
        if not np.isfinite(self.ebitda) or self.ebitda == 0:
            return float("nan")
        return valor / self.ebitda

    @property
    def conversao_operacional(self) -> float:
        """Quanto do EBITDA chega ao caixa gerado pelas operacoes."""
        return self._fracao(self.cgo)

    @property
    def conversao_final(self) -> float:
        return self._fracao(self.fco)

    @property
    def degraus(self) -> list[tuple[str, float, float]]:
        """Cada degrau da ponte: rotulo, valor e fracao do EBITDA."""
        return [
            ("EBITDA", self.ebitda, self._fracao(self.ebitda)),
            ("(±) Ajustes que não são caixa", self.cgo - self.ebitda,
             self._fracao(self.cgo - self.ebitda)),
            ("= Caixa gerado pelas operações", self.cgo, self.conversao_operacional),
            ("(±) Variação do capital de giro", self.giro, self._fracao(self.giro)),
            ("(−) Imposto de renda pago", -abs(self.imposto),
             self._fracao(-abs(self.imposto))),
            ("(−) Juros pagos", -abs(self.juro), self._fracao(-abs(self.juro))),
            ("(±) Outros operacionais", self.outros, self._fracao(self.outros)),
            ("= Fluxo de caixa operacional", self.fco, self.conversao_final),
        ]

    @property
    def fecha(self) -> bool:
        """A ponte reconstroi o FCO publicado?

        Medido na base: com o termo ``6.01.03`` incluido ela fecha em 96,8% das
        companhias. Sem ele fechava em 59% -- e essa diferenca ja custou uma
        auditoria inteira, entao a verificacao anda junto.
        """
        montado = (
            self.cgo + self.giro + self.outros - abs(self.imposto) - abs(self.juro)
        )
        if not np.isfinite(montado) or not np.isfinite(self.fco):
            return False
        return abs(montado - self.fco) <= max(abs(self.fco), 1.0) * 0.01


def ponte_do_caixa(analise: AnaliseHistorica, ano: int | None = None) -> PonteDoCaixa | None:
    """Monta a ponte de um ano; ``None`` quando a DFC nao permite."""
    d = analise.demonstracoes
    ano = ano if ano is not None else d.ano_base
    if ano is None:
        return None

    def v(chave: str) -> float:
        return d.valor(chave, ano)

    # O EBITDA nao e conta canonica: e derivado, EBIT + D&A.
    ebitda = v("ebit") + v("depreciacao_amortizacao")
    cgo, fco = v("caixa_das_operacoes"), v("fluxo_operacional")
    if not (np.isfinite(ebitda) and np.isfinite(cgo) and np.isfinite(fco)):
        return None

    def ou_zero(chave: str) -> float:
        valor = v(chave)
        return valor if np.isfinite(valor) else 0.0

    return PonteDoCaixa(
        ebitda=ebitda,
        cgo=cgo,
        giro=ou_zero("variacao_capital_giro"),
        outros=ou_zero("outros_operacionais"),
        imposto=ou_zero("impostos_pagos"),
        juro=ou_zero("juros_pagos"),
        fco=fco,
    )
