"""Estruturas de premissas usadas por todos os modulos de valuation.

Convencao de unidades adotada em todo o projeto:

* Taxas (crescimento, margens, juros, inflacao, aliquotas) sao decimais:
  ``0.12`` significa 12% a.a. Nunca ``12``.
* Valores monetarios ficam sempre na mesma unidade e moeda dentro de um mesmo
  modelo (tipicamente R$ milhoes). O projeto nao converte unidades: quem
  informa as premissas garante a consistencia.
* Fluxos anuais. O ano 1 e o primeiro ano projetado apos a data-base.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Aliquota combinada IRPJ (15% + adicional de 10%) + CSLL (9%) do lucro real.
ALIQUOTA_IR_BRASIL = 0.34


@dataclass(frozen=True)
class PremissasMacro:
    """Premissas de mercado que independem da empresa avaliada.

    ``inflacao_brl`` e ``inflacao_usd`` sao as inflacoes de longo prazo usadas
    para converter um custo de capital estimado em USD nominal para BRL
    nominal (paridade de poder de compra).
    """

    inflacao_brl: float = 0.04
    inflacao_usd: float = 0.023
    aliquota_ir: float = ALIQUOTA_IR_BRASIL

    def __post_init__(self) -> None:
        for nome in ("inflacao_brl", "inflacao_usd", "aliquota_ir"):
            valor = getattr(self, nome)
            if not -1 < valor < 1:
                raise ValueError(
                    f"{nome}={valor!r} fora do intervalo esperado. "
                    "Use decimais (0.34 para 34%), nao percentuais."
                )


@dataclass(frozen=True)
class PremissasCustoCapital:
    """Insumos para montar Ke (CAPM) e WACC.

    O modelo segue a construcao usual para mercados emergentes: estima-se o
    custo de capital em USD nominal a partir de parametros de um mercado
    maduro (EUA) somados ao risco-pais, e depois converte-se para BRL nominal.

    ``beta_alavancado_setor`` e ``divida_pl_setor`` descrevem os comparaveis
    de onde vem o beta; ``divida_pl_alvo`` e a estrutura de capital alvo da
    empresa avaliada, usada tanto para realavancar o beta quanto para ponderar
    o WACC. Alternativamente informe ``beta_desalavancado`` direto.
    """

    rf_usd: float = 0.045
    erp_maduro: float = 0.045
    risco_pais: float = 0.025
    beta_alavancado_setor: float | None = 1.0
    beta_desalavancado: float | None = None
    divida_pl_setor: float = 0.0
    divida_pl_alvo: float = 0.0
    lambda_pais: float = 1.0
    premio_tamanho: float = 0.0
    custo_divida_brl: float | None = None
    spread_credito: float = 0.03

    def __post_init__(self) -> None:
        if self.beta_alavancado_setor is None and self.beta_desalavancado is None:
            raise ValueError(
                "Informe beta_alavancado_setor (com divida_pl_setor) ou "
                "beta_desalavancado."
            )
        for nome in ("divida_pl_setor", "divida_pl_alvo"):
            if getattr(self, nome) < 0:
                raise ValueError(f"{nome} nao pode ser negativo.")
        if self.lambda_pais < 0:
            raise ValueError("lambda_pais nao pode ser negativo.")


@dataclass(frozen=True)
class PremissasOperacionais:
    """Direcionadores da projecao explicita, um valor por ano projetado.

    As listas ``crescimento_receita``, ``margem_ebitda``, ``depreciacao_pct_receita``,
    ``capex_pct_receita`` e ``capital_giro_pct_receita`` devem ter o mesmo
    comprimento, que define o horizonte da projecao.

    ``capital_giro_pct_receita`` e o *saldo* de capital de giro liquido como
    percentual da receita do ano; a variacao usada no fluxo e derivada dele.
    """

    receita_base: float
    crescimento_receita: list[float]
    margem_ebitda: list[float]
    depreciacao_pct_receita: list[float]
    capex_pct_receita: list[float]
    capital_giro_pct_receita: list[float]
    capital_giro_inicial: float | None = None
    ano_base: int = 0

    def __post_init__(self) -> None:
        if self.receita_base <= 0:
            raise ValueError("receita_base deve ser positiva.")
        tamanhos = {
            "crescimento_receita": len(self.crescimento_receita),
            "margem_ebitda": len(self.margem_ebitda),
            "depreciacao_pct_receita": len(self.depreciacao_pct_receita),
            "capex_pct_receita": len(self.capex_pct_receita),
            "capital_giro_pct_receita": len(self.capital_giro_pct_receita),
        }
        if len(set(tamanhos.values())) != 1:
            raise ValueError(
                f"As listas de premissas operacionais tem tamanhos diferentes: {tamanhos}"
            )
        if next(iter(tamanhos.values())) == 0:
            raise ValueError("A projecao precisa de ao menos um ano.")

    @property
    def horizonte(self) -> int:
        """Numero de anos da projecao explicita."""
        return len(self.crescimento_receita)


@dataclass(frozen=True)
class PremissasPerpetuidade:
    """Como o valor terminal e calculado.

    ``metodo`` aceita ``"gordon"`` (crescimento perpetuo) ou ``"multiplo"``
    (multiplo de saida sobre o EBITDA do ultimo ano projetado).

    Em Gordon, ``roic_perpetuidade`` permite normalizar o reinvestimento: o
    fluxo perpetuo passa a ser ``NOPAT_n * (1 + g) * (1 - g / ROIC)``, que e a
    unica forma consistente de crescer para sempre. Sem ele, o fluxo do ultimo
    ano projetado e simplesmente crescido a ``g``.
    """

    metodo: str = "gordon"
    crescimento_perpetuo: float = 0.04
    roic_perpetuidade: float | None = None
    multiplo_saida: float | None = None

    def __post_init__(self) -> None:
        if self.metodo not in ("gordon", "multiplo"):
            raise ValueError(f"metodo de perpetuidade desconhecido: {self.metodo!r}")
        if self.metodo == "multiplo" and self.multiplo_saida is None:
            raise ValueError("metodo 'multiplo' exige multiplo_saida.")
        if self.roic_perpetuidade is not None and self.roic_perpetuidade <= 0:
            raise ValueError("roic_perpetuidade deve ser positivo.")


@dataclass(frozen=True)
class PonteValor:
    """Itens que ligam o Enterprise Value ao Equity Value na data-base.

    Sinais ja embutidos: ``divida_bruta``, ``minoritarios``, ``contingencias`` e
    ``deficit_atuarial`` sao subtraidos; ``caixa``, ``aplicacoes_financeiras`` e
    ``ativos_nao_operacionais`` sao somados. Informe todos como valores
    positivos.
    """

    divida_bruta: float = 0.0
    caixa: float = 0.0
    aplicacoes_financeiras: float = 0.0
    minoritarios: float = 0.0
    contingencias: float = 0.0
    deficit_atuarial: float = 0.0
    ativos_nao_operacionais: float = 0.0
    acoes_em_circulacao: float | None = None

    @property
    def divida_liquida(self) -> float:
        return self.divida_bruta - self.caixa - self.aplicacoes_financeiras


@dataclass(frozen=True)
class Empresa:
    """Agrupa tudo que descreve uma avaliacao de uma empresa."""

    nome: str
    macro: PremissasMacro = field(default_factory=PremissasMacro)
    custo_capital: PremissasCustoCapital = field(default_factory=PremissasCustoCapital)
    operacionais: PremissasOperacionais | None = None
    perpetuidade: PremissasPerpetuidade = field(default_factory=PremissasPerpetuidade)
    ponte: PonteValor = field(default_factory=PonteValor)
    data_base: str = ""
    moeda: str = "BRL"
    unidade: str = "R$ milhoes"
