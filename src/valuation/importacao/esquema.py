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
        sinonimos=("resultado bruto", "lucro bruto", "gross profit"),
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
    ),
)


CONTAS: tuple[Conta, ...] = CONTAS_DRE + CONTAS_BP + CONTAS_DFC
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

_CODIGOS: dict[str, str] = {}
for _conta in CONTAS:
    for _codigo in _conta.codigos_cvm:
        _CODIGOS.setdefault(_codigo, _conta.chave)


def reconhecer(rotulo: str, codigo: str | None = None) -> Reconhecimento:
    """Identifica a conta canonica de um rotulo de planilha.

    A ordem das tentativas vai da evidencia mais forte para a mais fraca:
    codigo CVM exato, sinonimo exato, e por fim sinonimo contido no rotulo. A
    confianca devolvida alimenta a tela de conferencia do app -- o que foi
    reconhecido com folga passa direto, o resto e mostrado para o usuario
    confirmar.
    """
    codigo = codigo or extrair_codigo_cvm(rotulo)
    if codigo and codigo in _CODIGOS:
        return Reconhecimento(_CODIGOS[codigo], 1.0, f"codigo CVM {codigo}")

    normalizado = normalizar(rotulo)
    if not normalizado:
        return Reconhecimento(None, 0.0, "rotulo vazio")

    if normalizado in _SINONIMOS_EXATOS:
        return Reconhecimento(_SINONIMOS_EXATOS[normalizado], 0.95, "sinonimo exato")

    # Casamento parcial: exige que o sinonimo ocupe boa parte do rotulo, para
    # "receita liquida" nao capturar "receita liquida de juros de aplicacoes".
    melhor = Reconhecimento(None, 0.0, "sem correspondencia")
    for sinonimo, chave in _SINONIMOS:
        if len(sinonimo) < 5 or sinonimo not in normalizado:
            continue
        proporcao = len(sinonimo) / len(normalizado)
        if proporcao > melhor.confianca:
            melhor = Reconhecimento(chave, min(proporcao, 0.9), f"contem '{sinonimo}'")

    if melhor.confianca >= 0.6:
        return melhor
    return Reconhecimento(None, melhor.confianca, "sem correspondencia confiavel")
