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

from dataclasses import dataclass, field, replace

# Aliquota combinada IRPJ (15% + adicional de 10%) + CSLL (9%) do lucro real.
ALIQUOTA_IR_BRASIL = 0.34

# Como o crescimento perpetuo e determinado. Ver PremissasPerpetuidade.ancora.
ANCORAS_PERPETUIDADE = ("livre", "ipca", "pib_nominal")

# Sobre que conta o multiplo de saida incide, e como ele se chama na tela. A
# chave e a conta do ultimo ano projetado; o rotulo e o nome do multiplo, que e
# o que o analista digita.
BASES_DO_MULTIPLO = {"ebitda": "EV/EBITDA", "lucro": "P/L"}

# Por onde o Ke e montado. Ver ``PremissasCustoCapital.metodo``.
# Os rotulos vao para a tela, entao levam acento -- e a regra do projeto para
# texto de usuario, e estes sao os dois botoes que o analista le antes de
# escolher por onde o Ke e montado.
METODOS_DE_CUSTO_DE_CAPITAL = {
    "usd": "Dólar + risco-país",
    "local": "NTN-B + prêmio local",
}


@dataclass(frozen=True)
class PremissasMacro:
    """Premissas de mercado que independem da empresa avaliada.

    ``inflacao_brl`` e ``inflacao_usd`` sao as inflacoes de longo prazo usadas
    para converter um custo de capital estimado em USD nominal para BRL
    nominal (paridade de poder de compra).

    ``pib_real`` e o crescimento real da economia no longo prazo. **Ele nao
    entra no custo de capital**: serve para compor o crescimento nominal da
    economia, que e o teto natural do crescimento perpetuo e uma das ancoras
    possiveis para ele.
    """

    inflacao_brl: float = 0.04
    inflacao_usd: float = 0.023
    aliquota_ir: float = ALIQUOTA_IR_BRASIL
    pib_real: float = 0.015

    def __post_init__(self) -> None:
        for nome in ("inflacao_brl", "inflacao_usd", "aliquota_ir", "pib_real"):
            valor = getattr(self, nome)
            if not -1 < valor < 1:
                raise ValueError(
                    f"{nome}={valor!r} fora do intervalo esperado. "
                    "Use decimais (0.34 para 34%), nao percentuais."
                )

    @property
    def pib_nominal(self) -> float:
        """Crescimento nominal da economia, com os dois termos compostos.

        Somar inflacao e PIB real (``0.05 + 0.015``) subestima: quem cresce 1,5%
        real cresce sobre precos ja reajustados. A diferenca e pequena, mas esta
        no teto de uma perpetuidade -- o lugar do modelo onde um erro pequeno
        nao fica pequeno.
        """
        return (1 + self.inflacao_brl) * (1 + self.pib_real) - 1


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

    # **Por onde o Ke e montado.** Sao duas construcoes legitimas, e elas nao se
    # misturam:
    #
    # ``"usd"``   -- rf americano + beta x ERP maduro + lambda x risco-pais, e o
    #                resultado convertido para BRL por diferencial de inflacao.
    #                Evita somar premio americano a taxa brasileira.
    # ``"local"`` -- rf **brasileiro** (NTN-B real, nominalizada pelo IPCA) +
    #                beta x ERP local. Aqui **nao entra risco-pais**: ele ja esta
    #                dentro do rf, e soma-lo seria conta-lo duas vezes.
    #
    # O custo do caminho local esta no ERP: um premio de risco de acoes estimado
    # na serie brasileira e ruidoso demais para ser observado, entao ``erp_local``
    # e uma premissa do analista -- e a que mais move o Ke.
    metodo: str = "usd"
    rf_usd: float = 0.045
    erp_maduro: float = 0.045
    risco_pais: float = 0.025
    # Usados so quando ``metodo == "local"``.
    rf_brl: float | None = None
    erp_local: float = 0.075
    beta_alavancado_setor: float | None = 1.0
    beta_desalavancado: float | None = None
    divida_pl_setor: float = 0.0
    divida_pl_alvo: float = 0.0
    lambda_pais: float = 1.0
    premio_tamanho: float = 0.0
    custo_divida_brl: float | None = None
    spread_credito: float = 0.03
    # Instituicao financeira **nao tem o beta realavancado**, e nao e detalhe.
    # Hamada supoe que a divida e escolha de financiamento que acrescenta risco
    # ao acionista; num banco o deposito e a **materia-prima**, e o risco dele ja
    # esta dentro do beta observado do equity. Medido nas 18 instituicoes com
    # balanco legivel em 2024: o passivo de terceiros e **11,2x o patrimonio na
    # mediana**, e realavancar um beta de 0,95 por esse D/E daria beta 8,0 e Ke de
    # **41% em dolar**. Banco nenhum tem isso -- os betas observados ficam perto
    # de 1. Com esta marca ligada, o beta informado entra como **ja alavancado**.
    instituicao_financeira: bool = False

    def __post_init__(self) -> None:
        if self.metodo not in METODOS_DE_CUSTO_DE_CAPITAL:
            raise ValueError(
                f"metodo de custo de capital desconhecido: {self.metodo!r}. "
                f"Use um de {list(METODOS_DE_CUSTO_DE_CAPITAL)}."
            )
        if self.metodo == "local" and self.rf_brl is None:
            raise ValueError(
                "metodo 'local' exige rf_brl -- a taxa livre de risco em reais, "
                "que sai da NTN-B nominalizada pela inflacao."
            )
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
    # Saldo do passivo de arrendamento como percentual da receita. Opcional, e
    # nasce desligado: quem nao informa continua com a projecao de antes.
    #
    # Existe porque contrato novo de aluguel **nao passa pelo capex**. Assinar um
    # ponto cria ativo de direito de uso e passivo de arrendamento sem tocar o
    # fluxo de investimento: numa rede que abre lojas, o EBITDA sobe, o capex
    # fica parado, o FCFF sai generoso -- e a divida cresce todo ano sem que a
    # ponte, congelada na data-base, saiba. Informado aqui, o crescimento do
    # passivo vira saida de caixa, como a variacao do capital de giro.
    arrendamento_pct_receita: list[float] | None = None
    arrendamento_inicial: float | None = None

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
        if self.arrendamento_pct_receita is not None:
            tamanhos["arrendamento_pct_receita"] = len(self.arrendamento_pct_receita)
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

    ``ancora`` diz **de onde vem** o ``g``:

    * ``"livre"``: e um numero informado, e ninguem o move sozinho.
    * ``"ipca"``: ``g`` = inflacao de longo prazo. Diz que a empresa cresce com
      os precos e nao ganha nem perde participacao na economia real.
    * ``"pib_nominal"``: ``g`` = crescimento nominal da economia. E o teto
      logico -- acima dele a empresa acabaria maior que o pais.

    Ancorado, ``crescimento_perpetuo`` deixa de ser entrada e passa a ser
    derivado: quem resolve e ``Empresa``, que e quem tem a macro na mao.

    ``roic_real`` existe pelo mesmo motivo, do outro lado da conta. O ROIC do
    denominador de ``g / ROIC`` e nominal: e retorno nominal sobre capital
    nominal. Se o ``g`` esta ancorado na macro e sobe com a inflacao enquanto o
    ROIC fica parado, a taxa de reinvestimento sobe sozinha e o modelo cobra
    capital que a inflacao nao pediu -- medido, ``g/ROIC`` saltava de 37% para
    51% do NOPAT com dois pontos de IPCA. Informando ``roic_real``, o nominal
    passa a ser derivado::

        roic_perpetuidade = (1 + roic_real) x (1 + inflacao_brl) - 1

    Repare no que isso **nao** faz: a taxa de reinvestimento continua subindo
    com a inflacao, so que menos (44% em vez de 51%, no mesmo caso). Isso esta
    certo. Sustentar o mesmo crescimento real custa mais reais nominais quando
    os precos correm mais rapido; o que estava errado era o tamanho, nao o
    sinal.
    """

    metodo: str = "gordon"
    crescimento_perpetuo: float = 0.04
    roic_perpetuidade: float | None = None
    # O ROE de perpetuidade, para quando o fluxo descontado e o **do acionista**.
    # A normalizacao do reinvestimento precisa do retorno sobre o capital que o
    # fluxo remunera: ROIC para o FCFF, ROE para o FCFE. Ver
    # ``dcf._normalizacao_do_gordon``.
    roe_perpetuidade: float | None = None
    multiplo_saida: float | None = None
    # Sobre que conta o multiplo de saida incide. Depende do caso: uma industria
    # sai por EV/EBITDA, uma financeira ou uma empresa cujo par negocia por lucro
    # sai por P/L. **A escolha muda a moeda do valor terminal** -- EV/EBITDA da
    # valor de firma, P/L da valor de equity --, e e por isso que ela e premissa
    # e nao detalhe de apresentacao. Ver ``dcf._terminal_na_moeda_do_fluxo``.
    base_do_multiplo: str = "ebitda"
    ancora: str = "livre"
    roic_real: float | None = None

    def __post_init__(self) -> None:
        if self.metodo not in ("gordon", "multiplo"):
            raise ValueError(f"metodo de perpetuidade desconhecido: {self.metodo!r}")
        if self.metodo == "multiplo" and self.multiplo_saida is None:
            raise ValueError("metodo 'multiplo' exige multiplo_saida.")
        if self.base_do_multiplo not in BASES_DO_MULTIPLO:
            raise ValueError(
                f"base_do_multiplo desconhecida: {self.base_do_multiplo!r}. "
                f"Use uma de {list(BASES_DO_MULTIPLO)}."
            )
        if self.roic_perpetuidade is not None and self.roic_perpetuidade <= 0:
            raise ValueError("roic_perpetuidade deve ser positivo.")
        if self.roe_perpetuidade is not None and self.roe_perpetuidade <= 0:
            raise ValueError("roe_perpetuidade deve ser positivo.")
        if self.roic_real is not None and self.roic_real <= 0:
            raise ValueError("roic_real deve ser positivo.")
        if self.ancora not in ANCORAS_PERPETUIDADE:
            raise ValueError(
                f"ancora de perpetuidade desconhecida: {self.ancora!r}. "
                f"Use uma de {list(ANCORAS_PERPETUIDADE)}."
            )

    def crescimento_ancorado(self, macro: PremissasMacro) -> float | None:
        """O ``g`` que a ancora impoe, ou ``None`` quando o ``g`` e livre."""
        if self.ancora == "ipca":
            return macro.inflacao_brl
        if self.ancora == "pib_nominal":
            return macro.pib_nominal
        return None

    def roic_indexado(self, macro: PremissasMacro) -> float | None:
        """O ROIC nominal que ``roic_real`` implica, ou ``None`` se nao ha."""
        if self.roic_real is None:
            return None
        return (1 + self.roic_real) * (1 + macro.inflacao_brl) - 1


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
    """Agrupa tudo que descreve uma avaliacao de uma empresa.

    E aqui que a ancora da perpetuidade se resolve, porque e aqui que a macro e
    a perpetuidade se encontram. Se ``perpetuidade.ancora`` nao for ``"livre"``,
    ``crescimento_perpetuo`` e reescrito a partir da macro na construcao.

    A alternativa seria calcular o ``g`` na hora do desconto e deixar o campo
    guardado com um valor velho. Nao vale: o campo aparece no resumo, no
    diagnostico, na exportacao e na tela. Um so lugar que lesse o valor guardado
    em vez do efetivo ja seria um numero errado na frente do usuario, e a tela e
    onde ele confere.
    """

    nome: str
    macro: PremissasMacro = field(default_factory=PremissasMacro)
    custo_capital: PremissasCustoCapital = field(default_factory=PremissasCustoCapital)
    operacionais: PremissasOperacionais | None = None
    perpetuidade: PremissasPerpetuidade = field(default_factory=PremissasPerpetuidade)
    ponte: PonteValor = field(default_factory=PonteValor)
    prejuizo_fiscal_acumulado: float = 0.0
    data_base: str = ""
    moeda: str = "BRL"
    unidade: str = "R$ milhoes"

    def __post_init__(self) -> None:
        perp = self.perpetuidade
        derivados = {}

        ancorado = perp.crescimento_ancorado(self.macro)
        if ancorado is not None and ancorado != perp.crescimento_perpetuo:
            derivados["crescimento_perpetuo"] = ancorado

        indexado = perp.roic_indexado(self.macro)
        if indexado is not None and indexado != perp.roic_perpetuidade:
            derivados["roic_perpetuidade"] = indexado

        if derivados:
            object.__setattr__(self, "perpetuidade", replace(perp, **derivados))
