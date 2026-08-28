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
    base_normalizada: float | None = None,
    retorno: float | None = None,
) -> float:
    """Valor terminal por crescimento perpetuo (Gordon), no fim do ano ``n``.

    Sem ``retorno``, cresce-se o fluxo do ultimo ano projetado:
    ``FC_n * (1+g)/(r-g)``.

    Com ``retorno`` e ``base_normalizada``, o fluxo perpetuo desconta a taxa de
    reinvestimento implicita ``g / retorno``::

        base * (1+g) * (1 - g/retorno) / (r - g)

    Esta e a forma consistente, porque crescer para sempre exige reinvestir para
    sempre; usar o fluxo do ultimo ano projetado costuma superestimar o valor
    terminal quando aquele ano tinha capex baixo.

    **Os dois argumentos andam juntos e tem de estar na mesma moeda que o
    fluxo.** Numa serie para a firma sao NOPAT e ROIC; numa serie para o
    acionista sao lucro liquido e ROE. Eles se chamavam ``nopat_final`` e
    ``roic`` -- nomes que descreviam so o primeiro caso, e que faziam o segundo
    parecer certo enquanto normalizava um fluxo desalavancado dentro de uma
    serie de equity. Ver :func:`avaliar_dcf`.
    """
    if taxa <= crescimento:
        raise CombinacaoInviavel(
            f"Taxa de desconto ({taxa:.2%}) deve ser maior que o crescimento "
            f"perpetuo ({crescimento:.2%}); caso contrario o valor terminal e infinito."
        )
    if retorno is not None:
        if base_normalizada is None:
            raise ValueError(
                "Normalizacao do reinvestimento exige a base (NOPAT ou lucro)."
            )
        if crescimento > retorno:
            raise CombinacaoInviavel(
                f"Crescimento perpétuo ({crescimento:.2%}) não pode superar o "
                f"retorno de perpetuidade ({retorno:.2%})."
            )
        fluxo_perpetuo = (
            base_normalizada * (1 + crescimento) * (1 - crescimento / retorno)
        )
    else:
        fluxo_perpetuo = fluxo_final * (1 + crescimento)
    return fluxo_perpetuo / (taxa - crescimento)


def valor_terminal_multiplo(base_final: float, multiplo: float) -> float:
    """Valor terminal por multiplo de saida sobre a conta do ultimo ano.

    A conta e o EBITDA (EV/EBITDA) ou o lucro liquido (P/L), conforme
    ``PremissasPerpetuidade.base_do_multiplo``. **Os dois nao dao a mesma
    moeda**: EV/EBITDA devolve valor de firma e P/L devolve valor de equity --
    ver :func:`_terminal_na_moeda_do_fluxo`.
    """
    if multiplo < 0:
        raise ValueError("multiplo_saida nao pode ser negativo.")
    return base_final * multiplo


def _base_do_multiplo(projecao: Projecao, base: str) -> float:
    """A conta do ultimo ano projetado sobre a qual o multiplo incide."""
    if base == "lucro":
        if projecao.lucro_liquido is None:
            raise ValueError(
                "A projecao nao tem lucro liquido; o P/L de saida precisa dele."
            )
        return float(projecao.lucro_liquido[-1])
    return float(projecao.ebitda[-1])


def _terminal_na_moeda_do_fluxo(
    valor_terminal: float,
    e_de_equity: bool,
    tipo_fluxo: str,
    ponte: PonteValor,
) -> tuple[float, str]:
    """Converte o valor terminal para a moeda da serie que ele fecha.

    **O multiplo carrega a moeda da conta em que incide.** EV/EBITDA devolve
    valor de firma; P/L devolve valor de equity, porque o lucro liquido ja e
    depois do juro. Somar um ao outro na mesma serie e o erro que a regra da
    casa proibe -- multiplos de EV e de equity nao se misturam na ponte --, e
    aqui ele nao aparece como numero absurdo: a ponte roda, o valor sai, e a
    divida foi contada duas vezes ou nenhuma.

    A conversao usa a **divida liquida de hoje**, porque o modelo nao projeta
    balanco. E hipotese, entao ela volta como aviso em vez de sumir dentro do
    numero.
    """
    fluxo_e_de_equity = tipo_fluxo == "fcfe"
    if e_de_equity == fluxo_e_de_equity:
        return valor_terminal, ""

    divida_liquida = ponte.divida_liquida
    if e_de_equity:
        # Terminal de equity dentro de uma serie de firma: devolve-se a divida,
        # que a ponte vai tirar de novo la na frente.
        return valor_terminal + divida_liquida, (
            "O múltiplo de saída é de equity (P/L) e o fluxo é para a firma "
            "(FCFF): a dívida líquida de hoje foi somada ao valor terminal para "
            "não ser descontada duas vezes na ponte. O modelo não projeta "
            "balanço, então a dívida do ano terminal é suposta igual à de hoje."
        )
    return valor_terminal - divida_liquida, (
        "O múltiplo de saída é de firma (EV/EBITDA) e o fluxo é para o acionista "
        "(FCFE): a dívida líquida de hoje foi tirada do valor terminal — sem "
        "isso ela nunca seria descontada. O modelo não projeta balanço, então a "
        "dívida do ano terminal é suposta igual à de hoje."
    )



def _normalizacao_do_gordon(
    projecao: Projecao, perpetuidade: PremissasPerpetuidade, tipo_fluxo: str
) -> tuple[float, float | None, str]:
    """A base e o retorno da normalizacao, na moeda do fluxo que se desconta.

    Crescer para sempre exige reinvestir para sempre, e a taxa de reinvestimento
    e ``g / retorno``. **Mas os dois termos tem de descrever o mesmo capital que
    o fluxo remunera:**

    * numa serie **para a firma** (FCFF), a base e o NOPAT e o retorno e o ROIC;
    * numa serie **para o acionista** (FCFE), a base e o **lucro liquido** e o
      retorno e o **ROE**.

    O app usava NOPAT e ROIC nos dois casos. Num FCFE isso normaliza um fluxo
    desalavancado dentro de uma serie de equity e desconta o resultado ao Ke --
    e o numero sai maior, nao menor, porque o NOPAT ignora o juro que o
    acionista paga. Medido no fixture: **35,8% de equity value**, o mesmo tipo
    de erro que o multiplo de saida ja tinha.

    Quando o FCFE e escolhido e so o ROIC esta informado, ele e usado como ROE
    **com aviso**: e aproximacao, e o sentido dela e conservador -- num negocio
    alavancado e lucrativo o ROE supera o ROIC, entao usar o ROIC exagera a
    retencao e subestima o valor. Trocar a base, que e o erro grande, nao depende
    de premissa nova nenhuma.
    """
    if perpetuidade.roic_perpetuidade is None and perpetuidade.roe_perpetuidade is None:
        return float(projecao.nopat[-1]), None, ""

    if tipo_fluxo != "fcfe":
        return float(projecao.nopat[-1]), perpetuidade.roic_perpetuidade, ""

    if projecao.lucro_liquido is None:
        return (
            float(projecao.nopat[-1]),
            perpetuidade.roe_perpetuidade or perpetuidade.roic_perpetuidade,
            "A projeção não trouxe lucro líquido, então a normalização do "
            "reinvestimento usou o NOPAT — que é desalavancado. Num fluxo para o "
            "acionista isso superestima o valor terminal.",
        )

    base = float(projecao.lucro_liquido[-1])
    if perpetuidade.roe_perpetuidade is not None:
        return base, perpetuidade.roe_perpetuidade, ""

    return base, perpetuidade.roic_perpetuidade, (
        "O fluxo é para o acionista (FCFE) e a normalização do reinvestimento "
        "usou o **ROIC** como se fosse ROE, porque só ele foi informado. A base "
        "já é o lucro líquido, que é o que corrige o erro grande; o ROIC no "
        "lugar do ROE é aproximação conservadora — num negócio alavancado e "
        "lucrativo o ROE supera o ROIC, então isto exagera a retenção."
    )

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
    # O que o modelo assumiu e o numero sozinho nao conta. Hoje so o multiplo de
    # saida escreve aqui, quando a moeda do terminal nao era a da serie.
    avisos: tuple[str, ...] = ()

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
        ("(-) Dívida bruta", -ponte.divida_bruta),
        ("(+) Caixa e equivalentes", ponte.caixa),
        ("(+) Aplicações financeiras", ponte.aplicacoes_financeiras),
        ("(-) Participação de minoritários", -ponte.minoritarios),
        ("(-) Contingências", -ponte.contingencias),
        ("(-) Déficit atuarial", -ponte.deficit_atuarial),
        ("(+) Ativos não operacionais", ponte.ativos_nao_operacionais),
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
        base, retorno, aviso_do_terminal = _normalizacao_do_gordon(
            projecao, perpetuidade, tipo_fluxo
        )
        vt = valor_terminal_gordon(
            fluxo_final=float(fluxos[-1]),
            taxa=taxa_desconto,
            crescimento=perpetuidade.crescimento_perpetuo,
            base_normalizada=base,
            retorno=retorno,
        )
    else:
        base = perpetuidade.base_do_multiplo
        vt = valor_terminal_multiplo(
            _base_do_multiplo(projecao, base), perpetuidade.multiplo_saida
        )
        vt, aviso_do_terminal = _terminal_na_moeda_do_fluxo(
            vt, base == "lucro", tipo_fluxo, ponte or PonteValor()
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
        avisos=(aviso_do_terminal,) if aviso_do_terminal else (),
    )
