"""Relatorio estruturado: tudo que o app apurou, em um documento so.

O que este modulo automatiza e a **primeira camada** do trabalho de analise --
a que hoje consome horas e nao exige julgamento: reunir o que a empresa
entregou, o que o modelo assume, quanto vale, o que o preco embute e o que pode
dar errado. Nao e a analise; e o material sobre o qual a analise acontece.

Tres decisoes que valem registrar
---------------------------------

**Markdown, nao PDF.** O relatorio precisa ser diffavel. Rodar de novo daqui a
tres meses e comparar com ``git diff`` mostra exatamente o que mudou no
raciocinio; um PDF novo so mostra que mudou alguma coisa.

**Nada de adjetivo sem numero atras.** Cada afirmacao do texto sai de algo
medido, e o numero aparece junto. "Margem confortavel" nao diz nada; "margem
EBITDA de 20,1% contra mediana de 18,7% nos quatro anos" da para conferir e
para discordar.

**As secoes ausentes aparecem.** Sem historico importado nao ha secao de
qualidade dos lucros -- e o relatorio diz isso, em vez de simplesmente nao ter a
secao. Quem le precisa saber a diferenca entre "foi verificado e esta bem" e
"nao foi verificado".
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import referencias
from . import formato
from .diagnostico import ALERTA, ERRO, Diagnostico
from .margem import MargemDeSeguranca
from .modelo import ResultadoValuation
from .premissas import BASES_DO_MULTIPLO

# Indicadores que sustentam a leitura do historico, na ordem em que sao lidos.
INDICADORES_DO_HISTORICO = (
    ("Crescimento da receita", "pct"),
    ("Margem EBITDA", "pct"),
    ("Margem liquida", "pct"),
    ("ROIC", "pct"),
    ("Conversao de caixa (FCO / EBITDA)", "pct"),
    ("Capex / Receita", "pct"),
    ("Divida liquida / EBITDA", "num"),
    ("Taxa de reinvestimento", "pct"),
)


def _pct(valor, casas: int = 1) -> str:
    return formato.pct(valor, casas, "n/d")


def _num(valor, casas: int = 1) -> str:
    return formato.num(valor, casas, "n/d")


def _formatar(valor: float, tipo: str) -> str:
    return _pct(valor) if tipo == "pct" else _num(valor, 2)


def _tabela_markdown(tabela: pd.DataFrame) -> str:
    """Converte para markdown sem depender do ``tabulate``."""
    colunas = [str(c) for c in tabela.columns]
    linhas = ["| " + " | ".join([tabela.index.name or ""] + colunas) + " |"]
    linhas.append("|" + "---|" * (len(colunas) + 1))
    for indice, linha in tabela.iterrows():
        celulas = [str(indice)] + [str(v) for v in linha]
        linhas.append("| " + " | ".join(celulas) + " |")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Secoes
# ---------------------------------------------------------------------------


def _cabecalho(resultado: ResultadoValuation, data: str) -> list[str]:
    empresa = resultado.empresa
    return [
        f"# {empresa.nome}",
        "",
        f"Relatório gerado em {data or date.today().isoformat()} · "
        f"data-base {empresa.data_base or 'não informada'} · "
        f"valores em {empresa.unidade}.",
        "",
        "> Material de apoio à análise, não recomendação de investimento. Cada "
        "número abaixo vem de uma premissa que pode ser conferida e contestada; "
        "a seção final lista o que este relatório **não** verifica.",
    ]


def _resumo(
    resultado: ResultadoValuation, margem: MargemDeSeguranca | None
) -> list[str]:
    empresa = resultado.empresa
    dcf = resultado.dcf
    cc = resultado.custo_capital
    perp = empresa.perpetuidade

    linhas = ["## Resumo", ""]

    origem_g = {
        "livre": "informado",
        "ipca": "ancorado no IPCA",
        "pib_nominal": "ancorado no PIB nominal",
    }[perp.ancora]

    itens = [
        ("Enterprise Value", _num(dcf.enterprise_value, 1)),
        ("Equity Value", _num(dcf.equity_value, 1)),
    ]
    if dcf.valor_por_acao is not None:
        itens.append(("Valor por ação", _num(dcf.valor_por_acao, 2)))
    itens += [
        ("WACC", _pct(cc.wacc_brl, 2)),
        ("Ke", _pct(cc.ke_brl, 2)),
        (f"Crescimento perpétuo ({origem_g})", _pct(perp.crescimento_perpetuo, 2)),
        ("Peso da perpetuidade no valor", _pct(dcf.peso_perpetuidade)),
    ]
    for rotulo, valor in itens:
        linhas.append(f"- **{rotulo}**: {valor}")

    linhas += ["", _tese(resultado, margem)]
    return linhas


def _tese(resultado: ResultadoValuation, margem: MargemDeSeguranca | None) -> str:
    """Um paragrafo, so com o que foi medido.

    A tentacao aqui e escrever uma recomendacao. O paragrafo diz de onde vem o
    valor e o que sustenta a conta -- quem decide o que fazer com isso e quem le.
    """
    dcf = resultado.dcf
    peso = dcf.peso_perpetuidade
    perp = resultado.empresa.perpetuidade

    partes = [
        f"O valor está em {_num(dcf.equity_value, 1)} "
        f"{resultado.empresa.unidade}, dos quais {_pct(peso)} vêm da perpetuidade"
    ]
    if peso > 0.75:
        partes.append(
            f" — ou seja, a maior parte da conta não está nos anos projetados, "
            f"mas na hipótese de crescer {_pct(perp.crescimento_perpetuo, 2)} "
            "para sempre"
        )
    partes.append(".")

    if margem is not None:
        partes.append(
            f" Ao preço de {_num(margem.preco, 2)}: {margem.resumo()[0].lower()}"
            f"{margem.resumo()[1:]} O preço máximo para manter "
            f"{_pct(margem.exigida)} de margem seria {_num(margem.preco_maximo, 2)}."
        )
    else:
        partes.append(
            " Nenhum preço foi informado, então este relatório calcula valor e não "
            "avalia oportunidade."
        )
    return "".join(partes)


def _historico(analise) -> list[str]:
    if analise is None:
        return [
            "## O que a empresa entregou",
            "",
            "**Não avaliado.** Nenhuma demonstração foi importada, então as "
            "premissas deste modelo não estão ancoradas no que a empresa de fato "
            "entregou. É a lacuna mais séria que um relatório destes pode ter.",
        ]

    anos = analise.anos
    linhas = [
        "## O que a empresa entregou",
        "",
        f"Período apurado: {anos[0]} a {anos[-1]} ({len(anos)} exercícios).",
        "",
    ]

    tabela = {}
    for nome, tipo in INDICADORES_DO_HISTORICO:
        if nome not in analise.indicadores.index:
            continue
        tabela[nome] = {
            "Mediana": _formatar(analise.mediana(nome), tipo),
            "Último ano": _formatar(analise.ultimo(nome), tipo),
        }
    if tabela:
        quadro = pd.DataFrame(tabela).T
        quadro.index.name = "Indicador"
        linhas.append(_tabela_markdown(quadro))

    return linhas


def _qualidade(qualidade, analise=None) -> list[str]:
    if qualidade is None:
        return [
            "## Qualidade dos lucros",
            "",
            "**Não avaliada** — depende do fluxo de caixa das demonstrações "
            "importadas.",
        ]

    linhas = [
        "## Qualidade dos lucros",
        "",
        f"**Veredito: {qualidade.veredito}.** {qualidade.resumo}",
        "",
        "O veredito é o **pior** dos sinais, não a média deles: uma boa conversão "
        "de caixa não cancela juro capitalizado.",
        "",
    ]
    for sinal in qualidade.por_severidade:
        linhas.append(f"- {sinal.icone} **{sinal.titulo}** — {sinal.detalhe}")
    linhas += _ponte_do_caixa(analise)
    return linhas


def _ponte_do_caixa(analise) -> list[str]:
    """De EBITDA a FCO, degrau a degrau, quando a DFC permite montar.

    O relatorio e o que sobra depois que a tela fecha, e a conversao sozinha nao
    diz **onde** o caixa se perdeu. Sem a ponte, quem le em tres meses ve
    "converte 34%" e refaz do zero a pergunta que a tela ja tinha respondido.

    Sai do relatorio quando a ponte nao fecha: uma tabela que nao reconstroi o
    FCO publicado descreveria uma companhia que nao e esta.
    """
    if analise is None:
        return []
    try:
        from .qualidade import ponte_do_caixa

        ponte = ponte_do_caixa(analise)
    except Exception:  # noqa: BLE001 - relatorio nao quebra por falta de DFC
        return []
    if ponte is None or not ponte.fecha:
        return []

    linhas = [
        "",
        f"### De EBITDA a caixa — {analise.anos[-1]}",
        "",
        "A conversão FCO/EBITDA responde três perguntas de uma vez, e só uma "
        "delas é sobre a operação: o resultado virou caixa? o giro prendeu "
        "caixa? quanto saiu para imposto e juro? A ponte separa as três.",
        "",
        "| Degrau | Valor | % do EBITDA |",
        "|---|---:|---:|",
    ]
    for rotulo, valor, fracao in ponte.degraus:
        linhas.append(f"| {rotulo} | {_num(valor, 1)} | {_pct(fracao)} |")
    linhas += [
        "",
        "`FCO = CGO + variação do giro + outros − imposto pago − juro pago`, e a "
        "ponte fecha com o FCO publicado.",
    ]
    return linhas


def _investimento(composicao) -> list[str]:
    """A secao de investimento aberta, com o que e capex e o que so passa ali.

    Sem isto o relatorio dizia "capex de X" e o leitor nao tinha como saber se o
    fluxo de investimento daquele ano foi ativo fixo, compra de empresa ou
    resgate de aplicacao. Medido no DFP consolidado de 2024, **53,5% das
    companhias movimentam TVM** dentro da secao e em **28 delas o TVM inverte o
    sinal do fluxo** -- ler o FCI como "investimento" erra a direcao.
    """
    if composicao is None:
        return [
            "## Onde foi o dinheiro do investimento",
            "",
            "**Não avaliado** — depende da árvore publicada pela companhia, que "
            "não veio nesta importação.",
        ]

    linhas = [
        "## Onde foi o dinheiro do investimento",
        "",
        f"A seção de investimento do exercício {composicao.ano}, aberta por "
        "natureza. **Nem tudo que passa por ela é capex**: aplicação e resgate "
        "de título entram aqui e não são investimento na operação, e aquisição "
        "de participação consome o mesmo caixa sem repor ativo.",
        "",
    ]
    quadro = pd.DataFrame(
        {"Valor": [_num(v) for _, v in composicao.linhas()]},
        index=[rotulo for rotulo, _ in composicao.linhas()],
    )
    quadro.index.name = "Componente"
    linhas.append(_tabela_markdown(quadro))
    linhas.append("")
    linhas.append(
        f"**Capex** (imobilizado + intangível + outros): {_num(composicao.capex)}. "
        f"**Entradas** (venda de ativo, de investimentos e proventos): "
        f"{_num(composicao.entradas)}."
    )
    if not composicao.fecha:
        linhas.append("")
        linhas.append(
            "> **O não classificado passa de 1% do total.** A leitura não "
            "entendeu esta companhia; confira as linhas publicadas antes de usar "
            "o número por natureza."
        )
    return linhas


def _ciclo_de_caixa(analise) -> list[str]:
    """Para onde o ciclo foi, e qual perna o moveu.

    O relatorio dizia quanto capital de giro a empresa consome sobre a receita,
    o que responde "quanto pesa" e nao "por que mudou". A decomposicao e exata
    por construcao -- ``dCCC = dPMR + dPME - dPMP`` --, e a traducao em caixa e
    o que deixa o numero acionavel: "o ciclo alongou 14 dias" nao decide nada
    sozinho; "prendeu R$ 1,6 bi" decide.
    """
    from .historico import NOME_DO_CICLO, caixa_preso_no_ciclo, ponte_do_ciclo

    titulo = "## O ciclo de caixa, e para onde ele foi"
    ponte = ponte_do_ciclo(analise) if analise is not None else None
    if ponte is None or not ponte.fecha:
        return [
            titulo,
            "",
            "**Não avaliado** — o ciclo precisa de recebíveis, estoques, "
            "fornecedores e custo dos produtos vendidos em pelo menos dois "
            "períodos, e esta companhia não publica todos.",
        ]

    curto = {
        "Prazo medio de recebimento (dias)": "Recebimento",
        "Prazo medio de estoque (dias)": "Estoque",
        "Prazo medio de pagamento (dias)": "Pagamento",
    }
    direcao = "alongou" if ponte.variacao > 0 else "encurtou"
    linhas = [
        titulo,
        "",
        f"O ciclo saiu de **{ponte.ciclo_de:,.0f} dias** em {ponte.de} para "
        f"**{ponte.ciclo_para:,.0f} dias** em {ponte.para} — "
        f"{direcao} {abs(ponte.variacao):,.0f} dias.",
        "",
    ]

    quadro = pd.DataFrame(
        {
            str(ponte.de): [f"{p.de:,.0f}" for p in ponte.pernas],
            str(ponte.para): [f"{p.para:,.0f}" for p in ponte.pernas],
            "Contribuição (dias)": [f"{p.contribuicao:+,.0f}" for p in ponte.pernas],
        },
        index=[curto.get(p.nome, p.nome) for p in ponte.pernas],
    )
    quadro.index.name = "Perna"
    linhas.append(_tabela_markdown(quadro))
    linhas.append("")

    maior = max(ponte.pernas, key=lambda p: abs(p.contribuicao))
    linhas.append(
        f"A perna que mais pesou foi **{curto.get(maior.nome, maior.nome)}** "
        f"({maior.contribuicao:+,.0f} dias). As três somam a variação exatamente: "
        "a decomposição é uma identidade, e prazo de pagamento entra com sinal "
        "invertido porque alongá-lo **encurta** o ciclo."
    )

    if np.isfinite(ponte.caixa):
        verbo = "prendeu" if ponte.caixa > 0 else "liberou"
        unidade = ponte.unidade or ""
        linhas.append("")
        linhas.append(
            f"Sobre a venda diária de {ponte.para}, essa variação **{verbo} "
            f"{_num(abs(ponte.caixa), 0)} {unidade}** de caixa."
        )

    preso = caixa_preso_no_ciclo(analise).dropna()
    if not preso.empty:
        linhas.append("")
        linhas.append(
            f"No total, o ciclo mantém **{_num(float(preso.iloc[-1]), 0)} "
            f"{ponte.unidade}** parados entre pagar o fornecedor e receber do "
            "cliente."
        )

    referencia = referencias.descrever(NOME_DO_CICLO, ponte.ciclo_para)
    if referencia:
        linhas.append("")
        linhas.append(f"O ciclo de {ponte.para} fica {referencia}.")

    return linhas


def _ifrs16(visao) -> list[str]:
    """As duas leituras do resultado, quando o aluguel pesa o bastante.

    Sai do relatorio quando o aluguel e pequeno: uma secao inteira para dizer
    que os dois numeros sao quase iguais gasta a atencao de quem le.
    """
    if visao is None or not visao.relevante:
        return []

    reportada = float(visao.margem_ebitda_reportada.dropna().iloc[-1])
    ex = float(visao.margem_ebitda.dropna().iloc[-1])
    linhas = [
        "## O aluguel, dentro e fora do EBITDA",
        "",
        "Até 2018 o aluguel era despesa operacional. Desde o **IFRS 16 / CPC 06 "
        "(R2)** ele virou depreciação de direito de uso mais juros — então o "
        "EBITDA subiu sem que nada tenha melhorado no negócio.",
        "",
        f"- **Margem EBITDA reportada**: {_pct(reportada)}",
        f"- **Margem EBITDA ex-IFRS 16**: {_pct(ex)}",
        f"- **O aluguel consome** {_pct(visao.peso_do_aluguel)} do EBITDA reportado.",
    ]

    alavancagem = visao.alavancagem_reportada.dropna()
    alavancagem_ex = visao.alavancagem.dropna()
    if not alavancagem.empty and not alavancagem_ex.empty:
        linhas.append(
            f"- **Dívida líquida / EBITDA**: {_num(float(alavancagem.iloc[-1]), 2)}x "
            f"reportada, {_num(float(alavancagem_ex.iloc[-1]), 2)}x ex-IFRS 16."
        )

    linhas += [
        "",
        "**As duas leituras não se misturam.** Ou dívida **com** arrendamento sobre "
        "EBITDA **com** aluguel, ou dívida **sem** sobre EBITDA **sem**. Cruzar as "
        "duas — dívida cheia sobre EBITDA ex-aluguel — infla a alavancagem; ao "
        "contrário, esconde.",
    ]
    if visao.ressalva:
        linhas += ["", visao.ressalva]
    return linhas


def _premissas(resultado: ResultadoValuation) -> list[str]:
    empresa = resultado.empresa
    op = empresa.operacionais
    perp = empresa.perpetuidade
    macro = empresa.macro

    anos = [str(op.ano_base + i + 1) for i in range(op.horizonte)]
    colunas = {
        "Crescimento da receita": [_pct(v) for v in op.crescimento_receita],
        "Margem EBITDA": [_pct(v) for v in op.margem_ebitda],
        "Capex / receita": [_pct(v) for v in op.capex_pct_receita],
        "Capital de giro / receita": [_pct(v) for v in op.capital_giro_pct_receita],
    }
    if op.arrendamento_pct_receita is not None:
        colunas["Arrendamento / receita"] = [
            _pct(v) for v in op.arrendamento_pct_receita
        ]
    quadro = pd.DataFrame(colunas, index=anos)
    quadro.index.name = "Ano"

    linhas = [
        "## O que o modelo assume",
        "",
        _tabela_markdown(quadro),
        "",
        "### Perpetuidade e macro",
        "",
    ]

    if perp.metodo == "gordon":
        origem = {
            "livre": "informado à mão",
            "ipca": f"derivado do IPCA de {_pct(macro.inflacao_brl)}",
            "pib_nominal": (
                f"derivado do PIB nominal — IPCA de {_pct(macro.inflacao_brl)} "
                f"composto com PIB real de {_pct(macro.pib_real)}"
            ),
        }[perp.ancora]
        linhas.append(
            f"- **Crescimento perpétuo**: {_pct(perp.crescimento_perpetuo, 2)}, {origem}."
        )
        linhas.append(
            f"- **Teto da economia**: {_pct(macro.pib_nominal, 2)}. "
            + (
                "O crescimento assumido está acima dele."
                if perp.crescimento_perpetuo > macro.pib_nominal
                else "O crescimento assumido cabe dentro dele."
            )
        )
        if perp.roic_perpetuidade is None:
            linhas.append(
                "- **Reinvestimento**: não normalizado. O fluxo perpétuo cresce sem "
                "exigir capital para sustentar o crescimento, o que costuma "
                "superestimar o valor terminal."
            )
        else:
            reinvestimento = perp.crescimento_perpetuo / perp.roic_perpetuidade
            indexado = (
                " O ROIC é informado em termos reais e acompanha a inflação."
                if perp.roic_real is not None
                else " O ROIC é nominal e fixo."
            )
            linhas.append(
                f"- **Reinvestimento**: normalizado a ROIC de "
                f"{_pct(perp.roic_perpetuidade, 1)}, o que retém "
                f"{_pct(reinvestimento)} do NOPAT perpétuo.{indexado}"
            )
    else:
        conta = "EBITDA" if perp.base_do_multiplo == "ebitda" else "lucro líquido"
        linhas.append(
            f"- **Perpetuidade por múltiplo de saída**: "
            f"{_num(perp.multiplo_saida, 1)}x "
            f"{BASES_DO_MULTIPLO[perp.base_do_multiplo]} sobre o {conta} do último "
            "ano projetado."
        )
        # O P/L devolve valor de equity dentro de uma serie de firma, e a
        # conversao usa a divida liquida de hoje. Quem le o relatorio em tres
        # meses precisa saber que esse numero e hipotese, e nao projecao.
        if perp.base_do_multiplo == "lucro":
            linhas.append(
                "  O P/L precifica o acionista, então a dívida líquida de hoje "
                "volta ao valor terminal para não ser descontada duas vezes na "
                "ponte. O modelo não projeta balanço: a dívida do ano terminal é "
                "suposta igual à de hoje."
            )

    if op.arrendamento_pct_receita is not None:
        linhas.append(
            f"- **Arrendamento**: o passivo cresce com a receita, a "
            f"{_pct(op.arrendamento_pct_receita[0])} dela, e a adição de cada ano "
            "sai do fluxo. Contrato novo de aluguel não passa pelo capex — sem "
            "esta linha, uma rede que abre pontos mostra FCFF que não tem."
        )

    cc = resultado.custo_capital
    p = empresa.custo_capital
    linhas += ["", "### Custo de capital", ""]

    # **O relatório descreve a construção que foi usada**, e não uma delas. Ele
    # escrevia sempre a soma em dólar; com o caminho local escolhido, o leitor
    # via uma conta com risco-país que o modelo não fez — e cujos números não
    # somavam o Ke mostrado logo abaixo.
    if p.metodo == "local":
        linhas += [
            f"- Ke em reais, direto: {_pct(cc.rf_brl, 2)} (NTN-B nominalizada "
            f"pelo IPCA de {_pct(macro.inflacao_brl)}) + "
            f"{_num(cc.beta_realavancado, 2)} × {_pct(p.erp_local, 2)} (prêmio "
            f"de risco local) = {_pct(cc.ke_brl, 2)}.",
            "- **Não há termo de risco-país**: ele já está dentro da NTN-B, e "
            "somá-lo o contaria duas vezes.",
            "- O prêmio de risco local é **premissa, não medida** — a série "
            "brasileira é curta e volátil demais para estimá-lo, e ele é o "
            "número que mais move este Ke.",
        ]
    else:
        linhas += [
            f"- Ke em USD: {_pct(p.rf_usd, 2)} (livre de risco) + "
            f"{_num(cc.beta_realavancado, 2)} × {_pct(p.erp_maduro, 2)} (prêmio "
            f"de mercado) + {_pct(p.lambda_pais * p.risco_pais, 2)} "
            f"(risco-país) = {_pct(cc.ke_usd, 2)}.",
            f"- Convertido para moeda local pelo diferencial de inflação "
            f"({_pct(macro.inflacao_brl)} contra {_pct(macro.inflacao_usd)}): "
            f"Ke de {_pct(cc.ke_brl, 2)}.",
        ]

    linhas.append(
        f"- Kd após imposto: {_pct(cc.kd_liquido_brl, 2)}. WACC: "
        f"{_pct(cc.wacc_brl, 2)}, com {_pct(cc.peso_equity)} de capital próprio."
    )
    return linhas


def _ponte(resultado: ResultadoValuation) -> list[str]:
    tabela = resultado.tabela_ponte().copy()
    coluna = tabela.columns[0]
    tabela[coluna] = tabela[coluna].map(lambda v: _num(v, 1))
    if tabela.index.name is None:
        tabela.index.name = "Item"
    return ["## Do Enterprise Value ao Equity Value", "", _tabela_markdown(tabela)]


def _lucro_residual(valuation, ke_referencia: float | None = None) -> list[str]:
    """A seção de valor quando a companhia é instituição financeira.

    Existe porque o relatório inteiro é montado em torno do DCF, e para um banco
    o DCF **não foi usado** — a tela mostrou lucro residual. Sem esta seção o
    entregável final descreveria um Enterprise Value, um WACC e uma ponte que
    ninguém calculou, contradizendo a tela em que o número foi visto.
    """
    if valuation is None:
        return []

    pvp = (
        valuation.equity_value / valuation.patrimonio_inicial
        if valuation.patrimonio_inicial
        else float("nan")
    )
    linhas = [
        "## Valor, pelo lucro residual",
        "",
        "**FCFF descontado ao WACC não se aplica a esta companhia.** Para uma "
        "indústria a dívida financia o ativo e o custo dela entra na taxa de "
        "desconto; para um banco a dívida — depósito, captação — **é o insumo do "
        "negócio**, e o spread entre captar e emprestar é a receita. Descontar um "
        "fluxo para a firma ao WACC somaria ao valor o que a instituição ganha "
        "por tomar dinheiro e depois descontaria por ela tomar dinheiro.",
        "",
        "O valor aqui é o patrimônio contábil mais o valor presente do que a "
        "instituição ganha **acima do custo de capital** sobre esse patrimônio.",
        "",
    ]
    itens = [
        ("Equity Value", _num(valuation.equity_value, 1)),
        ("Patrimônio contábil", _num(valuation.patrimonio_inicial, 1)),
        ("P/VP implícito", f"{_num(pvp, 2)}x"),
        ("Ke", _pct(valuation.ke, 2)),
        ("Do patrimônio", _pct(valuation.peso_do_patrimonio)),
        ("Do valor terminal", _pct(valuation.peso_do_terminal)),
    ]
    linhas += [f"- **{rotulo}**: {valor}" for rotulo, valor in itens]

    if valuation.equity_value < valuation.patrimonio_inicial:
        linhas += [
            "",
            "**O modelo devolve menos que o patrimônio contábil.** Com retorno "
            "sobre o patrimônio abaixo do custo de capital, cada real retido rende "
            "menos que o Ke — a instituição destrói valor sobre o próprio livro.",
        ]
    else:
        linhas += [
            "",
            "O modelo devolve mais que o patrimônio contábil: a instituição "
            "entrega retorno acima do custo de capital sobre o livro que tem.",
        ]

    linhas += [
        "",
        f"O patrimônio contábil carrega {_pct(valuation.peso_do_patrimonio)} do "
        "valor. **É a virtude do modelo:** no DCF de uma indústria o valor "
        "terminal costuma valer 60% a 80% do total, e a premissa mais frágil "
        "carrega quase tudo; aqui a âncora contábil segura a maior parte, e erro "
        "na perpetuidade custa menos.",
        "",
        "A conta, ano a ano:",
        "",
        _tabela_markdown(
            valuation.tabela().map(lambda v: _num(v, 1)).rename_axis("Item")
        ),
        "",
        "**O que este modelo não faz:** não considera capital regulatório. Uma "
        "instituição que cresce precisa de capital para sustentar o ativo "
        "ponderado por risco, e crescimento alto com distribuição alta pode ser "
        "inviável por Basileia sem que a aritmética acima reclame.",
    ]
    return linhas


def _historico_do_banco(historico) -> list[str]:
    """O passado de uma instituição financeira, nos indicadores que valem nela.

    Margem EBITDA, capex sobre receita e conversão de caixa **não querem dizer
    num banco o que querem dizer no resto** — a receita dele é spread, o ativo é
    crédito e não fábrica. A seção industrial mostrava margem EBITDA de −8,3%
    para o Bradesco, número que não descreve nada.
    """
    if historico is None:
        return []
    anos = historico.anos
    linhas = [
        "## O que a instituição entregou",
        "",
        f"Período apurado: {anos[0]} a {anos[-1]} ({len(anos)} exercícios).",
        "",
    ]
    # Monta a tabela formatada do zero: escrever texto por cima de uma linha
    # numerica faz o pandas recusar (``LossySetitemError``).
    original = historico.tabela()
    formatada = pd.DataFrame(
        {
            coluna: [
                (_pct if rotulo in ("ROE", "Payout") else lambda v: _num(v, 1))(
                    original.loc[rotulo, coluna]
                )
                for rotulo in original.index
            ]
            for coluna in original.columns
        },
        index=original.index,
    )
    formatada.index.name = "Indicador"
    linhas.append(_tabela_markdown(formatada))
    linhas += [
        "",
        "**O ROE sai sobre o patrimônio médio do ano**, e não sobre o de "
        "fechamento: uma instituição que capitalizou no meio do ano apareceria "
        "menos rentável do que foi.",
    ]
    return linhas


def _qualitativo_do_banco(vrio, respostas=None) -> list[str]:
    """VRIO com a serie que vale para instituicao financeira.

    O relatorio do banco deixava as perguntas de framework **inteiramente** de
    fora, e a razao era boa -- margem EBITDA e capex nao descrevem um banco. Mas
    a pergunta do fosso num banco e *a* pergunta, e o app ja calculava o que a
    sustenta: ROE contra Ke, persistencia e o beta de indiferenca.

    Some quando nao ha o historico do banco: sem ROE nao ha o que perguntar, e
    um cabecalho com quatro blocos vazios diria que a analise foi feita.
    """
    if not vrio:
        return []
    linhas = [
        "## VRIO — o que vale para uma instituição financeira",
        "",
        "As mesmas quatro perguntas, com **ROE contra Ke** no lugar de margem e "
        "capex. Raridade fica **sem número**: são 19 instituições na base "
        "medida, e quantil sobre 19 é ruído.",
        "",
    ]
    return linhas + _blocos_de_evidencia(vrio, respostas)


def _nao_se_aplica_ao_banco() -> list[str]:
    """O que o relatório deixou de fora por não valer para instituição financeira.

    Duas seções descreviam outra companhia que não a avaliada:

    * a **evidência qualitativa** cita percentis da base de pares, e o universo
      de comparáveis **exclui bancos e seguradoras** de propósito — margem EBITDA
      e capex sobre receita não querem dizer neles o que querem dizer no resto.
      Comparar contra 445 companhias a que a instituição não pertence produz um
      percentil que parece informação e não é;
    * o **diagnóstico automático** roda sobre o DCF, e o DCF não foi usado. Ele
      chegava a reclamar de "margem EBITDA projetada abaixo do pior ano
      histórico" num modelo que não projeta margem nenhuma.

    Omitir em silêncio seria pior: quem lê precisa distinguir "foi verificado e
    está bem" de "não foi verificado".
    """
    return [
        "## O que não foi avaliado aqui",
        "",
        "Duas seções que este relatório traz para empresa não financeira ficaram "
        "de fora, porque descreveriam outra companhia — as perguntas de VRIO "
        "**não** estão entre elas: elas aparecem acima, com ROE contra Ke no "
        "lugar dos indicadores industriais.",
        "",
        "- **Comparação com pares** — o universo de comparáveis exclui bancos e "
        "seguradoras de propósito: margem EBITDA e capex sobre receita não querem "
        "dizer neles o que querem dizer no resto. Um percentil contra companhias "
        "a que esta instituição não pertence parece informação e não é.",
        "- **Diagnóstico automático do modelo** — ele verifica a coerência do DCF, "
        "e o DCF não foi usado. As verificações que valeriam aqui seriam sobre "
        "capital regulatório e composição da carteira, que este app não faz.",
        "",
        "O que **foi** verificado está nas seções acima: a leitura das "
        "demonstrações contra o arquivo publicado, e a aritmética do lucro "
        "residual ano a ano.",
    ]


def _expectativas(
    expectativas: pd.DataFrame | None, margem: MargemDeSeguranca | None
) -> list[str]:
    if expectativas is None or margem is None:
        return [
            "## O que o preço embute",
            "",
            "**Não avaliado** — nenhum preço de mercado foi informado.",
        ]

    tabela = expectativas.drop(columns=["caminho"], errors="ignore").copy()
    formatada = tabela.map(lambda v: _pct(v, 2) if isinstance(v, float) else v)
    formatada.index.name = "Premissa"

    linhas = [
        "## O que o preço embute",
        "",
        f"Preço considerado: {_num(margem.preco, 2)}. Valor calculado: "
        f"{_num(margem.valor, 2)}. Margem sobre o valor: {_pct(margem.margem)}.",
        "",
        "O DCF ao contrário: para cada premissa, o valor que faria o modelo dar "
        "exatamente o preço pedido. Serve para trocar *“acho caro”* por uma "
        "afirmação que dá para checar.",
        "",
        _tabela_markdown(formatada),
    ]

    validos = tabela.dropna(subset=["Diferença"]) if "Diferença" in tabela else tabela
    if not validos.empty and "Diferença" in validos:
        apertada = validos["Diferença"].abs().idxmin()
        diferenca = validos.loc[apertada, "Diferença"]
        linhas += [
            "",
            f"A premissa com menos folga é **{apertada}**: "
            f"{_pct(abs(diferenca), 2)} de distância entre o que o modelo assume e o "
            "que o preço embute. É de lá que vem o risco desta tese.",
        ]
    return linhas


def _qualitativo(evidencias, respostas=None) -> list[str]:
    """As perguntas de framework, com a evidencia medida e o campo em branco.

    A secao existe para nao fazer o oposto do que o projeto se propoe. Escrever
    "vantagem competitiva solida" a partir de um ROIC alto seria inventar; nao
    ter a secao faria o relatorio parecer que a pergunta nao importa. Entao a
    maquina traz o que mediu e para onde o julgamento comeca.
    """
    if not evidencias:
        return [
            "## As perguntas que os números não respondem",
            "",
            "**Sem histórico importado**, não há evidência quantitativa para "
            "sustentar nenhuma das perguntas de framework.",
        ]

    linhas = [
        "## As perguntas que os números não respondem",
        "",
        "Cada bloco traz a pergunta, o que foi **medido** sobre ela e o que os "
        "dados não alcançam. A resposta fica em branco de propósito: é a parte "
        "que exige julgamento, e nenhuma conta deste relatório a substitui.",
        "",
        # **O total, e não só a marca por bloco.** Cada pergunta já diz "(não
        # respondida)", mas quem abre o documento no meio não sabe se encontrou
        # a única em branco ou uma de dez. E este é o número que mede o quanto do
        # material está pronto: o resto o app calcula sozinho.
        _quanto_respondido(respostas),
        "",
    ]
    return linhas + _blocos_de_evidencia(evidencias, respostas)


# As dez perguntas de framework: cinco forcas, fosso e as quatro do VRIO.
PERGUNTAS_DE_FRAMEWORK = 10


def _quanto_respondido(respostas) -> str:
    """Uma linha dizendo quanto do julgamento ja foi escrito."""
    feitas = len([v for v in (respostas or {}).values() if str(v).strip()])
    if feitas == 0:
        return (
            f"> **Nenhuma das {PERGUNTAS_DE_FRAMEWORK} perguntas foi respondida.** "
            "O que segue é a evidência reunida, e não a análise."
        )
    if feitas < PERGUNTAS_DE_FRAMEWORK:
        return (
            f"> **{feitas} de {PERGUNTAS_DE_FRAMEWORK} perguntas respondidas.** As "
            "demais aparecem marcadas como não respondidas."
        )
    return f"> As {PERGUNTAS_DE_FRAMEWORK} perguntas foram respondidas."


def _blocos_de_evidencia(evidencias, respostas=None) -> list[str]:
    """Um bloco por pergunta. Compartilhado por Porter e VRIO -- as duas secoes
    tem cabecalho proprio e o mesmo corpo, e fatiar a lista da outra por indice
    quebraria no dia em que o cabecalho mudasse de tamanho."""
    linhas: list[str] = []
    for evidencia in evidencias:
        linhas.append(f"### {evidencia.tema}")
        linhas.append("")
        linhas.append(f"*{evidencia.pergunta}*")
        linhas.append("")
        for item in evidencia.medido:
            linhas.append(f"- {item}")
        if evidencia.medido:
            linhas.append("")
        if evidencia.limite:
            linhas.append(f"**O que os dados não dizem:** {evidencia.limite}")
            linhas.append("")
        linhas.append("**Leitura do analista:**")
        linhas.append("")
        # A resposta escrita na tela de Qualitativo entra aqui. Quando nao ha,
        # o campo continua em branco e **diz que esta em branco**: um relatorio
        # em que a ausencia se parece com um paragrafo vazio deixa o leitor sem
        # saber se a pergunta foi considerada e dispensada, ou nao foi lida.
        resposta = (respostas or {}).get(evidencia.tema, "").strip()
        if resposta:
            for paragrafo in resposta.splitlines():
                linhas.append(f"> {paragrafo}" if paragrafo.strip() else ">")
        else:
            linhas.append("> *(não respondida)*")
        linhas.append("")
    return linhas


def _qualitativo_vrio(vrio, respostas=None) -> list[str]:
    """As quatro de Barney, reusando a mesma peca das cinco forcas.

    Secao propria porque a pergunta e outra -- Porter olha a **estrutura do
    setor**, VRIO olha o **recurso da empresa** --, e misturar as dez num bloco
    so faria o leitor tratar as duas leituras como uma lista de dez itens.
    """
    if not vrio:
        return []
    linhas = [
        "## VRIO — o recurso, e não o setor",
        "",
        "As quatro perguntas de Barney. **Não há nota**: pontuar de 1 a 5 "
        "converteria julgamento em medida. Imitabilidade é a que os dados menos "
        "alcançam, e o bloco dela diz isso.",
        "",
    ]
    return linhas + _blocos_de_evidencia(vrio, respostas)


def _riscos(diagnostico: Diagnostico | None) -> list[str]:
    if diagnostico is None:
        return ["## O que pode dar errado", "", "**Diagnóstico não executado.**"]

    if not len(diagnostico):
        return [
            "## O que pode dar errado",
            "",
            "O diagnóstico automático não encontrou nenhum achado. Isso significa "
            "que o modelo é internamente consistente — não que as premissas estejam "
            "certas.",
        ]

    linhas = ["## O que pode dar errado", ""]
    graves = len(diagnostico.erros)
    alertas = len(diagnostico.alertas)
    informacoes = len(diagnostico.achados) - graves - alertas
    # Contar so erros e alertas faria a frase dizer "0 e 0" logo acima de dois
    # achados listados, que e o tipo de contradicao que derruba a confianca no
    # documento inteiro.
    contagens = [
        f"{graves} erro(s)",
        f"{alertas} alerta(s)",
        f"{informacoes} observação(ões)",
    ]
    linhas.append("Diagnóstico automático: " + ", ".join(contagens) + ".")
    linhas.append("")
    for achado in diagnostico.achados:
        linhas.append(f"### {achado.icone} {achado.titulo}")
        linhas.append("")
        linhas.append(achado.detalhe)
        if achado.acao:
            linhas.append("")
            linhas.append(f"**O que fazer:** {achado.acao}")
        if achado.referencia:
            linhas.append("")
            linhas.append(f"*{achado.referencia}*")
        linhas.append("")
    return linhas


def _limites(resultado: ResultadoValuation, analise, qualidade) -> list[str]:
    """A secao que impede o relatorio de parecer mais do que e."""
    linhas = [
        "## O que este relatório não faz",
        "",
        "- **Não avalia o negócio.** Vantagem competitiva, qualidade da gestão, "
        "regulação e concorrência não entram em nenhuma conta aqui. Um modelo "
        "consistente sobre uma tese errada continua errado.",
        "- **Não valida as premissas.** O diagnóstico verifica coerência interna "
        "— se o crescimento cabe na economia, se o reinvestimento sustenta o "
        "crescimento — e não se a premissa vai se realizar.",
        # Este item dizia que os cortes eram "faixas de mercado arbitradas, ainda
        # nao calibradas contra a base da CVM". Deixou de ser verdade: conversao
        # de caixa, alavancagem, arrendamento e peso do nao recorrente foram
        # medidos nas 467 companhias. O relatorio e o entregavel final, e texto
        # velho ali vira afirmacao falsa sobre o proprio trabalho.
        "- **Os cortes de leitura são quartis medidos, e não convenção** — "
        "conversão de caixa, alavancagem, peso do arrendamento e do não "
        "recorrente saem da distribuição das companhias com DFP consolidada. Os "
        "que ainda não foram calibrados são a margem de segurança exigida e o "
        "spread mínimo entre WACC e g, que continuam sendo escolha do analista.",
        "- **Betas e prêmio de risco-país são valores de referência**, de ordem "
        "de grandeza, e não a base oficial do Damodaran. Onde o beta carrega o "
        "resultado sozinho — instituição financeira —, a seção de valor mostra "
        "qual beta inverteria a conclusão.",
    ]
    if analise is None:
        linhas.append(
            "- **Sem histórico importado**, nada aqui está ancorado no que a empresa "
            "entregou."
        )
    if qualidade is None and analise is not None:
        linhas.append(
            "- **Qualidade dos lucros não avaliada** — faltam dados de fluxo de caixa."
        )
    if resultado.empresa.perpetuidade.metodo == "gordon":
        if resultado.dcf.peso_perpetuidade > 0.75:
            linhas.append(
                f"- **{_pct(resultado.dcf.peso_perpetuidade)} do valor está na "
                "perpetuidade**, que depende de duas premissas e não das projetadas "
                "ano a ano."
            )
    return linhas


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------


def montar(
    resultado: ResultadoValuation,
    analise=None,
    qualidade=None,
    diagnostico: Diagnostico | None = None,
    margem: MargemDeSeguranca | None = None,
    expectativas: pd.DataFrame | None = None,
    evidencias=None,
    vrio=None,
    investimento=None,
    respostas_qualitativas=None,
    ifrs16=None,
    lucro_residual=None,
    historico_do_banco=None,
    vrio_do_banco=None,
    data: str = "",
) -> str:
    """Monta o relatorio completo em markdown.

    Tudo alem de ``resultado`` e opcional, e a ausencia de cada peca aparece no
    texto em vez de sumir dele.

    ``evidencias`` vem de ``qualitativo.reunir_evidencias``. Elas nao respondem
    as perguntas de framework -- reunem o que os numeros dizem sobre cada uma e
    deixam a resposta para quem le.

    ``lucro_residual`` troca a secao de valor pela do modelo de banco. Quando ele
    vem, **as secoes do DCF saem**: descrever um Enterprise Value, um WACC e uma
    ponte que ninguem calculou contradiria a tela em que o numero foi visto, e o
    relatorio e justamente o que sobra depois que a tela fecha.
    """
    if lucro_residual is not None:
        blocos = [
            _cabecalho(resultado, data),
            _lucro_residual(lucro_residual),
            _historico_do_banco(historico_do_banco)
            if historico_do_banco is not None
            else _historico(analise),
            _qualidade(qualidade, analise),
            _qualitativo_do_banco(vrio_do_banco, respostas_qualitativas),
            _nao_se_aplica_ao_banco(),
            _limites(resultado, analise, qualidade),
        ]
        return "\n\n".join("\n".join(bloco) for bloco in blocos) + "\n"

    blocos = [
        _cabecalho(resultado, data),
        _resumo(resultado, margem),
        _historico(analise),
        _qualidade(qualidade, analise),
        _investimento(investimento),
        _ciclo_de_caixa(analise),
        _ifrs16(ifrs16),
        _premissas(resultado),
        _ponte(resultado),
        _expectativas(expectativas, margem),
        _qualitativo(evidencias, respostas_qualitativas),
        _qualitativo_vrio(vrio, respostas_qualitativas),
        _riscos(diagnostico),
        _limites(resultado, analise, qualidade),
    ]
    return "\n\n".join("\n".join(bloco) for bloco in blocos) + "\n"


def sumario(diagnostico: Diagnostico | None) -> str:
    """Uma linha sobre o estado do modelo, para cabecalho de tela."""
    if diagnostico is None:
        return "Diagnóstico não executado."
    graves = [a for a in diagnostico.achados if a.severidade == ERRO]
    alertas = [a for a in diagnostico.achados if a.severidade == ALERTA]
    if graves:
        return f"{len(graves)} erro(s) a resolver antes de defender o número."
    if alertas:
        return f"Sem erros graves, {len(alertas)} alerta(s) a justificar."
    return "Modelo internamente consistente."
