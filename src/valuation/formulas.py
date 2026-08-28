"""A formula de cada indicador, e a convencao que ela escolheu.

**Ha varios jeitos de chegar no ROIC**, e eles nao dao o mesmo numero. O
denominador pode ser capital de abertura, de fechamento ou medio; o numerador
pode usar aliquota nominal ou efetiva; o capital investido pode incluir ou nao o
caixa. Um app que mostra "ROIC: 34,0%" sem dizer qual dos jeitos usou obriga o
analista a confiar ou a reimplementar a conta -- e as duas coisas sao piores que
mostrar a formula.

Este modulo e a resposta escrita. Cada indicador traz:

* ``formula`` -- a conta, nos nomes das contas da demonstracao;
* ``convencao`` -- **a escolha que a formula embute**, quando ha mais de um
  caminho defensavel. E aqui que mora a informacao: a formula sozinha nao diz
  que o capital e o medio *porque* o CFA manda, nem que a aliquota e a efetiva
  *porque* ela descreve o caixa que a empresa entrega.

Fica no motor, e nao na tela, porque e a descricao do que o motor calcula: se a
conta mudar em ``historico.py`` e o texto ficar aqui desatualizado, o app passa
a mentir com confianca. Ha teste ligando os dois -- todo indicador publicado
precisa de verbete.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Formula:
    """Como um indicador e calculado, e o que essa escolha implica."""

    formula: str
    convencao: str = ""


# A ordem segue a de ``AnaliseHistorica.indicadores``, para a tela poder
# percorrer as duas juntas.
FORMULAS: dict[str, Formula] = {
    # -- Crescimento e margens ------------------------------------------------
    "Crescimento da receita": Formula(
        "Receita líquida ÷ Receita líquida do ano anterior − 1"
    ),
    "Margem bruta": Formula("(Receita líquida − Custos) ÷ Receita líquida"),
    "Margem EBITDA": Formula(
        "EBITDA ÷ Receita líquida",
        "EBITDA = EBIT + D&A, com a **D&A da DFC** e não a da DRE. A da DRE mora "
        "dentro de despesas gerais e administrativas e captura só a depreciação "
        "que correu pelo SG&A — numa indústria, a maior parte corre pelo CPV e "
        "ficaria de fora.",
    ),
    "Margem EBIT": Formula("EBIT ÷ Receita líquida"),
    "Margem NOPAT": Formula("NOPAT ÷ Receita líquida"),
    "Margem liquida": Formula("Lucro líquido ÷ Receita líquida"),
    "Aliquota efetiva de IR": Formula(
        "Impostos sobre o lucro ÷ LAIR, limitado a [0, 100%]",
        "É a alíquota que a companhia de fato pagou, e costuma ficar abaixo dos "
        "34% nominais por incentivos, JCP e subvenções.",
    ),
    # -- Retorno e sua decomposicao -------------------------------------------
    "Giro do ativo": Formula("Receita líquida ÷ Ativo total médio"),
    "Alavancagem financeira": Formula("Ativo total médio ÷ Patrimônio líquido médio"),
    "ROE": Formula(
        "Lucro líquido ÷ Patrimônio líquido médio",
        "Patrimônio **médio** entre abertura e fechamento, e não o de "
        "fechamento: o lucro foi ganho ao longo do ano, sobre o capital que "
        "esteve empregado durante ele.",
    ),
    "Giro do capital investido": Formula("Receita líquida ÷ Capital investido médio"),
    "ROIC": Formula(
        "NOPAT ÷ Capital investido médio, onde\n\n"
        "- **NOPAT** = EBIT × (1 − alíquota efetiva de IR)\n"
        "- **Capital investido** = Dívida líquida + Patrimônio líquido\n"
        "- **Capital médio** = (saldo de abertura + saldo de fechamento) ÷ 2",
        "Três escolhas, e cada uma muda o número:\n\n"
        "1. **Alíquota efetiva, não os 34% nominais.** A nominal descreve a lei; "
        "a efetiva descreve o caixa que a empresa entrega. Quando o histórico "
        "não permite calculá-la, o app cai nos 34%.\n"
        "2. **Capital investido pela ótica do financiamento** — dívida líquida "
        "mais patrimônio —, e não pela do ativo operacional. As duas chegam ao "
        "mesmo lugar quando o balanço fecha, e esta usa contas que a CVM "
        "padroniza.\n"
        "3. **Capital médio, não o de fechamento.** É o que o CFA manda: o "
        "retorno foi gerado sobre o capital que esteve empregado no ano. Usar o "
        "de fechamento infla o ROIC de quem encolheu e deprime o de quem "
        "investiu no fim do exercício.\n\n"
        "É por isso que este ROIC pode não bater com o de um terminal: "
        "provavelmente ele escolheu diferente em pelo menos uma das três.",
    ),
    # -- Reinvestimento -------------------------------------------------------
    "Capex / Receita": Formula("Capex ÷ Receita líquida"),
    "Depreciacao / Receita": Formula("D&A ÷ Receita líquida"),
    "Capex / Depreciacao": Formula(
        "Capex ÷ D&A",
        "Abaixo de 1x por vários anos, a empresa não está repondo o ativo que "
        "consome — e entra na perpetuidade com uma base menor do que a que "
        "gerou o resultado projetado.",
    ),
    "Reinvestimento": Formula(
        "(Capex − D&A) + Variação do capital de giro",
        "É o capital novo que a operação exigiu: o que passou da reposição, "
        "mais o que ficou preso no giro.",
    ),
    "Taxa de reinvestimento": Formula("Reinvestimento ÷ NOPAT"),
    "Crescimento fundamentado (reinvest. x ROIC)": Formula(
        "Taxa de reinvestimento × ROIC",
        "O crescimento que o próprio reinvestimento sustenta. Comparado com o "
        "crescimento observado, diz se a receita cresceu por capital novo ou "
        "por ganho de eficiência.",
    ),
    # -- Capital de giro e ciclo ----------------------------------------------
    "Capital de giro / Receita": Formula(
        "(Contas a receber + Estoques − Fornecedores) ÷ Receita líquida",
        "Só as três contas operacionais. Caixa e dívida de curto prazo ficam de "
        "fora porque já entram na ponte de valor — incluí-los os contaria duas "
        "vezes.",
    ),
    "Prazo medio de recebimento (dias)": Formula(
        "Contas a receber × 365 ÷ Receita líquida"
    ),
    "Prazo medio de estoque (dias)": Formula("Estoques × 365 ÷ Custos"),
    "Prazo medio de pagamento (dias)": Formula("Fornecedores × 365 ÷ Custos"),
    # -- Estrutura de capital -------------------------------------------------
    "Divida liquida / EBITDA": Formula(
        "(Dívida bruta − Caixa − Aplicações financeiras) ÷ EBITDA",
        "A dívida bruta inclui o arrendamento do IFRS 16 — inclusive quando a "
        "companhia o publica fora da subárvore de empréstimos, o que 190 das "
        "467 companhias de 2024 fazem. Se você comparar com um EBITDA "
        "ex-IFRS 16, use a dívida ex-arrendamento também: cruzar as duas "
        "leituras infla a alavancagem.",
    ),
    "Divida bruta / Patrimonio liquido": Formula(
        "Dívida bruta ÷ Patrimônio líquido"
    ),
    "Custo da divida efetivo": Formula(
        "Despesas financeiras ÷ Dívida bruta média",
        "É por **competência**, e costuma superestimar o custo: a linha da CVM "
        "junta variação cambial e monetária de todo o passivo. Para o WACC o "
        "app usa o juro **pago** da DFC, que é o de baixo.",
    ),
    # -- Contraprova de caixa -------------------------------------------------
    "Conversao operacional (CGO / EBITDA)": Formula(
        "Caixa gerado pelas operações ÷ EBITDA",
        "Mede **a operação**: é o EBITDA depois de se realizar em caixa, antes "
        "de capital de giro, imposto e juro. Medido em 374 companhias de 2024, "
        "a mediana da base converte 105,9% — passa de 100% porque o caixa "
        "gerado devolve ao lucro despesas que não foram caixa e o EBITDA não "
        "captura, como provisão e impairment.",
    ),
    "Conversao de caixa (FCO / EBITDA)": Formula(
        "Fluxo de caixa operacional ÷ EBITDA",
        "Mede **o que sobra**: é líquido de capital de giro, imposto de renda e "
        "juros pagos. Mediana da base em 59,2%, contra 105,9% da conversão "
        "operacional — os 42,4 pontos de diferença não falam da operação. O "
        "juro pago sozinho vale 25,8% do EBITDA na mediana.",
    ),
    "Capex / FCO": Formula("Capex ÷ Fluxo de caixa operacional"),
    "Fluxo de caixa livre (FCO - capex)": Formula(
        "Fluxo de caixa operacional − Capex"
    ),
    "Custo da divida pelo caixa": Formula(
        "Juros pagos (DFC) ÷ Dívida bruta média",
        "É este que alimenta o WACC. O app traz para o operacional o juro que a "
        "companhia classificou no financiamento — 121 das 467 companhias de "
        "2024 o classificam lá —, senão duas empresas idênticas teriam números "
        "diferentes só pela apresentação.",
    ),
    "Investimento em giro (DFC) / Receita": Formula(
        "− Variação do capital de giro (DFC) ÷ Receita líquida",
        "Sinal invertido para ler como os demais: positivo significa que o giro "
        "consumiu caixa. Sai da DFC, e não da variação dos saldos do balanço, "
        "depois de tirar dali imposto e juro pagos que muitas companhias lançam "
        "dentro da seção de variações.",
    ),
    "Payout (dividendos / lucro)": Formula(
        "Dividendos pagos (DFC) ÷ Lucro líquido",
        "Sai do caixa que saiu, e não do que foi declarado: dividendo aprovado "
        "e não pago ainda não remunerou ninguém. Inclui JCP, que no Brasil é "
        "dividendo com outro nome fiscal.",
    ),
    "Arrendamento / Divida bruta": Formula(
        "(Arrendamento de curto prazo + de longo prazo) ÷ Dívida bruta",
        "Quanto da dívida é IFRS 16. Acima de 20% — o quartil superior da base "
        "—, a leitura ex-IFRS 16 muda materialmente a alavancagem.",
    ),
    "Margem EBIT recorrente": Formula(
        "(EBIT − Impairment − Outras receitas op. − Outras despesas op.) ÷ Receita líquida",
        "Com o **sinal publicado**, não com a magnitude: reversão entra "
        "positiva, perda entra negativa, e a subtração cuida dos dois casos. A "
        "equivalência patrimonial fica **fora** da subtração — para uma holding "
        "ela é o negócio, e excluí-la por padrão acertaria numa e erraria na "
        "outra.",
    ),
    "Margem EBITDA recorrente": Formula(
        "(EBITDA − Impairment − Outras receitas op. − Outras despesas op.) ÷ Receita líquida",
        "É esta que alimenta a margem sugerida na projeção, e não a reportada. "
        "O ajuste vai nos dois sentidos: na Vale o item foi impairment e a "
        "recorrente é **maior**; na CESP foi ganho e é menor.",
    ),
    "Itens nao recorrentes / EBIT": Formula(
        "(Impairment + Outras receitas op. + Outras despesas op.) ÷ EBIT",
        "Os três códigos que a CVM padroniza — `3.04.03`, `3.04.04` e "
        "`3.04.05`. O que a companhia chama de não recorrente no próprio "
        "release costuma ser maior: reestruturação e despesa de M&A moram "
        "dentro do SG&A e não têm código próprio.",
    ),
    "Ciclo de conversao de caixa (dias)": Formula(
        "Prazo de recebimento + Prazo de estoque − Prazo de pagamento",
        "Quantos dias o caixa fica preso entre pagar o fornecedor e receber do "
        "cliente. Negativo significa que o fornecedor financia a operação.",
    ),
    # -- Liquidez -------------------------------------------------------------
    "Liquidez corrente": Formula("Ativo circulante ÷ Passivo circulante"),
    "Liquidez seca": Formula(
        "(Ativo circulante − Estoques) ÷ Passivo circulante",
        "Tira o estoque porque ele é o circulante que menos se converte em "
        "caixa no prazo.",
    ),
    "Liquidez imediata": Formula(
        "(Caixa + Aplicações financeiras) ÷ Passivo circulante"
    ),
    "FCO / Passivo circulante": Formula(
        "Fluxo de caixa operacional ÷ Passivo circulante",
        "Mede solvência sem depender de estoque virar caixa no prazo. Alto com "
        "liquidez corrente baixa, os dois estão certos: a operação paga o que o "
        "balanço não cobre.",
    ),
    "Caixa / Divida de curto prazo": Formula(
        "(Caixa + Aplicações financeiras) ÷ Dívida de curto prazo"
    ),
    "Divida de curto prazo / Divida bruta": Formula(
        "Dívida de curto prazo ÷ Dívida bruta"
    ),
}


def formula(indicador: str) -> Formula | None:
    """A formula de um indicador, ou ``None`` se ele nao tem verbete."""
    return FORMULAS.get(indicador)


# ---------------------------------------------------------------------------
# O nome do indicador quando ele vai para os olhos de alguem
# ---------------------------------------------------------------------------

# **A chave do indicador e identificador de codigo; o rotulo e texto de usuario.**
# As duas eram a mesma string, e ela chegava crua a tela e ao texto que o motor
# escreve: "Prazo medio", "Divida liquida", "Aliquota efetiva", "Conversao de
# caixa". Num app inteiro em portugues acentuado, essas linhas denunciavam a
# convencao do codigo vazando para a interface.
#
# A traducao acontece aqui e **nao renomeando as chaves**: elas sao usadas em
# `referencias.BASE`, nos verbetes acima, em `pares.DIMENSOES` e nos projetos
# salvos em disco -- renomea-las quebraria valuation guardado, para ganhar um
# acento.
#
# Mora no motor porque o nome nao vai so a tela: a evidencia qualitativa escreve
# "Conversao de caixa de 55%" no proprio texto, e o relatorio e a CLI tambem.
# Uma copia na camada de apresentacao divergiria desta na primeira mudanca.
#
# Entradas so para o que muda: indicador cujo nome ja esta certo (Margem EBITDA,
# ROIC, Liquidez corrente) nao aparece aqui, e `rotulo_do_indicador` o devolve
# como veio.
ROTULOS_DE_INDICADOR = {
    "Margem liquida": "Margem líquida",
    "Aliquota efetiva de IR": "Alíquota efetiva de IR",
    "Depreciacao / Receita": "Depreciação / Receita",
    "Capex / Depreciacao": "Capex / Depreciação",
    "Prazo medio de recebimento (dias)": "Prazo médio de recebimento (dias)",
    "Prazo medio de estoque (dias)": "Prazo médio de estoque (dias)",
    "Prazo medio de pagamento (dias)": "Prazo médio de pagamento (dias)",
    "Divida liquida / EBITDA": "Dívida líquida / EBITDA",
    "Divida liquida / EBITDA (ex-IFRS 16)": "Dívida líquida / EBITDA (ex-IFRS 16)",
    "Divida bruta / Patrimonio liquido": "Dívida bruta / Patrimônio líquido",
    "Custo da divida efetivo": "Custo da dívida efetivo",
    "Custo da divida pelo caixa": "Custo da dívida pelo caixa",
    "Divida de curto prazo / Divida bruta": "Dívida de curto prazo / Dívida bruta",
    "Caixa / Divida de curto prazo": "Caixa / Dívida de curto prazo",
    "Conversao operacional (CGO / EBITDA)": "Conversão operacional (CGO / EBITDA)",
    "Conversao de caixa (FCO / EBITDA)": "Conversão de caixa (FCO / EBITDA)",
    "Investimento em giro (DFC) / Receita": "Investimento em giro (DFC) / Receita",
    "Arrendamento / Divida bruta": "Arrendamento / Dívida bruta",
    "Ciclo de conversao de caixa (dias)": "Ciclo de conversão de caixa (dias)",
    "Margem EBIT recorrente": "Margem EBIT recorrente",
    "Itens nao recorrentes / EBIT": "Itens não recorrentes / EBIT",
    "Margem EBITDA recorrente": "Margem EBITDA recorrente",
    "Aluguel / EBITDA": "Aluguel / EBITDA",
    "Margem EBITDA (ex-IFRS 16)": "Margem EBITDA (ex-IFRS 16)",
    "Margem EBIT (ex-IFRS 16)": "Margem EBIT (ex-IFRS 16)",
}


def rotulo_do_indicador(chave: str) -> str:
    """O nome do indicador como ele deve aparecer na tela."""
    return ROTULOS_DE_INDICADOR.get(str(chave), str(chave))


def rotulo_do_indicador(chave: str) -> str:
    """O nome do indicador como ele deve aparecer para quem le."""
    return ROTULOS_DE_INDICADOR.get(str(chave), str(chave))
