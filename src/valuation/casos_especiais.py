"""Ajustes contabeis que a analise de valuation exige e a contabilidade nao faz.

Tres situacoes em que os numeros publicados descrevem mal a economia da empresa:

* **P&D tratado como despesa.** A norma manda lancar pesquisa e desenvolvimento
  no resultado, mas economicamente e investimento: gera beneficio por varios
  anos. Sem o ajuste, empresas de tecnologia e farmaceuticas aparecem com lucro
  e capital investido subestimados, e com ROIC artificialmente alto.
* **Empresa ciclica avaliada no pico ou no fundo.** Projetar a partir da margem
  do ultimo ano de uma siderurgica ou de uma empresa de commodity e projetar um
  momento do ciclo como se fosse permanente.
* **Arrendamento operacional fora do balanco.** Depois do IFRS 16 / CPC 06 (R2)
  a maior parte ja esta no balanco, mas dados anteriores a 2019 e alguns
  reportes em US GAAP ainda deixam o compromisso de fora -- e ele e divida.

Cada funcao devolve o ajuste **e** o detalhamento de como chegou nele, porque
ajuste de valuation que nao pode ser auditado nao deveria ser usado.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .historico import AnaliseHistorica


@dataclass(frozen=True)
class AjustePD:
    """Resultado da capitalizacao de pesquisa e desenvolvimento."""

    ativo_de_pd: float
    amortizacao_do_ano: float
    ajuste_no_ebit: float
    detalhamento: pd.DataFrame

    @property
    def explicacao(self) -> str:
        return (
            f"O ativo de P&D de {self.ativo_de_pd:,.1f} passa a compor o capital "
            f"investido, e o EBIT sobe {self.ajuste_no_ebit:,.1f} (gasto do ano "
            f"devolvido ao lucro, menos a amortizacao de {self.amortizacao_do_ano:,.1f})."
        )


def capitalizar_pesquisa_desenvolvimento(
    gastos_por_ano: dict[int, float],
    vida_util: int = 5,
) -> AjustePD:
    """Converte P&D lancado como despesa em ativo amortizavel.

    Metodo do Damodaran: o gasto de cada um dos ultimos ``vida_util`` anos e
    tratado como investimento, amortizado linearmente. O ano corrente entra
    integralmente no ativo (ainda nao amortizado); o gasto de um ano atras entra
    com ``(vida_util - 1) / vida_util`` do valor, e assim por diante.

    ``gastos_por_ano`` mapeia ano para gasto de P&D daquele ano. Anos faltantes
    sao tratados como ausencia de informacao, nao como gasto zero, e o
    detalhamento mostra quais entraram.
    """
    if vida_util < 1:
        raise ValueError("vida_util deve ser de ao menos um ano.")
    if not gastos_por_ano:
        raise ValueError("Informe ao menos um ano de gasto com P&D.")

    anos = sorted(gastos_por_ano)
    ano_corrente = anos[-1]

    linhas = []
    ativo = 0.0
    amortizacao = 0.0
    for ano in anos:
        idade = ano_corrente - ano
        if idade > vida_util:
            continue
        gasto = float(gastos_por_ano[ano])
        parcela_nao_amortizada = max(0.0, (vida_util - idade) / vida_util)
        valor_no_ativo = gasto * parcela_nao_amortizada
        # O gasto do ano corrente ainda nao comecou a amortizar.
        amortizacao_do_ano = gasto / vida_util if idade > 0 else 0.0

        ativo += valor_no_ativo
        amortizacao += amortizacao_do_ano
        linhas.append(
            {
                "Ano": ano,
                "Gasto com P&D": gasto,
                "Idade (anos)": idade,
                "Parcela nao amortizada": parcela_nao_amortizada,
                "Valor no ativo": valor_no_ativo,
                "Amortizacao no ano corrente": amortizacao_do_ano,
            }
        )

    gasto_corrente = float(gastos_por_ano[ano_corrente])
    return AjustePD(
        ativo_de_pd=ativo,
        amortizacao_do_ano=amortizacao,
        ajuste_no_ebit=gasto_corrente - amortizacao,
        detalhamento=pd.DataFrame(linhas).set_index("Ano"),
    )


@dataclass(frozen=True)
class MargemNormalizada:
    """Margem de um setor ciclico, normalizada pelo ciclo inteiro."""

    margem_normalizada: float
    margem_do_ultimo_ano: float
    posicao_no_ciclo: str
    amplitude: float
    detalhamento: pd.Series

    @property
    def explicacao(self) -> str:
        return (
            f"A margem do ultimo ano ({self.margem_do_ultimo_ano:.1%}) esta no "
            f"{self.posicao_no_ciclo} do ciclo observado, cuja amplitude e de "
            f"{self.amplitude:.1%}. A mediana do periodo, {self.margem_normalizada:.1%}, "
            "descreve melhor um ano tipico."
        )


def normalizar_margem_ciclica(
    analise: AnaliseHistorica,
    indicador: str = "Margem EBITDA",
) -> MargemNormalizada:
    """Substitui a margem do ultimo ano pela mediana do ciclo observado.

    Empresas ciclicas nao tem uma margem: tem uma faixa. Projetar a partir do
    ultimo ano significa apostar que o momento atual do ciclo e o permanente --
    o erro classico de avaliar siderurgica no pico e varejo na crise.

    Quanto mais anos o historico cobrir, mais confiavel a normalizacao; com
    menos de um ciclo inteiro (tipicamente 5 a 7 anos) o resultado ainda carrega
    o vies do periodo escolhido.
    """
    serie = analise.linha(indicador).replace([np.inf, -np.inf], np.nan).dropna()
    if serie.empty:
        raise ValueError(f"Sem historico de '{indicador}' para normalizar.")
    if len(serie) < 3:
        raise ValueError(
            f"Normalizacao ciclica precisa de ao menos 3 anos de '{indicador}'; "
            f"ha {len(serie)}."
        )

    mediana = float(serie.median())
    ultimo = float(serie.iloc[-1])
    minimo, maximo = float(serie.min()), float(serie.max())
    amplitude = maximo - minimo

    if amplitude == 0:
        posicao = "meio"
    else:
        relativo = (ultimo - minimo) / amplitude
        posicao = "pico" if relativo > 0.66 else "fundo" if relativo < 0.33 else "meio"

    return MargemNormalizada(
        margem_normalizada=mediana,
        margem_do_ultimo_ano=ultimo,
        posicao_no_ciclo=posicao,
        amplitude=amplitude,
        detalhamento=serie,
    )


@dataclass(frozen=True)
class AjusteLeasing:
    """Capitalizacao de arrendamento operacional fora do balanco."""

    divida_equivalente: float
    ajuste_no_ebit: float
    detalhamento: pd.DataFrame

    @property
    def explicacao(self) -> str:
        return (
            f"O compromisso de aluguel equivale a uma divida de "
            f"{self.divida_equivalente:,.1f}, que entra na ponte de valor, e devolve "
            f"{self.ajuste_no_ebit:,.1f} ao EBIT (a parcela de juros embutida no aluguel)."
        )


def capitalizar_leasing_operacional(
    despesa_anual: float,
    prazo_anos: int,
    custo_divida: float,
) -> AjusteLeasing:
    """Converte aluguel operacional em divida equivalente e ajuste no EBIT.

    A divida equivalente e o valor presente dos alugueis futuros descontados ao
    custo da divida da empresa. O ajuste no EBIT devolve a parcela de juros
    embutida no aluguel, que economicamente e despesa financeira e nao
    operacional.

    Depois do IFRS 16 / CPC 06 (R2), vigente desde 2019, a maior parte dos
    arrendamentos ja esta reconhecida no balanco -- aplicar este ajuste sobre
    demonstracoes ja ajustadas contaria a mesma divida duas vezes.
    """
    if despesa_anual < 0:
        raise ValueError("despesa_anual deve ser positiva.")
    if prazo_anos < 1:
        raise ValueError("prazo_anos deve ser de ao menos um ano.")
    if custo_divida <= 0:
        raise ValueError("custo_divida deve ser positivo.")

    anos = np.arange(1, prazo_anos + 1)
    fatores = 1 / (1 + custo_divida) ** anos
    valores_presentes = despesa_anual * fatores
    divida = float(valores_presentes.sum())

    detalhamento = pd.DataFrame(
        {
            "Ano": anos,
            "Aluguel": despesa_anual,
            "Fator de desconto": fatores,
            "Valor presente": valores_presentes,
        }
    ).set_index("Ano")

    return AjusteLeasing(
        divida_equivalente=divida,
        ajuste_no_ebit=divida * custo_divida,
        detalhamento=detalhamento,
    )
