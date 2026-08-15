"""Custo de capital: beta, CAPM com risco-pais, custo da divida e WACC.

A construcao adotada e a usual para mercados emergentes (Damodaran):

1. Estima-se o beta desalavancado a partir dos comparaveis do setor (Hamada) e
   realavanca-se para a estrutura de capital alvo da empresa.
2. Monta-se o Ke em **USD nominal**: ``rf_usd + beta * ERP_maduro +
   lambda * risco_pais + premio_tamanho``.
3. Converte-se para **BRL nominal** por paridade de poder de compra, usando o
   diferencial de inflacao de longo prazo.

Trabalhar primeiro em USD evita o erro comum de somar um premio de risco
americano a uma taxa livre de risco brasileira (que ja embute inflacao e risco
soberano locais, gerando dupla contagem).
"""

from __future__ import annotations

from dataclasses import dataclass

from .premissas import PremissasCustoCapital, PremissasMacro


def desalavancar_beta(beta_alavancado: float, divida_pl: float, aliquota_ir: float) -> float:
    """Beta desalavancado (Hamada): ``bL / (1 + (1 - t) * D/E)``."""
    if divida_pl < 0:
        raise ValueError("divida_pl nao pode ser negativo.")
    return beta_alavancado / (1 + (1 - aliquota_ir) * divida_pl)


def realavancar_beta(beta_desalavancado: float, divida_pl: float, aliquota_ir: float) -> float:
    """Beta realavancado (Hamada): ``bu * (1 + (1 - t) * D/E)``."""
    if divida_pl < 0:
        raise ValueError("divida_pl nao pode ser negativo.")
    return beta_desalavancado * (1 + (1 - aliquota_ir) * divida_pl)


def converter_taxa(taxa: float, inflacao_destino: float, inflacao_origem: float) -> float:
    """Converte uma taxa nominal entre moedas pelo diferencial de inflacao.

    ``(1 + taxa) * (1 + inflacao_destino) / (1 + inflacao_origem) - 1``
    """
    return (1 + taxa) * (1 + inflacao_destino) / (1 + inflacao_origem) - 1


def pesos_estrutura_capital(divida_pl: float) -> tuple[float, float]:
    """Converte D/E em pesos ``(peso_divida, peso_equity)`` que somam 1."""
    if divida_pl < 0:
        raise ValueError("divida_pl nao pode ser negativo.")
    peso_divida = divida_pl / (1 + divida_pl)
    return peso_divida, 1 - peso_divida


@dataclass(frozen=True)
class ResultadoCustoCapital:
    """Custo de capital com todos os passos intermediarios preservados.

    Guardar os intermediarios importa: em valuation o numero final quase nunca
    e o entregavel, e sim a trilha que leva ate ele.
    """

    beta_desalavancado: float
    beta_realavancado: float
    ke_usd: float
    ke_brl: float
    kd_bruto_brl: float
    kd_liquido_brl: float
    peso_divida: float
    peso_equity: float
    wacc_brl: float
    wacc_usd: float
    aliquota_ir: float

    def resumo(self) -> dict[str, float]:
        """Dicionario ordenado para exibicao em relatorio ou planilha."""
        return {
            "Beta desalavancado": self.beta_desalavancado,
            "Beta realavancado": self.beta_realavancado,
            "Ke (USD nominal)": self.ke_usd,
            "Ke (BRL nominal)": self.ke_brl,
            "Kd bruto (BRL)": self.kd_bruto_brl,
            "Kd apos IR (BRL)": self.kd_liquido_brl,
            "Peso divida": self.peso_divida,
            "Peso equity": self.peso_equity,
            "WACC (BRL nominal)": self.wacc_brl,
            "WACC (USD nominal)": self.wacc_usd,
        }


def calcular_custo_capital(
    premissas: PremissasCustoCapital,
    macro: PremissasMacro | None = None,
) -> ResultadoCustoCapital:
    """Monta beta, Ke, Kd e WACC a partir das premissas de custo de capital."""
    macro = macro or PremissasMacro()
    t = macro.aliquota_ir

    if premissas.beta_desalavancado is not None:
        beta_u = premissas.beta_desalavancado
    else:
        beta_u = desalavancar_beta(
            premissas.beta_alavancado_setor, premissas.divida_pl_setor, t
        )
    beta_l = realavancar_beta(beta_u, premissas.divida_pl_alvo, t)

    ke_usd = (
        premissas.rf_usd
        + beta_l * premissas.erp_maduro
        + premissas.lambda_pais * premissas.risco_pais
        + premissas.premio_tamanho
    )
    ke_brl = converter_taxa(ke_usd, macro.inflacao_brl, macro.inflacao_usd)

    if premissas.custo_divida_brl is not None:
        kd_bruto_brl = premissas.custo_divida_brl
    else:
        # Kd sintetico: livre de risco global + risco soberano + spread de credito
        # da empresa, montado em USD e trazido para BRL pela mesma paridade.
        kd_usd = premissas.rf_usd + premissas.risco_pais + premissas.spread_credito
        kd_bruto_brl = converter_taxa(kd_usd, macro.inflacao_brl, macro.inflacao_usd)

    kd_liquido_brl = kd_bruto_brl * (1 - t)

    peso_divida, peso_equity = pesos_estrutura_capital(premissas.divida_pl_alvo)
    wacc_brl = peso_equity * ke_brl + peso_divida * kd_liquido_brl
    wacc_usd = converter_taxa(wacc_brl, macro.inflacao_usd, macro.inflacao_brl)

    return ResultadoCustoCapital(
        beta_desalavancado=beta_u,
        beta_realavancado=beta_l,
        ke_usd=ke_usd,
        ke_brl=ke_brl,
        kd_bruto_brl=kd_bruto_brl,
        kd_liquido_brl=kd_liquido_brl,
        peso_divida=peso_divida,
        peso_equity=peso_equity,
        wacc_brl=wacc_brl,
        wacc_usd=wacc_usd,
        aliquota_ir=t,
    )
