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

from .diagnostico import ALERTA, ERRO, Diagnostico
from .margem import MargemDeSeguranca
from .modelo import ResultadoValuation

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


def _pct(valor: float | None, casas: int = 1) -> str:
    if valor is None or not np.isfinite(valor):
        return "n/d"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _num(valor: float | None, casas: int = 1) -> str:
    if valor is None or not np.isfinite(valor):
        return "n/d"
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


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


def _qualidade(qualidade) -> list[str]:
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
    return linhas


def _premissas(resultado: ResultadoValuation) -> list[str]:
    empresa = resultado.empresa
    op = empresa.operacionais
    perp = empresa.perpetuidade
    macro = empresa.macro

    anos = [str(op.ano_base + i + 1) for i in range(op.horizonte)]
    quadro = pd.DataFrame(
        {
            "Crescimento da receita": [_pct(v) for v in op.crescimento_receita],
            "Margem EBITDA": [_pct(v) for v in op.margem_ebitda],
            "Capex / receita": [_pct(v) for v in op.capex_pct_receita],
            "Capital de giro / receita": [_pct(v) for v in op.capital_giro_pct_receita],
        },
        index=anos,
    )
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
        linhas.append(
            f"- **Perpetuidade por múltiplo de saída**: {_num(perp.multiplo_saida, 1)}x "
            "EV/EBITDA sobre o último ano projetado."
        )

    cc = resultado.custo_capital
    p = empresa.custo_capital
    linhas += [
        "",
        "### Custo de capital",
        "",
        f"- Ke em USD: {_pct(p.rf_usd, 2)} (livre de risco) + "
        f"{_num(cc.beta_realavancado, 2)} × {_pct(p.erp_maduro, 2)} (prêmio de "
        f"mercado) + {_pct(p.lambda_pais * p.risco_pais, 2)} (risco-país) = "
        f"{_pct(cc.ke_usd, 2)}.",
        f"- Convertido para moeda local pelo diferencial de inflação "
        f"({_pct(macro.inflacao_brl)} contra {_pct(macro.inflacao_usd)}): "
        f"Ke de {_pct(cc.ke_brl, 2)}.",
        f"- Kd após imposto: {_pct(cc.kd_liquido_brl, 2)}. WACC: "
        f"{_pct(cc.wacc_brl, 2)}, com {_pct(cc.peso_equity)} de capital próprio.",
    ]
    return linhas


def _ponte(resultado: ResultadoValuation) -> list[str]:
    tabela = resultado.tabela_ponte().copy()
    coluna = tabela.columns[0]
    tabela[coluna] = tabela[coluna].map(lambda v: _num(v, 1))
    if tabela.index.name is None:
        tabela.index.name = "Item"
    return ["## Do Enterprise Value ao Equity Value", "", _tabela_markdown(tabela)]


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


def _qualitativo(evidencias) -> list[str]:
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
    ]
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
        linhas.append("> ")
        linhas.append("")
    return linhas


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
        "- **Os cortes de leitura são convenção.** Conversão de caixa de 90% e "
        "60%, margem exigida de 30%, spread mínimo de 2 p.p. entre WACC e g: são "
        "faixas de mercado arbitradas, ainda não calibradas contra a base da CVM.",
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
    data: str = "",
) -> str:
    """Monta o relatorio completo em markdown.

    Tudo alem de ``resultado`` e opcional, e a ausencia de cada peca aparece no
    texto em vez de sumir dele.

    ``evidencias`` vem de ``qualitativo.reunir_evidencias``. Elas nao respondem
    as perguntas de framework -- reunem o que os numeros dizem sobre cada uma e
    deixam a resposta para quem le.
    """
    blocos = [
        _cabecalho(resultado, data),
        _resumo(resultado, margem),
        _historico(analise),
        _qualidade(qualidade),
        _premissas(resultado),
        _ponte(resultado),
        _expectativas(expectativas, margem),
        _qualitativo(evidencias),
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
