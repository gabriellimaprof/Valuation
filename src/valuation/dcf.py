"""Fluxo de caixa descontado: desconto, valor terminal e ponte EV -> equity."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .erros import CombinacaoInviavel
from .premissas import PonteValor, PremissasPerpetuidade
from .projecao import Projecao


def fatores_desconto(taxa: float, periodos: int, meio_de_ano: bool = False) -> np.ndarray:
    """Fatores de desconto para os periodos 1..n.

    Com ``meio_de_ano=True`` assume-se que o caixa e gerado uniformemente ao
    longo do ano, descontando em ``t - 0.5``. E a convencao usual quando a
    empresa nao concentra recebimentos no fim do exercicio.
    """
    if taxa <= -1:
        raise ValueError("A taxa de desconto precisa ser maior que -100%.")
    expoentes = np.arange(1, periodos + 1, dtype=float)
    if meio_de_ano:
        expoentes = expoentes - 0.5
    return 1 / (1 + taxa) ** expoentes


def valor_terminal_gordon(
    fluxo_final: float,
    taxa: float,
    crescimento: float,
    nopat_final: float | None = None,
    roic: float | None = None,
) -> float:
    """Valor terminal por crescimento perpetuo (Gordon), no fim do ano ``n``.

    Sem ``roic``, cresce-se o fluxo do ultimo ano projetado: ``FC_n * (1+g)/(r-g)``.

    Com ``roic`` e ``nopat_final``, o fluxo perpetuo e normalizado pela taxa de
    reinvestimento implicita ``g / ROIC``: ``NOPAT_n * (1+g) * (1 - g/ROIC) / (r-g)``.
    Esta e a forma consistente, porque crescer para sempre exige reinvestir para
    sempre; usar o fluxo do ultimo ano projetado costuma superestimar o valor
    terminal quando aquele ano tinha capex baixo.
    """
    if taxa <= crescimento:
        raise CombinacaoInviavel(
            f"Taxa de desconto ({taxa:.2%}) deve ser maior que o crescimento "
            f"perpetuo ({crescimento:.2%}); caso contrario o valor terminal e infinito."
        )
    if roic is not None:
        if nopat_final is None:
            raise ValueError("Normalizacao por ROIC exige nopat_final.")
        if crescimento > roic:
            raise CombinacaoInviavel(
                f"Crescimento perpetuo ({crescimento:.2%}) nao pode superar o "
                f"ROIC de perpetuidade ({roic:.2%})."
            )
        fluxo_perpetuo = nopat_final * (1 + crescimento) * (1 - crescimento / roic)
    else:
        fluxo_perpetuo = fluxo_final * (1 + crescimento)
    return fluxo_perpetuo / (taxa - crescimento)


def valor_terminal_multiplo(ebitda_final: float, multiplo: float) -> float:
    """Valor terminal por multiplo de saida sobre o EBITDA do ultimo ano."""
    if multiplo < 0:
        raise ValueError("multiplo_saida nao pode ser negativo.")
    return ebitda_final * multiplo


@dataclass(frozen=True)
class ResultadoDCF:
    """Saida completa de um DCF, com os intermediarios preservados."""

    fluxos: np.ndarray
    fatores: np.ndarray
    fluxos_descontados: np.ndarray
    valor_presente_explicito: float
    valor_terminal: float
    valor_presente_terminal: float
    enterprise_value: float
    equity_value: float
    valor_por_acao: float | None
    taxa_desconto: float
    tipo_fluxo: str
    anos: list[int]
    meio_de_ano: bool = False

    @property
    def peso_perpetuidade(self) -> float:
        """Fracao do EV que vem do valor terminal.

        Acima de ~75% e sinal de que a projecao explicita e curta demais ou de
        que as premissas de perpetuidade estao fazendo todo o trabalho.
        """
        if self.enterprise_value == 0:
            return float("nan")
        return self.valor_presente_terminal / self.enterprise_value

    def tabela_fluxos(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Fluxo": self.fluxos,
                "Fator de desconto": self.fatores,
                "Fluxo descontado": self.fluxos_descontados,
            },
            index=[f"Ano {a}" for a in self.anos],
        ).T


def ponte_ev_equity(enterprise_value: float, ponte: PonteValor) -> tuple[float, pd.DataFrame]:
    """Aplica a ponte EV -> Equity Value e devolve o detalhamento auditavel."""
    itens = [
        ("Enterprise Value", enterprise_value),
        ("(-) Divida bruta", -ponte.divida_bruta),
        ("(+) Caixa e equivalentes", ponte.caixa),
        ("(+) Aplicacoes financeiras", ponte.aplicacoes_financeiras),
        ("(-) Participacao de minoritarios", -ponte.minoritarios),
        ("(-) Contingencias", -ponte.contingencias),
        ("(-) Deficit atuarial", -ponte.deficit_atuarial),
        ("(+) Ativos nao operacionais", ponte.ativos_nao_operacionais),
    ]
    equity = sum(valor for _, valor in itens)
    itens.append(("Equity Value", equity))
    detalhe = pd.DataFrame(itens, columns=["Item", "Valor"]).set_index("Item")
    return equity, detalhe


def avaliar_dcf(
    projecao: Projecao,
    taxa_desconto: float,
    perpetuidade: PremissasPerpetuidade,
    ponte: PonteValor | None = None,
    meio_de_ano: bool = False,
    tipo_fluxo: str = "fcff",
) -> ResultadoDCF:
    """Desconta a projecao e monta o valor da empresa.

    ``tipo_fluxo="fcff"`` desconta o fluxo para a firma ao WACC e chega ao
    Enterprise Value, aplicando a ponte para o equity. ``tipo_fluxo="fcfe"``
    desconta o fluxo para o acionista ao Ke e ja chega ao Equity Value
    diretamente, sem ponte.
    """
    if tipo_fluxo not in ("fcff", "fcfe"):
        raise ValueError(f"tipo_fluxo desconhecido: {tipo_fluxo!r}")
    if tipo_fluxo == "fcfe":
        if projecao.fcfe is None:
            raise ValueError(
                "A projecao nao tem FCFE. Informe divida_por_ano em projetar()."
            )
        fluxos = projecao.fcfe
    else:
        fluxos = projecao.fcff

    n = projecao.horizonte
    fatores = fatores_desconto(taxa_desconto, n, meio_de_ano)
    descontados = fluxos * fatores
    vp_explicito = float(descontados.sum())

    if perpetuidade.metodo == "gordon":
        vt = valor_terminal_gordon(
            fluxo_final=float(fluxos[-1]),
            taxa=taxa_desconto,
            crescimento=perpetuidade.crescimento_perpetuo,
            nopat_final=float(projecao.nopat[-1]),
            roic=perpetuidade.roic_perpetuidade,
        )
    else:
        vt = valor_terminal_multiplo(
            float(projecao.ebitda[-1]), perpetuidade.multiplo_saida
        )

    # O valor terminal esta posicionado no fim do ano n, entao desconta por n
    # periodos inteiros mesmo quando os fluxos usam convencao de meio de ano.
    fator_terminal = 1 / (1 + taxa_desconto) ** n
    vp_terminal = vt * fator_terminal

    valor_operacional = vp_explicito + vp_terminal
    ponte = ponte or PonteValor()

    if tipo_fluxo == "fcff":
        enterprise_value = valor_operacional
        equity_value, _ = ponte_ev_equity(enterprise_value, ponte)
    else:
        equity_value = valor_operacional
        enterprise_value = equity_value + ponte.divida_liquida

    acoes = ponte.acoes_em_circulacao
    valor_acao = equity_value / acoes if acoes else None

    return ResultadoDCF(
        fluxos=fluxos,
        fatores=fatores,
        fluxos_descontados=descontados,
        valor_presente_explicito=vp_explicito,
        valor_terminal=vt,
        valor_presente_terminal=vp_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        valor_por_acao=valor_acao,
        taxa_desconto=taxa_desconto,
        tipo_fluxo=tipo_fluxo,
        anos=projecao.anos,
        meio_de_ano=meio_de_ano,
    )
