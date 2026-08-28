"""Pecas de interface reutilizadas pelas telas."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .textos import CONCEITOS


_NEGRITO = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALICO = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)", re.DOTALL)
_CODIGO = re.compile(r"`([^`]+?)`")


def _markdown_para_html(texto: str) -> str:
    """Converte a marcacao usada nos textos para HTML.

    Necessario porque o bloco de conceito e uma ``<div>`` propria, e o Streamlit
    nao interpreta markdown dentro de HTML cru -- sem isto os asteriscos
    apareceriam literais na tela.
    """
    texto = _NEGRITO.sub(r"<strong>\1</strong>", texto)
    texto = _ITALICO.sub(r"<em>\1</em>", texto)
    return _CODIGO.sub(r"<code>\1</code>", texto)


def conceito(chave: str, titulo: str = "") -> None:
    """Bloco explicativo de um conceito, sempre no mesmo formato.

    Fica visivel por padrao em vez de escondido atras de um clique: a parte
    educacional do app so funciona se o texto estiver no caminho do olho.
    """
    texto = CONCEITOS.get(chave)
    if not texto:
        return
    prefixo = f"<strong>{titulo}</strong><br>" if titulo else ""
    st.markdown(
        f'<div class="bloco-conceito">{prefixo}{_markdown_para_html(texto)}</div>',
        unsafe_allow_html=True,
    )


def etapa(rotulo: str, titulo: str, subtitulo: str = "") -> None:
    """Cabecalho padrao de tela."""
    st.markdown(f'<div class="rotulo-etapa">{rotulo}</div>', unsafe_allow_html=True)
    st.title(titulo)
    if subtitulo:
        st.caption(subtitulo)


def secao(titulo: str, descricao: str = "") -> None:
    """Cabecalho de bloco dentro de uma tela, sempre no mesmo formato.

    As telas usavam ``st.subheader``, ``st.markdown("**...**")`` e texto solto
    para a mesma coisa, e o resultado era que "e um titulo de secao" nao tinha
    uma aparencia -- tinha tres. Uma so torna a tela escaneavel: o olho aprende
    o padrao uma vez e passa a achar o comeco de cada bloco sem ler.
    """
    st.markdown(
        f'<div class="titulo-secao">{titulo}</div>', unsafe_allow_html=True
    )
    if descricao:
        st.caption(descricao)


def cartoes(
    itens: list[tuple[str, str]] | list[tuple[str, str, str]],
    colunas: int | None = None,
) -> None:
    """Uma fila de cartoes de indicador: rotulo, numero e ajuda opcional.

    O numero que decide a tela estava saindo como texto solto numa linha de
    colunas -- mesmo peso visual de uma legenda, sem moldura, sem separacao. E o
    padrao que todo terminal financeiro resolve do mesmo jeito, porque funciona:
    **cartao com borda**, rotulo pequeno em cima, numero grande embaixo. O olho
    acha o numero sem ler o rotulo.

    Cada item e ``(rotulo, valor)`` ou ``(rotulo, valor, ajuda)``. O valor ja vem
    formatado -- quem chama sabe se aquilo e moeda, percentual ou multiplo.
    """
    if not itens:
        return
    faixas = st.columns(colunas or len(itens))
    for faixa, item in zip(faixas, itens):
        rotulo, valor = item[0], item[1]
        ajuda = item[2] if len(item) > 2 else None
        faixa.metric(rotulo, valor, help=ajuda, border=True)


def proximo_passo(chave: str, pronto: bool = True, motivo: str = "") -> None:
    """Rodape com o caminho: de onde se veio e para onde se vai.

    Sem isto, terminar uma tela obrigava a voltar ao menu e lembrar qual era a
    proxima -- o app e um encadeamento e nao mostrava o encadeamento. O link do
    proximo passo carrega o resumo do que ele faz, entao a decisao de seguir nao
    depende de ja se conhecer o fluxo.
    """
    from .navegacao import anterior, pagina, proximo

    depois, antes = proximo(chave), anterior(chave)
    if depois is None and antes is None:
        return

    st.divider()
    esquerda, direita = st.columns([1, 2])
    alvo_antes = pagina(antes.chave) if antes else None
    if alvo_antes is not None:
        esquerda.page_link(
            alvo_antes,
            label=f"Voltar a {antes.titulo}",
            icon=":material/arrow_back:",
        )

    alvo_depois = pagina(depois.chave) if depois else None
    if alvo_depois is None:
        return

    with direita:
        if pronto:
            st.page_link(
                alvo_depois,
                label=f"**Próximo — {depois.titulo}**",
                icon=depois.icone_material,
                width="stretch",
            )
            st.caption(depois.resumo)
        else:
            st.caption(motivo or f"Próximo: {depois.titulo}")



def balizador(
    valor: float,
    indicador: str = "",
    analise=None,
    formato: str = "pct",
    contexto: str = "",
) -> None:
    """Onde o número que você acabou de digitar cai — na empresa e na base.

    A tela de Premissas pedia doze decisões e não respondia a pergunta que cada
    uma levanta: **25% de ROIC perpétuo é muito ou pouco?** A resposta estava a
    duas telas de distância, no Histórico, e depois na base de referência — e ir
    e voltar para conferir cada campo é o tipo de trabalho braçal que este
    projeto existe para tirar da mão.

    Duas âncoras, porque elas respondem coisas diferentes e nenhuma basta:

    * **o que a companhia entregou** — a mediana do período importado. É o
      balizador mais forte: projetar 25% para quem nunca passou de 12% é uma
      afirmação sobre mudança, e ela precisa de motivo;
    * **onde isso cai na base brasileira** — o percentil entre as companhias
      medidas. Serve para o caso oposto, o da empresa sem histórico longo, e
      para saber se o número é incomum no mercado e não só nela.

    Sai em silêncio quando não há âncora: uma linha dizendo "sem referência"
    ocupa o mesmo espaço e não ajuda ninguém.
    """
    from valuation import referencias

    partes = []

    if analise is not None and indicador:
        try:
            historico = float(analise.mediana(indicador))
        except Exception:  # noqa: BLE001 - indicador que a analise nao produziu
            historico = float("nan")
        if np.isfinite(historico):
            anos = analise.anos
            partes.append(
                f"**{formatar(historico, formato)}** na empresa "
                f"({anos[0]}–{anos[-1]})"
            )
            partes.append(_comparacao_com_o_historico(valor, historico, formato))

    onde = referencias.descrever(indicador, valor) if indicador else ""
    if onde:
        partes.append(onde.replace("companhias brasileiras", "da base"))

    if contexto:
        partes.append(contexto)

    partes = [p for p in partes if p]
    if partes:
        st.caption(" · ".join(partes))


# Quanto o número projetado precisa se afastar do histórico para merecer ser
# comentado. Abaixo disso a diferença é ruído de arredondamento da própria
# mediana, e apontá-la treinaria o usuário a ignorar o balizador.
DISTANCIA_QUE_MERECE_NOTA = 0.25


def _comparacao_com_o_historico(valor: float, historico: float, formato: str) -> str:
    """"Acima" e "abaixo" com o tamanho, e só quando o tamanho importa."""
    if not np.isfinite(valor) or not np.isfinite(historico) or historico == 0:
        return ""
    razao = valor / historico
    if abs(razao - 1) < DISTANCIA_QUE_MERECE_NOTA:
        return "em linha com o histórico"
    if formato in ("pct", "pct2"):
        diferenca = formatar(abs(valor - historico), formato)
        sentido = "acima" if valor > historico else "abaixo"
        return f"**{diferenca} {sentido}** do histórico"
    return f"**{razao:.1f}x** o histórico".replace(".", ",")


def grafico(figura: go.Figure, dados: pd.DataFrame | pd.Series | None = None,
            rotulo_dados: str = "Ver os dados do gráfico") -> None:
    """Exibe um grafico com a tabela de dados disponivel ao lado.

    A tabela nao e opcional por acaso: parte da paleta fica abaixo de 3:1 de
    contraste no modo claro, e o guia de acessibilidade exige rotulo visivel ou
    visao tabular nesse caso. Aqui ela tambem serve para copiar numero para a
    planilha sem precisar exportar tudo.
    """
    st.plotly_chart(figura, width="stretch", config={"displayModeBar": False})
    if dados is not None:
        with st.expander(rotulo_dados):
            st.dataframe(dados, width="stretch")


def metrica(
    rotulo: str,
    valor: float | None,
    formato: str = "moeda",
    unidade: str = "",
    ajuda: str = "",
    delta: str | None = None,
    cartao: bool = True,
) -> None:
    """Metrica formatada no padrao brasileiro, com ajuda opcional.

    **A unidade vai no rotulo, e nao dentro do numero.** "930,0 R$ milhoes" nao
    cabe na largura de um cartao e o Streamlit o corta em "930,0 R$ mil…" -- um
    numero truncado, que e pior que um numero sem unidade porque parece um
    numero inteiro. No rotulo ela cabe, porque rotulo quebra linha e numero nao;
    e e a convencao da propria demonstracao financeira, que escreve a unidade uma
    vez no cabecalho em vez de repeti-la em cada celula.
    """
    if unidade and formato == "moeda":
        rotulo = f"{rotulo} ({unidade_curta(unidade)})"
        texto = formatar(valor, formato)
    else:
        texto = formatar(valor, formato, unidade)
    st.metric(rotulo, texto, delta=delta, help=ajuda or None, border=cartao)


# "R$ milhoes" por extenso dentro do rotulo de um cartao estoura a largura e o
# Streamlit corta o **rotulo** -- "Receita do ultimo ano (R$ mil…", que ainda por
# cima se le como milhares. A abreviacao e a que o mercado brasileiro escreve.
ABREVIACOES = {
    "R$ milhões": "R$ mi",
    "R$ milhoes": "R$ mi",
    "R$ bilhões": "R$ bi",
    "R$ bilhoes": "R$ bi",
    "R$ mil": "R$ mil",
    "unidades monetárias": "un. mon.",
    "unidades monetarias": "un. mon.",
}


def unidade_curta(unidade: str) -> str:
    """A unidade no tamanho que cabe num rotulo de cartao."""
    return ABREVIACOES.get(unidade.strip(), unidade)


def formatar(valor: float | None, formato: str = "moeda", unidade: str = "") -> str:
    """Formata numeros no padrao brasileiro (milhar com ponto, decimal com virgula)."""
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return "—"
    if formato == "pct":
        return f"{valor * 100:,.1f}%".replace(".", ",")
    if formato == "pct2":
        return f"{valor * 100:,.2f}%".replace(".", ",")
    if formato == "multiplo":
        return f"{valor:,.2f}x".replace(".", ",")
    if formato == "numero":
        return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    if formato == "dias":
        return f"{valor:,.0f} dias".replace(",", ".")
    texto = f"{valor:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"{texto} {unidade}".strip()


def em_texto(valor: float | None, unidade: str = "") -> str:
    """Valor monetario para dentro de um markdown, com o ``$`` escapado.

    O Streamlit interpreta ``$...$`` como LaTeX. A unidade brasileira e
    ``R$ milhoes``, entao **duas** aparicoes dela na mesma frase fecham um par e
    o trecho entre as duas vira formula. Visto no navegador: "Saldo de divida
    bruta ao fim de cada ano, em R milhoes. O saldo de partida e 400,0 R
    milhoes" saiu com o meio em italico de matematica, e a frase perdeu os dois
    cifroes.

    Nao da para escapar dentro de ``formatar``, que tambem alimenta tabela --
    ali o ``\$`` apareceria literal. Entao a distincao e por destino: numero que
    vai para texto passa por aqui, numero que vai para celula nao.
    """
    return formatar(valor, "moeda", unidade).replace("$", r"\$")


def escapar_cifrao(texto: str) -> str:
    """Escapa o ``$`` de um texto **ja montado**, pela mesma razao de ``em_texto``.

    ``em_texto`` recebe um numero e o formata; esta recebe uma frase que veio
    pronta -- tipicamente do motor, que nao conhece o Streamlit e nao deveria
    conhecer. A regra e a mesma e continua sendo por destino: o que vai para
    markdown passa por aqui, o que vai para celula nao.
    """
    return texto.replace("$", r"\$")


def tabela_formatada(
    dados: pd.DataFrame, formato: str = "moeda", unidade: str = ""
) -> pd.DataFrame:
    """Aplica a formatacao brasileira a um DataFrame inteiro, para exibicao."""
    return dados.map(lambda v: formatar(v, formato, unidade))


_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _texto_seguro(valor: object) -> str:
    texto = str(valor)
    for cru, escapado in _ESCAPES.items():
        texto = texto.replace(cru, escapado)
    return texto


NIVEL_MAXIMO_COM_ESTILO = 5


def tabela_de_demonstracao(
    linhas: pd.DataFrame, unidade: str = "", compacta: bool = False
) -> str:
    """A demonstracao publicada em HTML, com a hierarquia visivel.

    ``st.dataframe`` desenha em canvas e trata toda linha igual: "Ativo Total" e
    "JSCP a receber" saiam com o mesmo peso, e achar os totais exigia ler os 210
    rotulos. O peso do texto e o nivel do plano de contas -- que e a informacao
    que o recuo ja carregava e que ninguem via.

    Vai como HTML porque **e o que sabe fazer o que se pede aqui**: o Styler do
    pandas so atravessa cor de texto e de fundo para o ``st.dataframe``, e nao
    peso nem tamanho de fonte, que sao justamente a diferenca entre um total e
    um item folha. De quebra o texto passa a existir no DOM -- a varredura do
    navegador nao consegue ler numero dentro do canvas.

    ``linhas`` e o que :meth:`Demonstracoes.linhas_publicadas` devolve: codigo,
    rotulo, nivel e uma coluna por ano.

    ``compacta`` aperta a coluna de rotulo e o recuo, para a tabela caber em
    meia largura -- e o que o balanco lado a lado precisa, com sete anos de cada
    lado numa tela so.
    """
    from valuation.importacao.cvm import e_conta_por_acao
    from valuation.importacao.importador import colunas_de_periodo

    anos = colunas_de_periodo(linhas)
    cabecalho = "".join(f"<th>{ano}</th>" for ano in anos)
    corpo = []
    for _, linha in linhas.iterrows():
        # O bloco do lucro por acao fica em reais por acao enquanto o resto da
        # tabela esta em milhoes. O rotulo tem de dizer: um "1,4" sem marca, na
        # coluna de um balanco em R$ milhoes, se le como um milhao e meio.
        por_acao = e_conta_por_acao(linha["codigo"])
        profundidade = max(int(linha["nivel"]) - 1, 0)
        nivel = min(int(linha["nivel"]) or 1, NIVEL_MAXIMO_COM_ESTILO)
        # O recuo continua sendo a hierarquia, agora em CSS: o peso do texto
        # diz "isto e um total" e o recuo diz "dentro de quem". As duas leituras
        # nao se substituem -- num nivel 4 longo, so o peso perderia o caminho.
        passo = 0.6 if compacta else 0.85
        recuo = f"padding-left: calc(0.75rem + {profundidade} * {passo}rem)"
        marca = '<span class="unidade">R$/ação</span>' if por_acao else ""
        celulas = [
            f'<td class="conta" style="{recuo}" '
            f'title="{_texto_seguro(linha["codigo"])}">'
            f'{_texto_seguro(linha["rotulo"])}{marca}</td>'
        ]
        for ano in anos:
            valor = linha[ano]
            vazio = valor is None or (
                isinstance(valor, float) and not np.isfinite(valor)
            )
            classe = "nulo" if vazio or valor == 0 else ""
            if not vazio and valor < 0:
                classe = "negativo"
            atributo = f' class="{classe}"' if classe else ""
            formato = "numero" if por_acao else "moeda"
            celulas.append(f"<td{atributo}>{formatar(valor, formato)}</td>")
        corpo.append(f'<tr class="n{nivel}">{"".join(celulas)}</tr>')

    rotulo_conta = f"Conta ({unidade_curta(unidade)})" if unidade else "Conta"
    classe = "df-publicada compacta" if compacta else "df-publicada"
    return (
        f'<div class="{classe}"><table><thead><tr>'
        f'<th class="conta">{_texto_seguro(rotulo_conta)}</th>{cabecalho}'
        f'</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'
    )


def _celula(valor, formato: str) -> str:
    """Uma celula qualquer: numero formatado, ou texto que ja veio pronto.

    A passagem de texto existe para as tabelas que misturam as duas coisas -- o
    balizador da projecao poe "no percentil 69 de 397" ao lado de "12,5%" --, e
    sem ela essas tabelas voltariam a ser `st.dataframe`, que desenha em canvas
    e alinha tudo a esquerda.
    """
    if isinstance(valor, str):
        return f'<td class="texto">{_texto_seguro(valor)}</td>'
    return _celula_de_numero(valor, formato)


def _celula_de_numero(valor, formato: str) -> str:
    """Uma celula de numero: alinhada a direita, negativo marcado, zero recessivo.

    **Sem unidade.** Ela mora no cabecalho da coluna, uma vez. Repeti-la aqui sao
    154 vezes o mesmo texto numa DRE de 22 linhas por 7 anos, e o que ele empurra
    para fora da largura util e o numero -- foi assim que a tabela antiga perdeu
    tres anos de coluna. E o erro e facil de repetir: escrevi este componente e
    o cometi de novo na primeira versao.
    """
    vazio = valor is None or (isinstance(valor, float) and not np.isfinite(valor))
    classe = "nulo" if vazio or valor == 0 else ""
    if not vazio and valor < 0:
        classe = "negativo"
    atributo = f' class="{classe}"' if classe else ""
    return f"<td{atributo}>{formatar(valor, formato)}</td>"


def tabela_financeira(
    tabela: pd.DataFrame,
    subtotais: set[str] | None = None,
    formato: str = "moeda",
    unidade: str = "",
) -> str:
    """Uma demonstracao em forma de tabela: rotulo a esquerda, anos a direita.

    Serve a DRE gerencial e qualquer outra tabela de linha contabil por ano. A
    diferenca para o ``st.dataframe`` que estava aqui nao e enfeite:

    * **numero a direita, em algarismo tabular.** Alinhado a esquerda, como o
      canvas do Streamlit desenha, "13.347,4" e "9.394,2" nao compartilham
      posicao de casa decimal e comparar dois anos vira trabalho de leitura;
    * **subtotal em negrito e com fundo**, para a ponte se ler como ponte -- o
      olho acha "= EBITDA" sem percorrer as 22 linhas;
    * **negativo em vermelho** junto do sinal de menos, que ja estava la: e
      reforco redundante, e nao a unica pista.

    ``subtotais`` sao os rotulos que fecham um bloco. Sem eles a tabela sai toda
    no mesmo peso, o que e o comportamento certo para uma tabela sem hierarquia.
    """
    subtotais = subtotais or set()
    colunas = list(tabela.columns)
    cabecalho = "".join(f"<th>{_texto_seguro(c)}</th>" for c in colunas)

    corpo = []
    for rotulo, linha in tabela.iterrows():
        nivel = "n2" if rotulo in subtotais else "n3"
        celulas = [f'<td class="conta">{_texto_seguro(rotulo)}</td>']
        celulas += [_celula(linha[c], formato) for c in colunas]
        corpo.append(f'<tr class="{nivel}">{"".join(celulas)}</tr>')

    rotulo_coluna = f"Linha ({unidade_curta(unidade)})" if unidade else "Linha"
    return (
        '<div class="df-publicada"><table><thead><tr>'
        f'<th class="conta">{_texto_seguro(rotulo_coluna)}</th>{cabecalho}'
        f'</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'
    )



def tabela_de_indicadores(
    tabela: pd.DataFrame, formato: str = "numero", destaques: set[str] | None = None
) -> str:
    """Indicadores por ano, com o mesmo desenho das demonstracoes.

    Diferente de :func:`tabela_financeira` em uma coisa so: aqui a linha nao e
    conta contabil e nao ha subtotal, entao o destaque e opcional e serve para o
    indicador que a aba esta tratando.

    Existe porque duas abas ficaram para tras no revamp -- "Liquidez e
    composicao" e "Tudo" -- e tabela com numero a esquerda ao lado de tabela com
    numero a direita le como dois apps.
    """
    destaques = destaques or set()
    colunas = list(tabela.columns)
    cabecalho = "".join(f"<th>{_texto_seguro(c)}</th>" for c in colunas)

    corpo = []
    for rotulo, linha in tabela.iterrows():
        nivel = "n2" if rotulo in destaques else "n3"
        celulas = [f'<td class="conta">{_texto_seguro(rotulo)}</td>']
        celulas += [_celula(linha[c], formato) for c in colunas]
        corpo.append(f'<tr class="{nivel}">{"".join(celulas)}</tr>')

    return (
        '<div class="df-publicada"><table><thead><tr>'
        f'<th class="conta">Indicador</th>{cabecalho}'
        f'</tr></thead><tbody>{"".join(corpo)}</tbody></table></div>'
    )


def formulas_dos_indicadores(indicadores: list[str]) -> None:
    """As contas por tras dos numeros, para quem quiser conferir.

    "Ha varios jeitos de chegar no ROIC" -- e ha. Mostrar o numero sem dizer
    qual dos jeitos foi usado obriga quem le a confiar ou a reimplementar a
    conta. Fica num expansor porque a maioria das visitas nao precisa dele, e
    quem precisa precisa muito.
    """
    from valuation.formulas import formula as buscar_formula

    verbetes = [(nome, buscar_formula(nome)) for nome in indicadores]
    verbetes = [(nome, v) for nome, v in verbetes if v is not None]
    if not verbetes:
        return

    with st.expander("Como cada indicador é calculado"):
        for nome, verbete in verbetes:
            st.markdown(f"**{nome}**")
            st.markdown(verbete.formula)
            if verbete.convencao:
                st.caption(verbete.convencao)
            st.divider()


def aviso_sem_modelo(erro: str | None) -> None:
    """Mensagem padrao quando as premissas nao fecham."""
    st.error(
        "O modelo não fecha com as premissas atuais, então não há resultado para "
        f"mostrar.\n\n**Motivo:** {erro}"
        if erro
        else "O modelo não fecha com as premissas atuais."
    )
    st.info(
        "O caso mais comum é o crescimento perpétuo ter ficado acima da taxa de "
        "desconto. Volte em **Premissas** ou **Custo de capital** e ajuste."
    )


def barra_de_severidade(erros: int, alertas: int, informacoes: int) -> None:
    """Resumo do diagnostico em tres numeros."""
    colunas = st.columns(3)
    colunas[0].metric("🔴 Erros", erros, border=True)
    colunas[1].metric("🟡 Alertas", alertas, border=True)
    colunas[2].metric("🔵 Observações", informacoes, border=True)


def linha_de_premissas_anuais(
    rotulo: str,
    valores: list[float],
    anos: list[int],
    chave: str,
    formato: str = "%.1f%%",
    percentual: bool = True,
    passo: float = 0.5,
    ajuda: str = "",
) -> list[float]:
    """Editor de uma premissa ano a ano, em colunas.

    Percentuais sao editados em pontos percentuais (12,5) e devolvidos em
    decimais (0,125): pedir que o usuario digite 0,125 e um convite ao erro de
    ordem de grandeza, que e o mais caro de todos em valuation.
    """
    st.markdown(f"**{rotulo}**" + (f" — {ajuda}" if ajuda else ""))
    colunas = st.columns(len(anos))
    novos = []
    for indice, (coluna, ano) in enumerate(zip(colunas, anos)):
        atual = valores[indice] * 100 if percentual else valores[indice]
        novo = coluna.number_input(
            f"{ano}",
            value=float(atual),
            step=passo,
            format=formato.replace("%%", "%") if percentual else "%.2f",
            key=f"{chave}_{indice}",
            label_visibility="visible",
        )
        novos.append(novo / 100 if percentual else novo)
    return novos
