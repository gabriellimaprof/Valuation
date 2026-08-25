"""Vocabulario canonico das demonstracoes financeiras e regras de reconhecimento.

Todo importador -- template proprio, export da CVM/B3 ou de terminal -- converte
para o mesmo conjunto de contas canonicas definido aqui. O resto do projeto so
conhece esses nomes, entao adicionar uma nova origem de dados significa escrever
um reconhecedor novo, nunca mexer no motor de valuation.

Cada conta declara:

* os **sinonimos** usados por planilhas em portugues e ingles, ja normalizados
  (sem acento, minusculas) na hora da comparacao;
* o **codigo CVM** do plano de contas padronizado, quando existe;
* se e **obrigatoria** para o modelo funcionar;
* como pode ser **derivada** de outras contas, quando nao vier explicita.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Conta:
    """Uma linha canonica de demonstracao financeira."""

    chave: str
    rotulo: str
    demonstracao: str  # "dre", "bp" ou "dfc"
    sinonimos: tuple[str, ...] = ()
    codigos_cvm: tuple[str, ...] = ()
    obrigatoria: bool = False
    sinal_invertido: bool = False
    ajuda: str = ""
    # Onde a conta aparece quando a demonstracao e exibida inteira. Vazio usa o
    # primeiro codigo CVM, que ja ordena naturalmente (3.01 antes de 3.04.01
    # antes de 3.05). So as contas sem codigo -- capex, juros pagos, D&A --
    # precisam declarar, para nao caírem no fim da tabela longe do seu bloco.
    ordem: str = ""

    @property
    def posicao(self) -> tuple[int, ...]:
        """Chave de ordenacao pela posicao no plano de contas."""
        referencia = self.ordem or (self.codigos_cvm[0] if self.codigos_cvm else "")
        if not referencia:
            return (99,)
        return tuple(int(p) for p in referencia.split("."))


# ---------------------------------------------------------------------------
# Demonstracao do resultado
# ---------------------------------------------------------------------------

CONTAS_DRE: tuple[Conta, ...] = (
    Conta(
        chave="receita_liquida",
        rotulo="Receita liquida",
        demonstracao="dre",
        sinonimos=(
            "receita liquida",
            "receita liquida de vendas",
            "receita de venda de bens e/ou servicos",
            # Plano financeiro: para um banco a receita e o que ele cobra
            # para emprestar. Sao 17 companhias que escrevem assim.
            "receitas de intermediacao financeira",
            "receitas da intermediacao financeira",
            "receita operacional liquida",
            "vendas liquidas",
            "receita liquida de vendas e servicos",
            "net revenue",
            "net sales",
            "revenue",
            "total revenue",
            "sales",
        ),
        codigos_cvm=("3.01",),
        obrigatoria=True,
        ajuda="Ponto de partida de todo o modelo: e sobre ela que as margens sao aplicadas.",
    ),
    Conta(
        chave="custo_produtos_vendidos",
        rotulo="Custo dos produtos e servicos (CPV/CSV)",
        demonstracao="dre",
        sinonimos=(
            "custo dos bens e/ou servicos vendidos",
            "despesas de intermediacao financeira",
            "despesas da intermediacao financeira",
            "custo dos produtos vendidos",
            "custo das mercadorias vendidas",
            "custo dos servicos prestados",
            "cpv",
            "cmv",
            "cost of goods sold",
            "cogs",
            "cost of revenue",
            "cost of sales",
        ),
        codigos_cvm=("3.02",),
        sinal_invertido=True,
        ajuda="Custo direto de produzir o que foi vendido. Receita menos CPV e o lucro bruto.",
    ),
    Conta(
        chave="lucro_bruto",
        rotulo="Lucro bruto",
        demonstracao="dre",
        sinonimos=("resultado bruto",
            "resultado bruto de intermediacao financeira",
            "resultado bruto intermediacao financeira", "lucro bruto", "gross profit"),
        codigos_cvm=("3.03",),
        ajuda="Mede o quanto sobra da venda antes das despesas de estrutura.",
    ),
    Conta(
        chave="despesas_operacionais",
        rotulo="Despesas operacionais (SG&A)",
        demonstracao="dre",
        sinonimos=(
            "despesas/receitas operacionais",
            "despesas operacionais",
            "despesas com vendas gerais e administrativas",
            "despesas gerais e administrativas",
            "sg&a",
            "operating expenses",
            "selling general and administrative",
        ),
        codigos_cvm=("3.04",),
        sinal_invertido=True,
        ajuda="Despesas de vender e administrar, que nao variam diretamente com o volume.",
    ),
    Conta(
        chave="depreciacao_amortizacao",
        rotulo="Depreciacao e amortizacao",
        demonstracao="dre",
        sinonimos=(
            "depreciacao e amortizacao",
            "depreciacao amortizacao e exaustao",
            "depreciacao",
            "amortizacao",
            "d&a",
            "depreciation and amortization",
            "depreciation amortization",
            "depreciation",
        ),
        ajuda=(
            "Despesa sem saida de caixa. E o que separa o EBITDA do EBIT, e volta ao "
            "fluxo de caixa depois de calculado o imposto."
        ),
        # D&A e magnitude: ``EBITDA = EBIT + D&A`` nao admite valor negativo, que
        # faria o EBITDA ficar **abaixo** do EBIT. Auditada a base de 2024, 43
        # companhias industriais publicavam a linha com sinal invertido -- Casas
        # Bahia com -R$ 864 mi --, e o app repassava.
        sinal_invertido=True,
        ordem="3.04.90",  # dentro das operacionais, logo antes do EBIT
    ),
    Conta(
        chave="ebit",
        rotulo="EBIT (resultado operacional)",
        demonstracao="dre",
        sinonimos=(
            "resultado antes do resultado financeiro e dos tributos",
            "resultado operacional",
            "lucro operacional",
            "ebit",
            "operating income",
            "operating profit",
            "earnings before interest and taxes",
        ),
        codigos_cvm=("3.05",),
        obrigatoria=True,
        ajuda="Lucro da operacao, antes de juros e impostos. Base do NOPAT e do FCFF.",
    ),
    Conta(
        chave="resultado_financeiro",
        rotulo="Resultado financeiro",
        demonstracao="dre",
        sinonimos=(
            "resultado financeiro",
            "resultado financeiro liquido",
            "net financial result",
            "net interest expense",
        ),
        codigos_cvm=("3.06",),
        ajuda="Receitas menos despesas financeiras. Nao entra no FCFF, que e desalavancado.",
    ),
    Conta(
        chave="despesas_financeiras",
        rotulo="Despesas financeiras (juros)",
        demonstracao="dre",
        sinonimos=(
            "despesas financeiras",
            "juros sobre emprestimos",
            "interest expense",
            "financial expenses",
        ),
        codigos_cvm=("3.06.02",),
        sinal_invertido=True,
        ajuda="Serve para estimar o custo da divida efetivo: juros sobre divida bruta media.",
    ),
    Conta(
        chave="lucro_antes_impostos",
        rotulo="Lucro antes dos impostos (LAIR)",
        demonstracao="dre",
        sinonimos=(
            "resultado antes dos tributos sobre o lucro",
            "lucro antes do imposto de renda",
            "lair",
            "ebt",
            "pretax income",
            "income before taxes",
        ),
        codigos_cvm=("3.07",),
    ),
    Conta(
        chave="impostos",
        rotulo="IR e CSLL",
        demonstracao="dre",
        sinonimos=(
            "imposto de renda e contribuicao social sobre o lucro",
            "imposto de renda e contribuicao social",
            "ir e csll",
            "provisao para ir e csll",
            "income tax expense",
            "income taxes",
            "taxes",
        ),
        codigos_cvm=("3.08",),
        sinal_invertido=True,
        ajuda="Usado para calcular a aliquota efetiva historica, que costuma diferir dos 34% nominais.",
    ),
    Conta(
        chave="lucro_liquido",
        rotulo="Lucro liquido",
        demonstracao="dre",
        sinonimos=(
            "lucro/prejuizo consolidado do periodo",
            "lucro ou prejuizo liquido consolidado do periodo",
            "lucro/prejuizo do periodo",
            "lucro liquido do periodo",
            "lucro liquido",
            "resultado liquido",
            "net income",
            "net profit",
            "net earnings",
        ),
        codigos_cvm=("3.11", "3.09"),
        obrigatoria=True,
        ajuda="Resultado que sobra para o acionista. Base do ROE e do P/L.",
    ),
    # --- abertura das linhas acima, para leitura da DRE -------------------
    Conta(
        chave="despesas_vendas",
        rotulo="Despesas com vendas",
        demonstracao="dre",
        sinonimos=("despesas com vendas", "despesas comerciais", "selling expenses"),
        codigos_cvm=("3.04.01",),
        sinal_invertido=True,
        ajuda="Parte do SG&A que acompanha o volume vendido mais de perto.",
    ),
    Conta(
        chave="despesas_administrativas",
        rotulo="Despesas gerais e administrativas",
        demonstracao="dre",
        sinonimos=(
            "despesas gerais e administrativas",
            "despesas administrativas",
            "general and administrative expenses",
        ),
        codigos_cvm=("3.04.02",),
        sinal_invertido=True,
        ajuda="A parcela mais fixa da estrutura: nao cai junto com a receita.",
    ),
    # As tres contas abaixo guardam o **sinal publicado**, e nao a magnitude.
    # Elas existem para uma conta de subtracao -- ``EBIT recorrente = EBIT menos
    # o que nao se repete`` -- e nessa conta o sinal e a informacao: reversao de
    # impairment entra positiva e perda entra negativa. Padronizar para
    # magnitude aqui inverteria metade dos casos sem que nada acusasse.
    Conta(
        chave="impairment",
        rotulo="Perdas por nao recuperabilidade de ativos (impairment)",
        demonstracao="dre",
        # Sem sinonimos, de proposito: o codigo e fixo (ST_CONTA_FIXA) e casa em
        # 1,0. O rotulo so criaria ambiguidade -- medido, 10 companhias publicam
        # "Outras Receitas Operacionais" no slot 3.04.06, que e da equivalencia.
        sinonimos=(),
        codigos_cvm=("3.04.03",),
        ordem="3.04.03",
        ajuda=(
            "Baixa (ou reversao) contabil do valor de um ativo. Nao e caixa e nao "
            "se repete: 94 companhias reconheceram em 2024, somando R$ 167 bilhoes."
        ),
    ),
    Conta(
        chave="outras_receitas_operacionais",
        rotulo="Outras receitas operacionais",
        demonstracao="dre",
        sinonimos=(),
        codigos_cvm=("3.04.04",),
        ordem="3.04.04",
        ajuda=(
            "Onde moram ganho de venda de ativo, credito tributario e ganho "
            "judicial. Parte e recorrente e parte nao -- por isso aparece "
            "separada, em vez de somada ao resultado sem aviso."
        ),
    ),
    Conta(
        chave="outras_despesas_operacionais",
        rotulo="Outras despesas operacionais",
        demonstracao="dre",
        sinonimos=(),
        codigos_cvm=("3.04.05",),
        ordem="3.04.05",
        ajuda="A contrapartida das outras receitas: perdas e provisoes fora da operacao.",
    ),
    Conta(
        chave="equivalencia_patrimonial",
        rotulo="Resultado de equivalencia patrimonial",
        demonstracao="dre",
        sinonimos=(
            "resultado de equivalencia patrimonial",
            "equivalencia patrimonial",
            "equity in earnings of affiliates",
        ),
        codigos_cvm=("3.04.06",),
        ajuda=(
            "Resultado de coligadas que nao entram no consolidado. Nao gera caixa "
            "na controladora, entao inflar o EBIT com ele distorce o multiplo."
        ),
    ),
    Conta(
        chave="receitas_financeiras",
        rotulo="Receitas financeiras",
        demonstracao="dre",
        sinonimos=("receitas financeiras", "receita financeira", "financial income"),
        codigos_cvm=("3.06.01",),
        ajuda="Rendimento do caixa aplicado. Separada das despesas, mostra o custo bruto da divida.",
    ),
    Conta(
        chave="imposto_corrente",
        rotulo="IR e CSLL correntes",
        demonstracao="dre",
        sinonimos=("corrente", "imposto corrente", "current income tax"),
        codigos_cvm=("3.08.01",),
        # **Sinal publicado**, e nao magnitude. O corrente e o diferido sao as
        # duas metades do 3.08 e cada uma pode ser despesa ou credito: na WEG de
        # 2023 o diferido foi credito de R$ 404,8 mi, e somar as duas como
        # magnitude dava R$ 1.532,7 mi contra os R$ 723,2 mi publicados. A ponte
        # da DRE nao fechava, e nada mais acusava.
        ajuda="A parcela do imposto que vira caixa no ano; o diferido nao.",
    ),
    Conta(
        chave="imposto_diferido",
        rotulo="IR e CSLL diferidos",
        demonstracao="dre",
        sinonimos=("diferido", "imposto diferido", "deferred income tax"),
        codigos_cvm=("3.08.02",),
        ajuda="Pode inverter de sinal entre anos; nao e saida de caixa.",
    ),
    Conta(
        chave="operacoes_descontinuadas",
        rotulo="Resultado de operacoes descontinuadas",
        demonstracao="dre",
        sinonimos=(
            "resultado liquido de operacoes descontinuadas",
            "operacoes descontinuadas",
            "discontinued operations",
        ),
        codigos_cvm=("3.10",),
        ajuda=(
            "Nao se projeta: e resultado de negocio que a empresa esta deixando. "
            "Precisa sair da base antes de estimar crescimento."
        ),
    ),
    Conta(
        chave="lucro_controladores",
        rotulo="Lucro atribuido aos controladores",
        demonstracao="dre",
        sinonimos=(
            "atribuido a socios da empresa controladora",
            "atribuido aos socios da empresa controladora",
            "lucro atribuido aos controladores",
        ),
        codigos_cvm=("3.11.01",),
        ajuda=(
            "E este, e nao o lucro consolidado, que pertence ao acionista da "
            "holding -- o denominador certo do LPA e do P/L."
        ),
    ),
    Conta(
        chave="lucro_nao_controladores",
        rotulo="Lucro atribuido aos nao controladores",
        demonstracao="dre",
        sinonimos=(
            "atribuido a socios nao controladores",
            "atribuido aos socios nao controladores",
            "minority interest in earnings",
        ),
        codigos_cvm=("3.11.02",),
    ),
)


# ---------------------------------------------------------------------------
# Balanco patrimonial
# ---------------------------------------------------------------------------

CONTAS_BP: tuple[Conta, ...] = (
    Conta(
        chave="caixa_equivalentes",
        rotulo="Caixa e equivalentes de caixa",
        demonstracao="bp",
        sinonimos=(
            "caixa e equivalentes de caixa",
            "caixa e equivalentes",
            "disponibilidades",
            "cash and cash equivalents",
            "cash",
        ),
        codigos_cvm=("1.01.01",),
        obrigatoria=True,
        ajuda="Entra na ponte EV -> equity somando ao valor do acionista.",
    ),
    Conta(
        chave="aplicacoes_financeiras",
        rotulo="Aplicacoes financeiras",
        demonstracao="bp",
        sinonimos=(
            "aplicacoes financeiras",
            "titulos e valores mobiliarios",
            "short term investments",
            "marketable securities",
        ),
        codigos_cvm=("1.01.02",),
    ),
    Conta(
        chave="contas_receber",
        rotulo="Contas a receber",
        demonstracao="bp",
        sinonimos=(
            "contas a receber",
            "clientes",
            "contas a receber de clientes",
            "accounts receivable",
            "trade receivables",
            "receivables",
        ),
        codigos_cvm=("1.01.03",),
        ajuda="Componente do capital de giro: quanto a empresa financia os clientes.",
    ),
    Conta(
        chave="estoques",
        rotulo="Estoques",
        demonstracao="bp",
        sinonimos=("estoques", "inventarios", "inventory", "inventories"),
        codigos_cvm=("1.01.04",),
        ajuda="Componente do capital de giro: capital parado em mercadoria.",
    ),
    Conta(
        chave="ativo_circulante",
        rotulo="Ativo circulante",
        demonstracao="bp",
        sinonimos=("ativo circulante", "total current assets", "current assets"),
        codigos_cvm=("1.01",),
    ),
    Conta(
        chave="imobilizado",
        rotulo="Imobilizado",
        demonstracao="bp",
        sinonimos=(
            "imobilizado",
            "ativo imobilizado",
            "property plant and equipment",
            "ppe",
            "net ppe",
        ),
        codigos_cvm=("1.02.03",),
        ajuda="Base do capital investido e referencia para saber se o capex repoe o ativo.",
    ),
    Conta(
        chave="intangivel",
        rotulo="Intangivel",
        demonstracao="bp",
        sinonimos=("intangivel", "ativo intangivel", "agio", "goodwill", "intangible assets"),
        codigos_cvm=("1.02.04",),
    ),
    Conta(
        chave="ativo_total",
        rotulo="Ativo total",
        demonstracao="bp",
        sinonimos=("ativo total", "total do ativo", "total assets"),
        codigos_cvm=("1",),
        obrigatoria=True,
    ),
    Conta(
        chave="fornecedores",
        rotulo="Fornecedores",
        demonstracao="bp",
        sinonimos=(
            "fornecedores",
            "contas a pagar",
            "accounts payable",
            "trade payables",
            "payables",
        ),
        codigos_cvm=("2.01.02",),
        ajuda="Componente do capital de giro: quanto os fornecedores financiam a empresa.",
    ),
    Conta(
        chave="divida_curto_prazo",
        rotulo="Emprestimos e financiamentos (curto prazo)",
        demonstracao="bp",
        sinonimos=(
            "emprestimos e financiamentos",
            "emprestimos e financiamentos circulante",
            "divida de curto prazo",
            "short term debt",
            "current portion of long term debt",
        ),
        codigos_cvm=("2.01.04",),
        ajuda="Somada a divida de longo prazo forma a divida bruta da ponte.",
    ),
    Conta(
        chave="passivo_circulante",
        rotulo="Passivo circulante",
        demonstracao="bp",
        sinonimos=("passivo circulante", "total current liabilities", "current liabilities"),
        codigos_cvm=("2.01",),
    ),
    Conta(
        chave="divida_longo_prazo",
        rotulo="Emprestimos e financiamentos (longo prazo)",
        demonstracao="bp",
        sinonimos=(
            "emprestimos e financiamentos nao circulante",
            "divida de longo prazo",
            "long term debt",
            "non current debt",
        ),
        codigos_cvm=("2.02.01",),
    ),
    Conta(
        chave="passivo_total",
        rotulo="Passivo total",
        demonstracao="bp",
        sinonimos=(
            "passivo total",
            "total do passivo",
            "passivo e patrimonio liquido",
            "total liabilities and equity",
        ),
        codigos_cvm=("2",),
        ajuda="Serve para conferir a identidade do balanco: ativo total = passivo total.",
    ),
    Conta(
        chave="minoritarios",
        rotulo="Participacao de nao controladores",
        demonstracao="bp",
        sinonimos=(
            "participacao dos acionistas nao controladores",
            "participacao de nao controladores",
            "minoritarios",
            "minority interest",
            "non controlling interests",
        ),
        codigos_cvm=("2.03.09",),
        ajuda="Subtraida na ponte: essa parcela do equity nao pertence ao controlador.",
    ),
    Conta(
        chave="patrimonio_liquido",
        rotulo="Patrimonio liquido",
        demonstracao="bp",
        sinonimos=(
            "patrimonio liquido consolidado",
            "patrimonio liquido",
            "total shareholders equity",
            "shareholders equity",
            "total equity",
        ),
        codigos_cvm=("2.03",),
        obrigatoria=True,
        ajuda="Base do ROE, do P/VPA e do capital investido.",
    ),
    # --- abertura do ativo -------------------------------------------------
    Conta(
        chave="tributos_recuperar",
        rotulo="Tributos a recuperar",
        demonstracao="bp",
        sinonimos=("tributos a recuperar", "impostos a recuperar", "tributos correntes a recuperar"),
        codigos_cvm=("1.01.06",),
    ),
    Conta(
        chave="despesas_antecipadas",
        rotulo="Despesas antecipadas",
        demonstracao="bp",
        sinonimos=("despesas antecipadas", "prepaid expenses"),
        codigos_cvm=("1.01.07",),
    ),
    Conta(
        chave="outros_ativos_circulantes",
        rotulo="Outros ativos circulantes",
        demonstracao="bp",
        sinonimos=("outros ativos circulantes",),
        codigos_cvm=("1.01.08",),
    ),
    Conta(
        chave="ativo_nao_circulante",
        rotulo="Ativo nao circulante",
        demonstracao="bp",
        sinonimos=("ativo nao circulante", "total non current assets"),
        codigos_cvm=("1.02",),
    ),
    Conta(
        chave="realizavel_longo_prazo",
        rotulo="Ativo realizavel a longo prazo",
        demonstracao="bp",
        sinonimos=("ativo realizavel a longo prazo", "realizavel a longo prazo"),
        codigos_cvm=("1.02.01",),
    ),
    Conta(
        chave="investimentos",
        rotulo="Investimentos (participacoes societarias)",
        demonstracao="bp",
        sinonimos=("participacoes societarias", "investimentos em coligadas"),
        codigos_cvm=("1.02.02",),
        ajuda=(
            "Coligadas nao consolidadas. Andam junto com a equivalencia "
            "patrimonial na DRE e ficam fora do capital operacional."
        ),
    ),
    Conta(
        chave="direito_uso_arrendamento",
        rotulo="Direito de uso em arrendamento",
        demonstracao="bp",
        sinonimos=(
            "direito de uso em arrendamento",
            "direito de uso",
            "right of use asset",
        ),
        codigos_cvm=("1.02.03.02",),
        ajuda=(
            "O ativo que o IFRS 16 criou. Ja esta dentro do imobilizado; "
            "aparece separado porque tem o passivo de arrendamento do outro lado."
        ),
    ),
    Conta(
        chave="goodwill",
        rotulo="Agio por expectativa de rentabilidade (goodwill)",
        demonstracao="bp",
        sinonimos=("goodwill", "agio por expectativa de rentabilidade futura"),
        codigos_cvm=("1.02.04.02",),
        ajuda="Ja esta dentro do intangivel. Nao repoe capex e nao gera caixa proprio.",
    ),
    # --- abertura do passivo ----------------------------------------------
    Conta(
        chave="obrigacoes_sociais_trabalhistas",
        rotulo="Obrigacoes sociais e trabalhistas",
        demonstracao="bp",
        sinonimos=("obrigacoes sociais e trabalhistas", "obrigacoes trabalhistas"),
        codigos_cvm=("2.01.01",),
    ),
    Conta(
        chave="obrigacoes_fiscais",
        rotulo="Obrigacoes fiscais",
        demonstracao="bp",
        sinonimos=("obrigacoes fiscais", "obrigacoes fiscais federais"),
        codigos_cvm=("2.01.03",),
    ),
    Conta(
        chave="debentures_curto_prazo",
        rotulo="Debentures (curto prazo)",
        demonstracao="bp",
        sinonimos=("debentures",),
        codigos_cvm=("2.01.04.02",),
        ajuda="Ja somada em emprestimos e financiamentos; separada so para leitura.",
    ),
    Conta(
        chave="arrendamento_curto_prazo",
        rotulo="Arrendamento a pagar (curto prazo)",
        demonstracao="bp",
        sinonimos=(
            "financiamento por arrendamento",
            "arrendamento a pagar",
            "passivo de arrendamento",
            "lease liabilities",
        ),
        codigos_cvm=("2.01.04.03",),
        ajuda=(
            "Divida de aluguel trazida ao balanco pelo IFRS 16. Ja esta dentro de "
            "emprestimos e financiamentos: some as duas e voce conta duas vezes."
        ),
    ),
    Conta(
        chave="provisoes_circulante",
        rotulo="Provisoes (curto prazo)",
        demonstracao="bp",
        sinonimos=("provisoes fiscais previdenciarias trabalhistas e civeis",),
        codigos_cvm=("2.01.06",),
    ),
    Conta(
        chave="passivo_nao_circulante",
        rotulo="Passivo nao circulante",
        demonstracao="bp",
        sinonimos=("passivo nao circulante", "total non current liabilities"),
        codigos_cvm=("2.02",),
    ),
    Conta(
        chave="debentures_longo_prazo",
        rotulo="Debentures (longo prazo)",
        demonstracao="bp",
        codigos_cvm=("2.02.01.02",),
        ajuda="Ja somada em emprestimos e financiamentos de longo prazo.",
    ),
    Conta(
        chave="arrendamento_longo_prazo",
        rotulo="Arrendamento a pagar (longo prazo)",
        demonstracao="bp",
        codigos_cvm=("2.02.01.03",),
        ajuda=(
            "A parcela longa do passivo de arrendamento. Ja esta dentro da divida "
            "de longo prazo; some separado so se tiver tirado de la antes."
        ),
    ),
    Conta(
        chave="tributos_diferidos_passivo",
        rotulo="Tributos diferidos (passivo)",
        demonstracao="bp",
        sinonimos=("imposto de renda e contribuicao social diferidos",),
        codigos_cvm=("2.02.03",),
    ),
    Conta(
        chave="provisoes_nao_circulante",
        rotulo="Provisoes (longo prazo)",
        demonstracao="bp",
        codigos_cvm=("2.02.04",),
        ajuda="Base para as contingencias que entram na ponte de valor.",
    ),
    Conta(
        chave="capital_social",
        rotulo="Capital social realizado",
        demonstracao="bp",
        sinonimos=("capital social realizado", "capital social", "common stock"),
        codigos_cvm=("2.03.01",),
    ),
    Conta(
        chave="reservas_lucros",
        rotulo="Reservas de lucros",
        demonstracao="bp",
        sinonimos=("reservas de lucros",),
        codigos_cvm=("2.03.04",),
    ),
    Conta(
        chave="lucros_acumulados",
        rotulo="Lucros/prejuizos acumulados",
        demonstracao="bp",
        sinonimos=("lucros/prejuizos acumulados", "retained earnings"),
        codigos_cvm=("2.03.05",),
    ),
)


# ---------------------------------------------------------------------------
# Fluxo de caixa
# ---------------------------------------------------------------------------

CONTAS_DFC: tuple[Conta, ...] = (
    Conta(
        chave="fluxo_operacional",
        rotulo="Caixa gerado pelas operacoes",
        demonstracao="dfc",
        sinonimos=(
            "caixa liquido gerado pelas atividades operacionais",
            "caixa liquido atividades operacionais",
            "fluxo de caixa operacional",
            "cash flow from operations",
            "net cash from operating activities",
            "operating cash flow",
        ),
        codigos_cvm=("6.01",),
    ),
    Conta(
        chave="capex",
        rotulo="Capex (aquisicao de imobilizado e intangivel)",
        demonstracao="dfc",
        sinonimos=(
            "aquisicao de imobilizado",
            "aquisicoes de imobilizado",
            "adicoes ao imobilizado",
            "aquisicao de imobilizado e intangivel",
            "capex",
            "capital expenditures",
            "purchase of property plant and equipment",
            "additions to fixed assets",
        ),
        sinal_invertido=True,
        ajuda=(
            "Investimento em ativo fixo. Comparado a depreciacao, diz se a empresa esta "
            "crescendo, apenas repondo ou encolhendo."
        ),
        ordem="6.02.50",  # dentro da secao de investimento
    ),
    Conta(
        chave="depreciacao_dfc",
        rotulo="Depreciacao e amortizacao (na DFC)",
        demonstracao="dfc",
        sinonimos=(
            "depreciacao e amortizacao",
            "depreciacao amortizacao e exaustao",
            "depreciation and amortization",
        ),
        ajuda="Muitas empresas so divulgam a D&A na DFC, nao na DRE.",
        sinal_invertido=True,
        ordem="6.01.50",  # dentro do operacional, junto dos ajustes
    ),
    Conta(
        chave="outros_operacionais",
        rotulo="Outros movimentos operacionais",
        demonstracao="dfc",
        sinonimos=("outros",),
        codigos_cvm=("6.01.03",),
        ordem="6.01.93",
        ajuda=(
            "A terceira parte do caixa operacional, ao lado da geracao e do "
            "capital de giro. Costuma abrigar juro e imposto pagos. Sem ela a "
            "decomposicao do FCO so fecha em 47% das companhias; com ela, em 97%."
        ),
    ),
    Conta(
        chave="impostos_pagos",
        rotulo="Impostos pagos",
        demonstracao="dfc",
        ordem="6.01.94",
        sinonimos=(
            "imposto de renda e contribuicao social pagos",
            "pagamento de imposto de renda e contribuicao social",
            "impostos pagos",
            "income taxes paid",
        ),
        sinal_invertido=True,
        ajuda=(
            "Imposto efetivamente desembolsado no ano. Fica abaixo da variacao do "
            "capital de giro, e nao dentro dela: pagamento nao e movimento de saldo."
        ),
    ),
    Conta(
        chave="pagamentos_reclassificados_do_giro",
        rotulo="Juros e impostos tirados do capital de giro",
        demonstracao="dfc",
        ordem="6.01.96",
        sinonimos=(),
        ajuda=(
            "Quanto de juro e imposto **pago** a companhia lancou dentro da "
            "variacao de ativos e passivos, e o app moveu para baixo dela. Nao "
            "muda o FCO; muda o que se le como investimento em giro."
        ),
    ),
    Conta(
        chave="outorga_paga",
        rotulo="Outorga de concessao paga",
        demonstracao="dfc",
        ordem="6.02.95",
        sinonimos=(),
        ajuda=(
            "Pagamento ao poder concedente pelo direito de explorar a concessao. "
            "Economicamente e capex, entao sai do operacional e entra no "
            "investimento."
        ),
    ),
    Conta(
        chave="juros_pagos_no_financiamento",
        rotulo="Juros pagos reclassificados para o FCO",
        demonstracao="dfc",
        ordem="6.01.95",
        sinonimos=(),
        ajuda=(
            "Quanto de juro pago a companhia classificou em financiamento e o app "
            "trouxe para o operacional. Existe para que a reclassificacao seja "
            "visivel, e nao um numero que muda sozinho."
        ),
    ),
    Conta(
        chave="arrendamento_principal_pago",
        rotulo="Arrendamento pago (principal)",
        demonstracao="dfc",
        ordem="6.03.90",
        sinonimos=("pagamento de arrendamento", "amortizacao de arrendamento"),
        ajuda=(
            "Saida de caixa do contrato de arrendamento, sem os juros. Somada aos "
            "juros, aproxima o aluguel que existia na DRE antes do IFRS 16."
        ),
    ),
    Conta(
        chave="arrendamento_juros_pagos",
        rotulo="Arrendamento pago (juros)",
        demonstracao="dfc",
        ordem="6.03.91",
        sinonimos=("juros sobre arrendamento", "juros de arrendamento"),
        ajuda=(
            "A parcela de juros do arrendamento. Ja esta dentro de juros pagos; "
            "aparece separada para permitir a leitura ex-IFRS 16."
        ),
    ),
    Conta(
        chave="fluxo_investimento",
        rotulo="Caixa liquido de investimento",
        demonstracao="dfc",
        sinonimos=(
            "caixa liquido atividades de investimento",
            "caixa liquido das atividades de investimento",
            "fluxo de caixa de investimento",
            "cash flow from investing activities",
            "net cash used in investing activities",
        ),
        codigos_cvm=("6.02",),
        ajuda=(
            "Somado ao caixa operacional da o fluxo de caixa livre da empresa. "
            "Serve de conferencia contra o capex informado linha a linha."
        ),
    ),
    Conta(
        chave="fluxo_financiamento",
        rotulo="Caixa liquido de financiamento",
        demonstracao="dfc",
        sinonimos=(
            "caixa liquido atividades de financiamento",
            "caixa liquido das atividades de financiamento",
            "fluxo de caixa de financiamento",
            "cash flow from financing activities",
            "net cash used in financing activities",
        ),
        codigos_cvm=("6.03",),
        ajuda="Mostra quanto a empresa captou ou devolveu a credores e acionistas.",
    ),
    Conta(
        chave="dividendos_pagos",
        rotulo="Dividendos e JCP pagos",
        demonstracao="dfc",
        sinonimos=(
            "dividendos pagos",
            "dividendos e juros sobre capital proprio pagos",
            "dividendos e jcp pagos",
            "pgto de dividendos juros s capital proprio",
            "pagamento de dividendos",
            "pagamento de dividendos e juros sobre capital proprio",
            "juros sobre capital proprio pagos",
            "dividends paid",
        ),
        sinal_invertido=True,
        ajuda=(
            "Entra na decomposicao do retorno do acionista: e a parcela do TSR "
            "que chega como caixa, e nao como valorizacao."
        ),
        ordem="6.03.50",  # dentro da secao de financiamento
    ),
    Conta(
        chave="caixa_das_operacoes",
        rotulo="Caixa gerado nas operacoes (antes do capital de giro)",
        demonstracao="dfc",
        sinonimos=(
            "caixa gerado nas operacoes",
            "caixa gerado pelas operacoes",
            "lucro liquido ajustado",
        ),
        codigos_cvm=("6.01.01",),
        ajuda=(
            "O lucro ja ajustado pelo que nao e caixa, antes de girar o capital "
            "de giro. Separado da variacao, mostra se o caixa veio da operacao "
            "ou de esticar prazo com fornecedor."
        ),
    ),
    Conta(
        chave="variacao_capital_giro",
        rotulo="Variacao nos ativos e passivos (capital de giro)",
        demonstracao="dfc",
        sinonimos=(
            "variacoes nos ativos e passivos",
            "variacao nos ativos e passivos",
            "variacoes patrimoniais",
            "changes in working capital",
        ),
        codigos_cvm=("6.01.02",),
        ajuda=(
            "Quanto de caixa o capital de giro consumiu (negativo) ou liberou "
            "(positivo) no ano. E o investimento em giro medido pelo caixa, e "
            "nao pela diferenca de saldos do balanco."
        ),
    ),
    Conta(
        chave="juros_pagos",
        rotulo="Juros pagos",
        demonstracao="dfc",
        sinonimos=(
            "juros pagos",
            "juros pagos sobre emprestimos",
            "juros sobre emprestimos e financiamentos pagos",
            "pagamento de juros",
            "juros pagos s/ emprestimos e financiamentos",
            "interest paid",
        ),
        sinal_invertido=True,
        ajuda=(
            "O juro que virou caixa no ano. Comparado a despesa financeira da "
            "DRE, revela quanto do custo da divida foi capitalizado em vez de pago."
        ),
        ordem="6.01.60",  # junto dos demais desembolsos operacionais
    ),
    Conta(
        chave="variacao_cambial_caixa",
        rotulo="Variacao cambial sobre caixa",
        demonstracao="dfc",
        sinonimos=(
            "variacao cambial s/ caixa e equivalentes",
            "variacao cambial sobre caixa e equivalentes",
            "efeito de variacao cambial sobre o caixa",
            "effect of exchange rate changes on cash",
        ),
        codigos_cvm=("6.04",),
        ajuda=(
            "Fecha a DFC de quem tem caixa no exterior. Nao e fluxo: e o caixa "
            "de fora sendo reconvertido. Sem ela a demonstracao nao bate em "
            "Vale, Gerdau ou Braskem."
        ),
    ),
    Conta(
        chave="variacao_caixa",
        rotulo="Aumento (reducao) de caixa e equivalentes",
        demonstracao="dfc",
        sinonimos=(
            "aumento (reducao) de caixa e equivalentes",
            "aumento reducao de caixa e equivalentes",
            "variacao liquida de caixa",
        ),
        codigos_cvm=("6.05",),
        ajuda=(
            "Fecha a DFC: operacional + investimento + financiamento + cambio. "
            "Serve de conferencia contra a variacao do caixa no balanco."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Capital social
# ---------------------------------------------------------------------------

CONTAS_CAPITAL: tuple[Conta, ...] = (
    Conta(
        chave="acoes_em_circulacao",
        rotulo="Acoes em circulacao",
        demonstracao="capital",
        sinonimos=(
            "acoes em circulacao",
            "quantidade de acoes",
            "shares outstanding",
        ),
        ordem="9.01",
        ajuda=(
            "Total emitido menos tesouraria. Fica fora das tres demonstracoes "
            "porque nao e valor monetario -- mas acompanha a escala dos valores, "
            "para que equity dividido por acoes de o preco por acao na mesma "
            "unidade."
        ),
    ),
)



# ---------------------------------------------------------------------------
# Demonstracao do valor adicionado
# ---------------------------------------------------------------------------
#
# A DVA nao entra em nenhuma conta do valuation, e mesmo assim e a demonstracao
# que responde perguntas que a DRE padronizada nao responde. Ela existe porque a
# lei brasileira obriga (Lei 11.638/2007), e em 450 das 467 companhias esta
# preenchida com a mesma estrutura de codigos.
#
# O que so ela tem:
#
# * ``7.01.01`` **receita bruta**. Contra a receita liquida do ``3.01``, a
#   diferenca sao impostos sobre vendas e devolucoes -- que a DRE padronizada
#   nao abre em lugar nenhum.
# * ``7.08.03.02`` **aluguel pago** -- que **nao** e o aluguel total, e sim o
#   que sobrou fora do IFRS 16. Medido, vale 0,19x o desembolso da DFC na
#   mediana. Serve para saber quanto de aluguel continua sendo despesa, nao para
#   substituir a leitura ex-IFRS 16.
# * ``7.08.01`` **folha**, e ``7.08.02`` o total de impostos, taxas e
#   contribuicoes -- nao so o IR.

CONTAS_DVA: tuple[Conta, ...] = (
    Conta(
        chave="receita_bruta",
        rotulo="Receita bruta (vendas de mercadorias, produtos e servicos)",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.01.01",),
        ordem="7.01.01",
        ajuda=(
            "Faturamento antes dos impostos sobre vendas e das devolucoes. A "
            "diferenca para a receita liquida e exatamente o que sai no caminho."
        ),
    ),
    Conta(
        chave="valor_adicionado_receitas",
        rotulo="Receitas (DVA)",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.01",),
        ordem="7.01",
    ),
    Conta(
        chave="insumos_de_terceiros",
        rotulo="Insumos adquiridos de terceiros",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.02",),
        ordem="7.02",
        ajuda="Quanto do faturamento sai direto para fornecedores.",
    ),
    Conta(
        chave="pessoal",
        rotulo="Pessoal (folha e beneficios)",
        demonstracao="dva",
        # Codigo so: em banco e seguradora a DVA numera as secoes como 7.09 e
        # 7.11, e casar por rotulo levaria "Pessoal" de banco para ca sem que o
        # resto da leitura acompanhasse.
        sinonimos=(),
        codigos_cvm=("7.08.01",),
        ordem="7.08.01",
        ajuda=(
            "Custo total de pessoal, incluindo beneficios e encargos. Nao aparece "
            "em nenhuma linha da DRE padronizada."
        ),
    ),
    Conta(
        chave="impostos_taxas_contribuicoes",
        rotulo="Impostos, taxas e contribuicoes (total)",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.08.02",),
        ordem="7.08.02",
        ajuda=(
            "Tudo que foi para o governo -- nao so IR e CSLL, mas tambem ICMS, "
            "PIS, COFINS, ISS e encargos."
        ),
    ),
    Conta(
        chave="aluguel_dva",
        rotulo="Alugueis pagos (DVA)",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.08.03.02",),
        ordem="7.08.03.02",
        ajuda=(
            "**Nao e o aluguel total.** Depois do IFRS 16 quase tudo saiu desta "
            "linha e virou depreciacao mais juros; sobra aqui o arrendamento de "
            "curto prazo e de baixo valor, que a norma dispensa. Medido em 81 "
            "companhias, a linha vale **0,19x** o desembolso de arrendamento da "
            "DFC na mediana -- usa-la para a leitura ex-IFRS 16 subestimaria o "
            "aluguel em cerca de 80%."
        ),
    ),
    Conta(
        chave="juros_dva",
        rotulo="Juros (remuneracao de capital de terceiros)",
        demonstracao="dva",
        sinonimos=(),
        codigos_cvm=("7.08.03.01",),
        ordem="7.08.03.01",
    ),
)


CONTAS: tuple[Conta, ...] = (
    CONTAS_DRE + CONTAS_BP + CONTAS_DFC + CONTAS_DVA + CONTAS_CAPITAL
)
POR_CHAVE: dict[str, Conta] = {c.chave: c for c in CONTAS}
CHAVES_OBRIGATORIAS: tuple[str, ...] = tuple(c.chave for c in CONTAS if c.obrigatoria)


# ---------------------------------------------------------------------------
# Derivacoes: contas que podem ser calculadas quando nao vem explicitas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Derivacao:
    """Como obter uma conta a partir de outras que ja estao disponiveis."""

    chave: str
    requer: tuple[str, ...]
    formula: str
    explicacao: str
    # Quando a conta ja existe **mas e zero em todos os anos**, deriva mesmo
    # assim. Existe por causa da D&A: muita companhia publica 3.04.02.02 como
    # zero, porque a depreciacao esta dentro do CPV e das despesas, e divulga o
    # numero de verdade so no ajuste da DFC. Sem isto, o zero da DRE bloqueia a
    # derivacao e a companhia fica com EBITDA igual ao EBIT -- na Raia Drogasil,
    # R$ 1,85 bilhao a menos.
    substitui_zero: bool = False


DERIVACOES: tuple[Derivacao, ...] = (
    Derivacao(
        chave="lucro_bruto",
        requer=("receita_liquida", "custo_produtos_vendidos"),
        formula="receita_liquida - custo_produtos_vendidos",
        explicacao="Lucro bruto = receita liquida - CPV",
    ),
    Derivacao(
        chave="ebit",
        requer=("lucro_bruto", "despesas_operacionais"),
        formula="lucro_bruto - despesas_operacionais",
        explicacao="EBIT = lucro bruto - despesas operacionais",
    ),
    Derivacao(
        chave="depreciacao_amortizacao",
        requer=("depreciacao_dfc",),
        formula="depreciacao_dfc",
        explicacao="D&A trazida da DFC, quando a DRE nao a destaca",
        substitui_zero=True,
    ),
    Derivacao(
        chave="lucro_antes_impostos",
        requer=("ebit", "resultado_financeiro"),
        formula="ebit + resultado_financeiro",
        explicacao="LAIR = EBIT + resultado financeiro",
    ),
    Derivacao(
        chave="lucro_liquido",
        requer=("lucro_antes_impostos", "impostos"),
        formula="lucro_antes_impostos - impostos",
        explicacao="Lucro liquido = LAIR - IR/CSLL",
    ),
    Derivacao(
        chave="resultado_financeiro",
        requer=("lucro_antes_impostos", "ebit"),
        formula="lucro_antes_impostos - ebit",
        explicacao="Resultado financeiro = LAIR - EBIT",
    ),
    Derivacao(
        chave="ebit",
        requer=("lucro_antes_impostos", "resultado_financeiro"),
        formula="lucro_antes_impostos - resultado_financeiro",
        explicacao="EBIT = LAIR - resultado financeiro",
    ),
    Derivacao(
        chave="impostos",
        requer=("lucro_antes_impostos", "lucro_liquido"),
        formula="lucro_antes_impostos - lucro_liquido",
        explicacao="IR/CSLL = LAIR - lucro liquido",
    ),
)


# ---------------------------------------------------------------------------
# Normalizacao e reconhecimento de rotulos
# ---------------------------------------------------------------------------

_LIMPEZA = re.compile(r"[^a-z0-9& ]+")
_ESPACOS = re.compile(r"\s+")
_CODIGO_CVM = re.compile(r"^\s*(\d(?:\.\d{2})*)\s*[-\s]")
_CODIGO_SOZINHO = re.compile(r"^\s*(\d(?:\.\d{2})*)\s*$")


def normalizar(texto: str) -> str:
    """Reduz um rotulo a uma forma comparavel: sem acento, minusculo, sem pontuacao.

    ``"Receita de Venda de Bens e/ou Servicos"`` e ``"RECEITA DE VENDA DE BENS
    E/OU SERVICOS "`` viram a mesma coisa, que e o que permite comparar rotulos
    escritos por gente diferente.
    """
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = texto.replace("/", " ")
    texto = _LIMPEZA.sub(" ", texto)
    return _ESPACOS.sub(" ", texto).strip()


def extrair_codigo_cvm(texto: str) -> str | None:
    """Extrai o codigo do plano de contas de um rotulo como ``"3.01 Receita..."``."""
    if texto is None:
        return None
    texto = str(texto).strip()
    achado = _CODIGO_SOZINHO.match(texto) or _CODIGO_CVM.match(texto)
    return achado.group(1) if achado else None


@dataclass(frozen=True)
class Reconhecimento:
    """Resultado de tentar identificar um rotulo de planilha."""

    chave: str | None
    confianca: float
    motivo: str


# Os sinonimos sao declarados como se leem ("Receita de Venda de Bens e/ou
# Servicos") e comparados ja normalizados. Normalizar na carga -- e nao a cada
# comparacao -- garante que os dois lados da comparacao passem pela mesma regra:
# do contrario, qualquer sinonimo com acento ou barra nunca casaria.
_SINONIMOS: tuple[tuple[str, str], ...] = tuple(
    (normalizar(sinonimo), conta.chave)
    for conta in CONTAS
    for sinonimo in conta.sinonimos
)
_SINONIMOS_EXATOS: dict[str, str] = {}
for _normalizado, _chave in _SINONIMOS:
    _SINONIMOS_EXATOS.setdefault(_normalizado, _chave)


# Terminacoes de plural em portugues, da mais especifica para a mais geral.
# Aplicadas aos dois lados da comparacao, entao nao importa se a forma resultante
# e uma palavra de verdade -- importa que "depreciacoes" e "depreciacao" cheguem
# a mesma coisa.
_PLURAIS: tuple[tuple[str, str], ...] = (
    ("oes", "ao"),
    ("aes", "ao"),
    ("ais", "al"),
    ("eis", "el"),
    ("ois", "ol"),
    ("res", "r"),
    ("zes", "z"),
    ("ns", "m"),
)


def singularizar(texto: str) -> str:
    """Reduz plurais para permitir casar rotulo com sinonimo.

    A CVM escreve "Depreciacoes e Amortizacoes" e o vocabulario declarava
    "Depreciacao e Amortizacao". Sem esta reducao os dois nao casam, e o efeito
    nao e cosmetico: **medido na DFP consolidada de 2024, 35% das linhas de
    depreciacao ficavam sem reconhecimento**, e companhia sem D&A reconhecida
    fica com EBITDA igual ao EBIT. Na Raia Drogasil isso escondia R$ 1,85 bilhao.

    Palavras curtas ficam de fora: "mais" nao deve virar "mal".
    """
    palavras = []
    for palavra in texto.split():
        if len(palavra) <= 4:
            palavras.append(palavra)
            continue
        for fim, troca in _PLURAIS:
            if palavra.endswith(fim):
                palavra = palavra[: -len(fim)] + troca
                break
        else:
            if palavra.endswith("s"):
                palavra = palavra[:-1]
        palavras.append(palavra)
    return " ".join(palavras)


_SINONIMOS_SINGULARES: dict[str, str] = {}
for _normalizado, _chave in _SINONIMOS:
    _SINONIMOS_SINGULARES.setdefault(singularizar(_normalizado), _chave)

# O mesmo sinonimo pode pertencer a contas de demonstracoes diferentes:
# "Depreciacao e Amortizacao" e conta da DRE **e** ajuste da DFC. Sem indexar
# por demonstracao, a primeira declarada ganha sempre e a outra fica inalcancavel
# -- foi o que manteve ``depreciacao_dfc`` morta, e com ela o EBITDA de quem so
# divulga D&A no fluxo de caixa.
_POR_DEMONSTRACAO: dict[str, dict[str, str]] = {}
_SINGULARES_POR_DEMONSTRACAO: dict[str, dict[str, str]] = {}
for _conta in CONTAS:
    _exatos = _POR_DEMONSTRACAO.setdefault(_conta.demonstracao, {})
    _singulares = _SINGULARES_POR_DEMONSTRACAO.setdefault(_conta.demonstracao, {})
    for _sinonimo in _conta.sinonimos:
        _norm = normalizar(_sinonimo)
        _exatos.setdefault(_norm, _conta.chave)
        _singulares.setdefault(singularizar(_norm), _conta.chave)

_CODIGOS: dict[str, str] = {}
for _conta in CONTAS:
    for _codigo in _conta.codigos_cvm:
        _CODIGOS.setdefault(_codigo, _conta.chave)


# **"Amortizacao de intangiveis" e "Despesa de Depreciacao" ficaram de fora do
# vocabulario de proposito, e a medicao e que decidiu.** Os dois rotulos existem
# na DRE e nao alcancam o limiar de reconhecimento (0,42 e 0,50), entao Allpark
# e PRIO Forte ficam sem D&A.
#
# Medido no DFP consolidado de 2024, o padrao alcanca **6 linhas em 5
# companhias**, e o saldo nao paga:
#
#   - **4 das 5 ja tem D&A pela DFC**, que e a fonte preferida por estrutura --
#     a linha da DRE mora dentro de "Despesas Gerais e Administrativas" e captura
#     so a depreciacao que correu pelo SG&A. Acrescentar o sinonimo ali cria
#     disputa com a fonte melhor, sem acrescentar dado.
#   - **das 2 que ganhariam, uma vale R$ 0,2 mi** (PRIO Forte).
#   - **2 das 6 linhas estao em `3.04.05`**, a subarvore que alimenta
#     `itens_nao_recorrentes`. Amortizacao de intangivel e a coisa mais
#     recorrente que existe: o problema da Allpark nao e a D&A faltando, e a
#     companhia ter posto R$ 164,3 mi de amortizacao em "Outras Despesas
#     Operacionais", o que ja infla a margem EBIT recorrente dela.
#
# E o mesmo desfecho do `7.08.03.02` da DVA: rotulo plausivel que a medicao
# reprovou. Fica registrado para nao ser "descoberto" de novo.


def reconhecer(
    rotulo: str, codigo: str | None = None, demonstracao: str | None = None
) -> Reconhecimento:
    """Identifica a conta canonica de um rotulo de planilha.

    A ordem das tentativas vai da evidencia mais forte para a mais fraca:
    codigo CVM exato, sinonimo exato, e por fim sinonimo contido no rotulo. A
    confianca devolvida alimenta a tela de conferencia do app -- o que foi
    reconhecido com folga passa direto, o resto e mostrado para o usuario
    confirmar.
    """
    codigo = codigo or extrair_codigo_cvm(rotulo)
    if codigo and codigo in _CODIGOS:
        candidata = _CODIGOS[codigo]
        if demonstracao is None or POR_CHAVE[candidata].demonstracao == demonstracao:
            return Reconhecimento(candidata, 1.0, f"codigo CVM {codigo}")

    normalizado = normalizar(rotulo)
    if not normalizado:
        return Reconhecimento(None, 0.0, "rotulo vazio")

    exatos = _POR_DEMONSTRACAO.get(demonstracao, _SINONIMOS_EXATOS) if demonstracao else _SINONIMOS_EXATOS
    if normalizado in exatos:
        return Reconhecimento(exatos[normalizado], 0.95, "sinonimo exato")

    # Plural e singular sao a mesma conta. Vem antes do casamento parcial porque
    # e evidencia mais forte: o rotulo inteiro casa, so a flexao difere.
    singulares = (
        _SINGULARES_POR_DEMONSTRACAO.get(demonstracao, _SINONIMOS_SINGULARES)
        if demonstracao
        else _SINONIMOS_SINGULARES
    )
    singular = singularizar(normalizado)
    if singular in singulares:
        return Reconhecimento(singulares[singular], 0.90, "sinonimo exato (plural)")

    # Casamento parcial: exige que o sinonimo ocupe boa parte do rotulo, para
    # "receita liquida" nao capturar "receita liquida de juros de aplicacoes".
    melhor = Reconhecimento(None, 0.0, "sem correspondencia")
    for sinonimo, chave in _SINONIMOS:
        if demonstracao and POR_CHAVE[chave].demonstracao != demonstracao:
            continue
        if len(sinonimo) < 5 or sinonimo not in normalizado:
            continue
        proporcao = len(sinonimo) / len(normalizado)
        if proporcao > melhor.confianca:
            melhor = Reconhecimento(chave, min(proporcao, 0.9), f"contem '{sinonimo}'")

    if melhor.confianca >= 0.6:
        return melhor
    return Reconhecimento(None, melhor.confianca, "sem correspondencia confiavel")
