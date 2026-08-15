"""Retorno esperado do acionista (TSR) e sua decomposicao.

O DCF responde *quanto a empresa vale*. Esta e outra pergunta, e e a que o
investidor faz na frente da tela: **comprando a este preco, que retorno anual eu
espero, e de onde ele vem?**

A resposta se abre em tres fontes, mais um termo cruzado:

* **Crescimento do lucro** -- a empresa entrega mais lucro por acao ao longo do
  periodo.
* **Dividendos** -- caixa distribuido no caminho.
* **Expansao ou contracao de multiplo** -- o mercado passa a pagar mais (ou
  menos) por cada real de lucro. E a unica das tres que nao depende da empresa,
  e sim de quanto o proximo comprador estara disposto a pagar.
* **Termo cruzado** -- crescer o lucro *e* reavaliar o multiplo se multiplicam;
  o produto nao pertence a nenhuma das duas parcelas isoladamente.

A identidade usada e exata, nao aproximada::

    (1 + retorno de preco) = (1 + g_lucro) x (1 + g_multiplo)
    TSR = g_lucro + g_multiplo + (g_lucro x g_multiplo) + contribuicao dos dividendos

A regra de bolso que circula no mercado -- "TSR = crescimento + dividend yield +
re-rating" -- omite o termo cruzado. Ele e pequeno quando as taxas sao pequenas,
mas deixa de ser em um caso de 20% de crescimento com 30% de expansao de
multiplo, que e exatamente o caso em que a conta importa. Aqui ele aparece
separado, e as parcelas somam o TSR ate a ultima casa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .erros import CombinacaoInviavel
from .premissas import ALIQUOTA_IR_BRASIL
from .projecao import LIMITE_COMPENSACAO_PREJUIZO, Projecao

TIR_MINIMA = -0.9999
TIR_MAXIMA = 10.0


def valor_presente_liquido(
    taxa: float, fluxos: np.ndarray, tempos: np.ndarray | None = None
) -> float:
    """VPL de fluxos posicionados em ``tempos`` (por padrao ``0, 1, 2, ...``).

    Aceitar tempos fracionarios permite honrar a convencao de meio de ano do
    DCF. Sem isso, o retorno calculado aqui e o valor calculado la partiriam dos
    mesmos fluxos e chegariam a numeros diferentes -- que e o tipo de
    inconsistencia que destroi a confianca no modelo inteiro.
    """
    fluxos = np.asarray(fluxos, dtype=float)
    if tempos is None:
        tempos = np.arange(len(fluxos), dtype=float)
    else:
        tempos = np.asarray(tempos, dtype=float)
        if tempos.shape != fluxos.shape:
            raise ValueError("tempos e fluxos precisam ter o mesmo tamanho.")
    return float(np.sum(fluxos / (1 + taxa) ** tempos))


def tir(
    fluxos: np.ndarray,
    tolerancia: float = 1e-10,
    tempos: np.ndarray | None = None,
) -> float:
    """Taxa interna de retorno de uma serie de fluxos.

    Resolvida por bisseccao, que e lenta comparada a Newton mas nao diverge --
    e uma TIR que diverge silenciosamente para um numero absurdo e pior do que
    uma que demora um milissegundo a mais.

    Exige uma troca de sinal nos fluxos. Sem ela, nao existe TIR: um
    investimento que so gera entradas (ou so saidas) nao tem taxa de retorno
    definida.
    """
    fluxos = np.asarray(fluxos, dtype=float)
    if fluxos.size < 2:
        raise ValueError("A TIR precisa de ao menos dois fluxos.")
    if not np.isfinite(fluxos).all():
        raise ValueError("Ha fluxos nao finitos na serie.")
    if not (np.any(fluxos > 0) and np.any(fluxos < 0)):
        raise CombinacaoInviavel(
            "Os fluxos nao trocam de sinal, entao nao existe TIR. Confira se o "
            "preco de entrada esta lancado como saida de caixa."
        )

    baixo, alto = TIR_MINIMA, TIR_MAXIMA
    valor_baixo = valor_presente_liquido(baixo, fluxos, tempos)
    valor_alto = valor_presente_liquido(alto, fluxos, tempos)
    if valor_baixo * valor_alto > 0:
        raise CombinacaoInviavel(
            f"Nao ha TIR entre {TIR_MINIMA:.0%} e {TIR_MAXIMA:.0%} para estes fluxos."
        )

    for _ in range(200):
        meio = (baixo + alto) / 2
        valor_meio = valor_presente_liquido(meio, fluxos, tempos)
        if abs(valor_meio) < tolerancia or (alto - baixo) < tolerancia:
            return meio
        if valor_baixo * valor_meio < 0:
            alto, valor_alto = meio, valor_meio
        else:
            baixo, valor_baixo = meio, valor_meio
    return (baixo + alto) / 2


def _taxa_composta(final: float, inicial: float, anos: int) -> float:
    """Taxa anual composta entre dois valores positivos."""
    if anos <= 0:
        raise ValueError("O horizonte precisa de ao menos um ano.")
    if inicial <= 0 or final <= 0:
        return float("nan")
    return float((final / inicial) ** (1 / anos) - 1)


# ---------------------------------------------------------------------------
# Fluxos do acionista
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjecaoAcionista:
    """Lucro, dividendos e divida ano a ano, sob uma politica de distribuicao."""

    anos: list[int]
    divida_abertura: np.ndarray
    juros: np.ndarray
    lucro_antes_impostos: np.ndarray
    impostos: np.ndarray
    lucro_liquido: np.ndarray
    caixa_disponivel: np.ndarray
    dividendos: np.ndarray
    amortizacao: np.ndarray
    divida_fechamento: np.ndarray

    def tabela(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Dívida (abertura)": self.divida_abertura,
                "(-) Juros": -self.juros,
                "LAIR": self.lucro_antes_impostos,
                "(-) IR/CSLL": -self.impostos,
                "Lucro líquido": self.lucro_liquido,
                "Caixa livre para o acionista": self.caixa_disponivel,
                "Dividendos": self.dividendos,
                "Amortização de dívida": self.amortizacao,
                "Dívida (fechamento)": self.divida_fechamento,
            },
            index=[f"Ano {a}" for a in self.anos],
        ).T


def _imposto_do_ano(
    resultado: float, aliquota: float, saldo_prejuizo: float
) -> tuple[float, float]:
    """Imposto de um exercicio e o saldo de prejuizo que sobra depois dele.

    Mesma regra do motor de projecao (trava de 30% na compensacao), aplicada
    ano a ano porque aqui o resultado tributavel e o LAIR, que so fica conhecido
    depois de calculados os juros do proprio ano.
    """
    if resultado <= 0:
        return 0.0, saldo_prejuizo + float(-resultado)
    compensavel = min(saldo_prejuizo, LIMITE_COMPENSACAO_PREJUIZO * float(resultado))
    return (float(resultado) - compensavel) * aliquota, saldo_prejuizo - compensavel


def projetar_acionista(
    projecao: Projecao,
    divida_inicial: float,
    custo_divida: float,
    aliquota_ir: float = ALIQUOTA_IR_BRASIL,
    payout: float = 0.5,
    politica: str = "payout",
    amortizar_divida: bool = True,
    prejuizo_fiscal_acumulado: float = 0.0,
) -> ProjecaoAcionista:
    """Deriva lucro liquido, dividendos e trajetoria da divida da projecao operacional.

    ``politica`` aceita:

    * ``"payout"`` -- distribui ``payout`` do lucro liquido, limitado ao caixa
      que de fato sobra. Empresa nao paga dividendo que nao tem.
    * ``"fcfe"`` -- distribui todo o caixa livre do acionista.

    Com ``amortizar_divida``, o caixa que sobra depois do dividendo abate a
    divida. E a hipotese usual em analise de retorno com alavancagem: a
    desalavancagem transfere valor do credor para o acionista, e ignora-la
    subestima o retorno de empresas endividadas.
    """
    if politica not in ("payout", "fcfe"):
        raise ValueError(f"politica desconhecida: {politica!r}")
    if not 0 <= payout <= 1:
        raise ValueError("payout deve estar entre 0 e 1.")
    if divida_inicial < 0:
        raise ValueError("divida_inicial nao pode ser negativa.")

    n = projecao.horizonte
    divida_abertura = np.zeros(n)
    juros = np.zeros(n)
    lair = np.zeros(n)
    impostos = np.zeros(n)
    lucro_liquido = np.zeros(n)
    caixa_disponivel = np.zeros(n)
    dividendos = np.zeros(n)
    amortizacao = np.zeros(n)
    divida_fechamento = np.zeros(n)

    # Um unico laco porque as grandezas sao circulares dentro do ano: os juros
    # dependem da divida, a divida do fim do ano depende da amortizacao, a
    # amortizacao depende do que sobra depois do dividendo, e o dividendo
    # depende do lucro -- que depende dos juros. Resolver em passadas separadas
    # exigiria iterar ate convergir; ano a ano, a ordem e determinada.
    saldo_divida = float(divida_inicial)
    saldo_prejuizo = float(prejuizo_fiscal_acumulado)

    for i in range(n):
        divida_abertura[i] = saldo_divida
        juros[i] = saldo_divida * custo_divida
        lair[i] = projecao.ebit[i] - juros[i]

        imposto, saldo_prejuizo = _imposto_do_ano(lair[i], aliquota_ir, saldo_prejuizo)
        impostos[i] = imposto
        lucro_liquido[i] = lair[i] - imposto

        # O caixa do acionista parte do FCFF e paga os juros ja liquidos do
        # beneficio fiscal, que a projecao desalavancada nao capturou.
        caixa_disponivel[i] = projecao.fcff[i] - juros[i] * (1 - aliquota_ir)

        if politica == "fcfe":
            dividendo = max(caixa_disponivel[i], 0.0)
        else:
            # Empresa nao distribui dividendo que nao tem em caixa, por mais
            # que a politica de payout mande.
            dividendo = min(
                max(payout * lucro_liquido[i], 0.0), max(caixa_disponivel[i], 0.0)
            )
        dividendos[i] = dividendo

        sobra = caixa_disponivel[i] - dividendo
        amortizacao[i] = (
            min(max(sobra, 0.0), saldo_divida) if amortizar_divida else 0.0
        )
        saldo_divida -= amortizacao[i]
        divida_fechamento[i] = saldo_divida

    return ProjecaoAcionista(
        anos=projecao.anos,
        divida_abertura=divida_abertura,
        juros=juros,
        lucro_antes_impostos=lair,
        impostos=impostos,
        lucro_liquido=lucro_liquido,
        caixa_disponivel=caixa_disponivel,
        dividendos=dividendos,
        amortizacao=amortizacao,
        divida_fechamento=divida_fechamento,
    )


# ---------------------------------------------------------------------------
# Decomposicao do TSR pelo lado do equity (lucro e P/L)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecomposicaoTSR:
    """TSR esperado e suas fontes. As parcelas somam o total exatamente."""

    tsr: float
    contribuicao_crescimento: float
    contribuicao_multiplo: float
    contribuicao_cruzada: float
    contribuicao_dividendos: float

    preco_entrada: float
    preco_saida: float
    multiplo_entrada: float
    multiplo_saida: float
    lucro_entrada: float
    lucro_saida: float
    dividendos: np.ndarray
    fluxos: np.ndarray
    anos: int
    retorno_de_preco: float

    @property
    def dividend_yield_de_entrada(self) -> float:
        """Dividendo do primeiro ano sobre o preco pago (yield on cost)."""
        if self.preco_entrada <= 0 or self.dividendos.size == 0:
            return float("nan")
        return float(self.dividendos[0] / self.preco_entrada)

    @property
    def multiplo_de_saida_implicito(self) -> float:
        return self.multiplo_saida

    @property
    def residuo(self) -> float:
        """Diferenca entre o TSR e a soma das parcelas. Deve ser zero."""
        soma = (
            self.contribuicao_crescimento
            + self.contribuicao_multiplo
            + self.contribuicao_cruzada
            + self.contribuicao_dividendos
        )
        return self.tsr - soma

    def fecha(self, tolerancia: float = 1e-9) -> bool:
        """A decomposicao reconstitui o TSR?"""
        return abs(self.residuo) < tolerancia

    def tabela(self) -> pd.DataFrame:
        """Contribuicoes em pontos de retorno anual, e sua participacao no total."""
        linhas = [
            ("Crescimento do lucro", self.contribuicao_crescimento),
            ("Dividendos", self.contribuicao_dividendos),
            ("Expansão/contração de múltiplo", self.contribuicao_multiplo),
            ("Termo cruzado (crescimento × múltiplo)", self.contribuicao_cruzada),
        ]
        tabela = pd.DataFrame(linhas, columns=["Fonte", "Contribuição a.a."])
        total = self.tsr if self.tsr else float("nan")
        tabela["% do TSR"] = tabela["Contribuição a.a."] / total
        tabela.loc[len(tabela)] = ["TSR esperado (TIR)", self.tsr, 1.0]
        return tabela.set_index("Fonte")

    def resumo(self) -> pd.Series:
        return pd.Series(
            {
                "Preço de entrada": self.preco_entrada,
                "Preço de saída": self.preco_saida,
                "Múltiplo de entrada": self.multiplo_entrada,
                "Múltiplo de saída": self.multiplo_saida,
                "Lucro de entrada": self.lucro_entrada,
                "Lucro de saída": self.lucro_saida,
                "Dividendos acumulados": float(np.sum(self.dividendos)),
                "Retorno de preço a.a.": self.retorno_de_preco,
                "TSR esperado (TIR)": self.tsr,
            }
        )


def decompor_tsr(
    preco_entrada: float,
    lucro_entrada: float,
    lucro_saida: float,
    dividendos: np.ndarray | list[float],
    multiplo_saida: float | None = None,
    anos: int | None = None,
    meio_de_ano: bool = False,
) -> DecomposicaoTSR:
    """Decompoe o retorno esperado do acionista em suas fontes.

    ``multiplo_saida`` em ``None`` significa **sem re-rating**: sai-se pelo
    mesmo multiplo pago na entrada. E a hipotese neutra, e a mais honesta como
    caso base -- supor expansao de multiplo e supor que alguem pagara mais caro
    do que voce pagou, o que e uma aposta sobre o mercado, nao sobre a empresa.

    O horizonte sai do numero de dividendos informados, salvo se ``anos`` for
    passado explicitamente.

    ``meio_de_ano`` posiciona os dividendos em ``t - 0,5``, a mesma convencao
    que o DCF usa para os fluxos. A venda continua no fim do ano ``n``, porque
    e um evento pontual e nao um fluxo distribuido ao longo do periodo.
    """
    dividendos = np.asarray(dividendos, dtype=float)
    n = anos if anos is not None else len(dividendos)
    if n <= 0:
        raise ValueError("O horizonte precisa de ao menos um ano.")
    if preco_entrada <= 0:
        raise ValueError("preco_entrada deve ser positivo.")
    if lucro_entrada <= 0:
        raise CombinacaoInviavel(
            "O lucro de entrada precisa ser positivo para haver multiplo de "
            "entrada. Com prejuizo, use a decomposicao por EV/EBITDA."
        )

    multiplo_entrada = preco_entrada / lucro_entrada
    multiplo_final = multiplo_entrada if multiplo_saida is None else float(multiplo_saida)
    if multiplo_final <= 0:
        raise ValueError("multiplo_saida deve ser positivo.")

    preco_saida = lucro_saida * multiplo_final

    g_lucro = _taxa_composta(lucro_saida, lucro_entrada, n)
    g_multiplo = _taxa_composta(multiplo_final, multiplo_entrada, n)

    # Fluxos do investidor: paga na entrada, recebe dividendos e vende na saida.
    fluxos = np.zeros(n + 1)
    fluxos[0] = -preco_entrada
    fluxos[1 : len(dividendos) + 1] += dividendos[:n]
    fluxos[n] += preco_saida

    tempos = np.arange(n + 1, dtype=float)
    if meio_de_ano:
        tempos[1:n] -= 0.5
        # O ultimo periodo carrega dividendo (meio do ano) e venda (fim do ano)
        # somados na mesma celula; separa-los preserva as duas datas.
        if n >= 1 and dividendos.size >= n and dividendos[n - 1] != 0:
            fluxos = np.append(fluxos, 0.0)
            fluxos[n] -= dividendos[n - 1]
            fluxos[n + 1] = dividendos[n - 1]
            tempos = np.append(tempos, n - 0.5)

    taxa_total = tir(fluxos, tempos=tempos)

    if np.isfinite(g_lucro) and np.isfinite(g_multiplo):
        retorno_de_preco = (1 + g_lucro) * (1 + g_multiplo) - 1
        cruzado = g_lucro * g_multiplo
    else:
        retorno_de_preco = _taxa_composta(preco_saida, preco_entrada, n)
        cruzado = float("nan")

    # A contribuicao dos dividendos e definida como o que sobra: e o unico jeito
    # de a decomposicao fechar exatamente contra uma TIR, que capitaliza os
    # recebimentos intermediarios de forma nao aditiva.
    contribuicao_dividendos = taxa_total - retorno_de_preco

    return DecomposicaoTSR(
        tsr=taxa_total,
        contribuicao_crescimento=g_lucro,
        contribuicao_multiplo=g_multiplo,
        contribuicao_cruzada=cruzado,
        contribuicao_dividendos=contribuicao_dividendos,
        preco_entrada=float(preco_entrada),
        preco_saida=float(preco_saida),
        multiplo_entrada=float(multiplo_entrada),
        multiplo_saida=float(multiplo_final),
        lucro_entrada=float(lucro_entrada),
        lucro_saida=float(lucro_saida),
        dividendos=dividendos,
        fluxos=fluxos,
        anos=n,
        retorno_de_preco=retorno_de_preco,
    )


# ---------------------------------------------------------------------------
# Ponte de criacao de valor pelo lado do EV (EBITDA, multiplo e desalavancagem)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PonteDeValor:
    """Decomposicao em valor do ganho do acionista, no formato usado em private equity.

    Aqui as parcelas estao em **moeda**, nao em taxa, e somam exatamente a
    variacao do equity. E a leitura complementar a do TSR: em empresa
    alavancada, boa parte do retorno vem de a divida encolher, e isso nao
    aparece como crescimento nem como multiplo.
    """

    equity_entrada: float
    equity_saida: float
    contribuicao_ebitda: float
    contribuicao_multiplo: float
    contribuicao_cruzada: float
    contribuicao_desalavancagem: float
    dividendos_acumulados: float

    ebitda_entrada: float
    ebitda_saida: float
    multiplo_entrada: float
    multiplo_saida: float
    divida_entrada: float
    divida_saida: float

    @property
    def ganho_total(self) -> float:
        """Variacao do equity mais os dividendos recebidos no caminho."""
        return self.equity_saida - self.equity_entrada + self.dividendos_acumulados

    @property
    def residuo(self) -> float:
        soma = (
            self.contribuicao_ebitda
            + self.contribuicao_multiplo
            + self.contribuicao_cruzada
            + self.contribuicao_desalavancagem
            + self.dividendos_acumulados
        )
        return self.ganho_total - soma

    def fecha(self, tolerancia: float = 1e-6) -> bool:
        return abs(self.residuo) < tolerancia

    def tabela(self) -> pd.DataFrame:
        linhas = [
            ("Equity na entrada", self.equity_entrada),
            ("Crescimento do EBITDA", self.contribuicao_ebitda),
            ("Expansão/contração de múltiplo", self.contribuicao_multiplo),
            ("Termo cruzado", self.contribuicao_cruzada),
            ("Desalavancagem (redução da dívida)", self.contribuicao_desalavancagem),
            ("Dividendos recebidos", self.dividendos_acumulados),
            ("Equity na saída + dividendos", self.equity_saida + self.dividendos_acumulados),
        ]
        return pd.DataFrame(linhas, columns=["Item", "Valor"]).set_index("Item")


def decompor_ponte_ev(
    ebitda_entrada: float,
    ebitda_saida: float,
    multiplo_entrada: float,
    divida_entrada: float,
    divida_saida: float,
    dividendos_acumulados: float = 0.0,
    multiplo_saida: float | None = None,
) -> PonteDeValor:
    """Ponte de criacao de valor por EV/EBITDA, com a desalavancagem separada.

    A identidade e exata::

        Equity = EBITDA x multiplo - divida

        variacao = (dEBITDA x M0) + (dM x EBITDA0) + (dEBITDA x dM) + (D0 - Dn)

    Cada parcela responde a uma pergunta diferente: a empresa melhorou, o
    mercado reavaliou, ou a divida simplesmente encolheu com o caixa gerado?
    """
    multiplo_final = (
        multiplo_entrada if multiplo_saida is None else float(multiplo_saida)
    )
    equity_entrada = ebitda_entrada * multiplo_entrada - divida_entrada
    equity_saida = ebitda_saida * multiplo_final - divida_saida

    variacao_ebitda = ebitda_saida - ebitda_entrada
    variacao_multiplo = multiplo_final - multiplo_entrada

    return PonteDeValor(
        equity_entrada=float(equity_entrada),
        equity_saida=float(equity_saida),
        contribuicao_ebitda=float(variacao_ebitda * multiplo_entrada),
        contribuicao_multiplo=float(variacao_multiplo * ebitda_entrada),
        contribuicao_cruzada=float(variacao_ebitda * variacao_multiplo),
        contribuicao_desalavancagem=float(divida_entrada - divida_saida),
        dividendos_acumulados=float(dividendos_acumulados),
        ebitda_entrada=float(ebitda_entrada),
        ebitda_saida=float(ebitda_saida),
        multiplo_entrada=float(multiplo_entrada),
        multiplo_saida=float(multiplo_final),
        divida_entrada=float(divida_entrada),
        divida_saida=float(divida_saida),
    )


def preco_para_tsr(
    tsr_alvo: float,
    lucro_entrada_por_preco: float,
    lucro_saida: float,
    dividendos: np.ndarray | list[float],
    multiplo_saida: float,
    anos: int | None = None,
    tolerancia: float = 1e-8,
) -> float:
    """Preco maximo a pagar para obter o TSR desejado.

    Responde a pergunta que o investidor faz de verdade: *ate quanto vale a pena
    pagar?* -- em vez de aceitar o preco de tela e descobrir o retorno depois.

    ``lucro_entrada_por_preco`` e o lucro de referencia da entrada; ele nao
    depende do preco, ao contrario do multiplo de entrada, que e recalculado a
    cada tentativa. O multiplo de saida e informado em nivel absoluto,
    justamente para nao acompanhar o preco de entrada durante a busca.
    """
    dividendos = np.asarray(dividendos, dtype=float)
    n = anos if anos is not None else len(dividendos)
    if n <= 0:
        raise ValueError("O horizonte precisa de ao menos um ano.")
    if multiplo_saida <= 0:
        raise ValueError("multiplo_saida deve ser positivo.")
    if tsr_alvo <= -1:
        raise ValueError("tsr_alvo deve ser maior que -100%.")

    # O preco de saida e os dividendos nao dependem do preco de entrada, entao o
    # valor procurado e simplesmente o valor presente deles ao TSR alvo.
    preco_saida = lucro_saida * multiplo_saida
    fluxos_recebidos = np.zeros(n + 1)
    fluxos_recebidos[1 : len(dividendos) + 1] += dividendos[:n]
    fluxos_recebidos[n] += preco_saida

    preco = valor_presente_liquido(tsr_alvo, fluxos_recebidos)
    if preco <= tolerancia:
        raise CombinacaoInviavel(
            f"Nenhum preco positivo entrega {tsr_alvo:.1%} com estes fluxos."
        )
    return float(preco)


def multiplo_de_saida_do_dcf(
    resultado, lucro_saida: float, divida_saida: float = 0.0
) -> float:
    """Multiplo de saida que o proprio DCF ja implica no ultimo ano projetado.

    O valor terminal do DCF **e** o Enterprise Value da empresa no fim do ano
    ``n``. Tirando dele a divida daquele momento chega-se ao equity de saida, e
    dividindo pelo lucro do ano ``n`` sai o P/L implicito.

    Usar este multiplo como saida do TSR e o que mantem as duas analises
    contando a mesma historia: qualquer multiplo diferente equivale a apostar
    que o mercado reavaliara a empresa acima ou abaixo do que o proprio modelo
    de fluxo de caixa sustenta -- o que e uma hipotese legitima, desde que
    consciente.
    """
    if lucro_saida <= 0:
        raise CombinacaoInviavel(
            "O lucro do ultimo ano projetado nao e positivo; nao ha P/L de saida."
        )
    equity_saida = resultado.dcf.valor_terminal - divida_saida
    if equity_saida <= 0:
        raise CombinacaoInviavel(
            "O valor terminal nao cobre a divida projetada para o fim do periodo."
        )
    return float(equity_saida / lucro_saida)
