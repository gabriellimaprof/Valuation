"""Orquestracao: de um objeto ``Empresa`` ate o valuation completo.

Este modulo amarra custo de capital -> projecao -> DCF, e oferece o utilitario
``substituir`` que troca uma premissa aninhada por caminho pontilhado. Esse
utilitario e o que torna possiveis as tabelas de sensibilidade e o Monte Carlo
sem duplicar a montagem do modelo.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .custo_capital import ResultadoCustoCapital, calcular_custo_capital
from .dcf import ResultadoDCF, avaliar_dcf, ponte_ev_equity
from .premissas import Empresa, PremissasPerpetuidade
from .projecao import Projecao, projetar


@dataclass(frozen=True)
class ResultadoValuation:
    """Um valuation completo, com cada etapa preservada para auditoria."""

    empresa: Empresa
    custo_capital: ResultadoCustoCapital
    projecao: Projecao
    dcf: ResultadoDCF

    @property
    def enterprise_value(self) -> float:
        return self.dcf.enterprise_value

    @property
    def equity_value(self) -> float:
        return self.dcf.equity_value

    @property
    def valor_por_acao(self) -> float | None:
        return self.dcf.valor_por_acao

    def tabela_ponte(self) -> pd.DataFrame:
        _, detalhe = ponte_ev_equity(self.dcf.enterprise_value, self.empresa.ponte)
        return detalhe

    def resumo(self) -> pd.DataFrame:
        """As poucas linhas que resumem o trabalho todo."""
        linhas = {
            "WACC (BRL nominal)": self.custo_capital.wacc_brl,
            "Ke (BRL nominal)": self.custo_capital.ke_brl,
            "Crescimento perpetuo": self.empresa.perpetuidade.crescimento_perpetuo,
            "VP dos fluxos explicitos": self.dcf.valor_presente_explicito,
            "VP do valor terminal": self.dcf.valor_presente_terminal,
            "% do EV na perpetuidade": self.dcf.peso_perpetuidade,
            "Enterprise Value": self.dcf.enterprise_value,
            "(-) Divida liquida": -self.empresa.ponte.divida_liquida,
            "Equity Value": self.dcf.equity_value,
        }
        if self.dcf.valor_por_acao is not None:
            linhas["Valor por acao"] = self.dcf.valor_por_acao
        return pd.DataFrame({"Valor": linhas})


def avaliar(
    empresa: Empresa,
    meio_de_ano: bool = False,
    tipo_fluxo: str = "fcff",
    taxa_desconto: float | None = None,
    divida_por_ano: list[float] | None = None,
) -> ResultadoValuation:
    """Roda o valuation completo de uma ``Empresa``.

    A taxa de desconto sai do WACC (para FCFF) ou do Ke (para FCFE) calculados
    a partir das premissas; ``taxa_desconto`` permite forcar um valor, o que e
    usado pelas tabelas de sensibilidade sobre o proprio WACC.
    """
    if empresa.operacionais is None:
        raise ValueError(
            f"A empresa {empresa.nome!r} nao tem premissas operacionais; "
            "sem elas nao ha projecao para descontar."
        )

    cc = calcular_custo_capital(empresa.custo_capital, empresa.macro)

    proj = projetar(
        empresa.operacionais,
        empresa.macro,
        divida_por_ano=divida_por_ano,
        divida_inicial=empresa.ponte.divida_bruta,
        custo_divida=cc.kd_bruto_brl,
        prejuizo_fiscal_acumulado=empresa.prejuizo_fiscal_acumulado,
    )

    if taxa_desconto is None:
        taxa_desconto = cc.ke_brl if tipo_fluxo == "fcfe" else cc.wacc_brl

    resultado = avaliar_dcf(
        proj,
        taxa_desconto=taxa_desconto,
        perpetuidade=empresa.perpetuidade,
        ponte=empresa.ponte,
        meio_de_ano=meio_de_ano,
        tipo_fluxo=tipo_fluxo,
    )
    return ResultadoValuation(
        empresa=empresa, custo_capital=cc, projecao=proj, dcf=resultado
    )


def substituir(objeto: Any, caminho: str, valor: Any) -> Any:
    """Devolve uma copia de ``objeto`` com ``caminho`` trocado por ``valor``.

    O caminho e pontilhado e navega dataclasses aninhadas, por exemplo
    ``"perpetuidade.crescimento_perpetuo"`` ou ``"custo_capital.rf_usd"``.
    Como as premissas sao imutaveis (``frozen=True``), nada e alterado no
    original -- o que evita que uma rodada de sensibilidade contamine a
    seguinte.

    Se o campo alvo for uma lista e o valor for escalar, o escalar e aplicado a
    todos os anos. E o comportamento util para premissas como
    ``operacionais.margem_ebitda``.
    """
    return substituir_varios(objeto, {caminho: valor})


def substituir_varios(objeto: Any, alteracoes: dict[str, Any]) -> Any:
    """Aplica varias substituicoes de caminho pontilhado de uma vez so.

    As alteracoes que atingem o mesmo bloco de premissas sao aplicadas em uma
    unica operacao, e nao em sequencia. A diferenca importa: trocar o metodo de
    perpetuidade para ``"multiplo"`` e informar o ``multiplo_saida`` sao duas
    alteracoes que, aplicadas uma de cada vez, passariam por um estado
    intermediario invalido e seriam rejeitadas pela validacao do bloco.
    """
    if not alteracoes:
        return objeto
    if not dataclasses.is_dataclass(objeto):
        raise TypeError(
            f"{objeto!r} nao e uma dataclass; caminhos {sorted(alteracoes)} invalidos."
        )

    validos = {f.name for f in dataclasses.fields(objeto)}
    folhas: dict[str, Any] = {}
    ramos: dict[str, dict[str, Any]] = {}
    for caminho, valor in alteracoes.items():
        campo, _, resto = caminho.partition(".")
        if campo not in validos:
            raise ValueError(
                f"{type(objeto).__name__} nao tem o campo {campo!r} "
                f"(caminho {caminho!r}). Campos aceitos: {sorted(validos)}"
            )
        if resto:
            ramos.setdefault(campo, {})[resto] = valor
        else:
            folhas[campo] = valor

    conflitos = set(folhas) & set(ramos)
    if conflitos:
        raise ValueError(
            f"Os campos {sorted(conflitos)} foram alterados como valor e como "
            "bloco ao mesmo tempo."
        )

    mudancas: dict[str, Any] = {}
    for campo, valor in folhas.items():
        atual = getattr(objeto, campo)
        if isinstance(atual, list) and not isinstance(valor, list):
            valor = [valor] * len(atual)
        mudancas[campo] = valor

    # Mexer num campo derivado na mao solta o que o derivava. Sem esta regra, o
    # valor informado seria reescrito ao remontar a Empresa, e uma tabela de
    # sensibilidade sobre o g sairia inteira igual -- sem erro, sem aviso, sem
    # nada na tela que explicasse por que. Quem passa a origem explicitamente
    # junto continua mandando.
    if isinstance(objeto, PremissasPerpetuidade):
        if "crescimento_perpetuo" in folhas:
            mudancas.setdefault("ancora", "livre")
        if "roic_perpetuidade" in folhas:
            mudancas.setdefault("roic_real", None)

    for campo, sub in ramos.items():
        atual = getattr(objeto, campo)
        if atual is None:
            raise ValueError(
                f"O campo {campo!r} esta vazio; nao da para navegar ate "
                f"{sorted(sub)}."
            )
        mudancas[campo] = substituir_varios(atual, sub)

    return dataclasses.replace(objeto, **mudancas)
