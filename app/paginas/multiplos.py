"""Tela de avaliacao relativa por multiplos de comparaveis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from valuation.importacao.series import ano_do_rotulo

from valuation import Alvo, Comparavel, avaliar_por_multiplos, estatisticas, tabela_comparaveis
from valuation.importacao.cvm import (
    FONTE_CVM,
    ErroCVM,
    carregar_cadastro,
    importar_cvm,
)

from .. import estado
from ..componentes import (
    conceito,
    em_texto,
    etapa,
    formatar,
    grafico,
    secao,
    tabela_de_indicadores,
)
from ..graficos import barras_de_faixa

COLUNAS_PEERS = [
    "Empresa",
    "Valor de mercado",
    "Dívida líquida",
    "Receita",
    "EBITDA",
    "EBIT",
    "Lucro líquido",
    "Patrimônio líquido",
]


def render() -> None:
    etapa("Passo 8", "Múltiplos", "O que o mercado paga por empresas parecidas")
    conceito("multiplos", "Avaliação relativa")

    _pares_por_perfil()
    _peers_da_cvm()
    _editor_peers()

    comparaveis = estado.comparaveis()
    if not comparaveis:
        st.info(
            "Preencha ao menos um comparável acima para ver os múltiplos e o valor "
            "implícito."
        )
        return

    alvo = _alvo_atual()
    st.divider()

    _multiplos_do_alvo(alvo, comparaveis)

    abas = st.tabs(["Múltiplos do peer group", "Valor implícito", "Comparação com o DCF"])
    with abas[0]:
        _peer_group(comparaveis)
    with abas[1]:
        _implicito(alvo, comparaveis)
    with abas[2]:
        _comparar(alvo, comparaveis)



def _multiplos_do_alvo(alvo: Alvo, comparaveis) -> None:
    """O múltiplo que o mercado paga **por esta empresa**, ao lado dos pares.

    A tela sabia o que os comparáveis valem e o que o DCF diz, e não sabia o
    número do meio: quanto a bolsa paga pela companhia em avaliação. Sem ele, a
    pergunta "está cara em relação aos pares?" ficava sem o lado esquerdo.

    O preço vem de onde já estava — o informado em **Margem de segurança** —,
    então nada é buscado aqui e as duas telas não podem discordar.
    """
    guardado = estado.preco()
    if guardado is None:
        st.caption(
            "Informe a cotação em **Margem de segurança** para ver, aqui, o "
            "múltiplo que o mercado paga por esta empresa ao lado do que paga "
            "pelos pares."
        )
        return

    acoes = alvo.acoes_em_circulacao
    valor_mercado = (
        guardado["valor"] * acoes if guardado["por_acao"] and acoes else guardado["valor"]
    )
    if not valor_mercado or not np.isfinite(valor_mercado):
        return

    do_alvo = Comparavel(
        nome=alvo.nome,
        valor_mercado=float(valor_mercado),
        divida_liquida=alvo.divida_liquida,
        receita=alvo.receita,
        ebitda=alvo.ebitda,
        ebit=alvo.ebit,
        lucro_liquido=alvo.lucro_liquido,
        patrimonio_liquido=alvo.patrimonio_liquido,
    ).multiplos()

    medianas = estatisticas(comparaveis)["Mediana"]
    linhas = []
    for nome, valor in do_alvo.items():
        par = float(medianas.get(nome, float("nan")))
        linhas.append(
            {
                "Múltiplo": nome,
                "Esta empresa": valor,
                "Mediana dos pares": par,
                "Prêmio sobre os pares": (valor / par - 1)
                if np.isfinite(valor) and np.isfinite(par) and par
                else float("nan"),
            }
        )

    ticker = estado.config().get("ticker")
    secao(
        "O que o mercado paga por esta empresa",
        f"A {em_texto(valor_mercado, estado.empresa().unidade)} de valor de "
        f"mercado{f' ({ticker})' if ticker else ''}, contra a mediana do peer "
        "group.",
    )
    tabela = pd.DataFrame(linhas).set_index("Múltiplo")
    st.html(
        tabela_de_indicadores(tabela[["Esta empresa", "Mediana dos pares"]], "multiplo")
    )
    st.caption(
        " · ".join(
            f"**{l['Múltiplo']}** {formatar(l['Prêmio sobre os pares'], 'pct')}"
            for l in linhas
            if np.isfinite(l["Prêmio sobre os pares"])
        )
        + "  — prêmio (ou desconto) sobre a mediana dos pares."
    )


def _pares_por_perfil() -> None:
    """Sugere comparáveis por **perfil econômico**, e não por rótulo de setor.

    O critério é o do Damodaran: comparável é a empresa com risco, crescimento e
    fluxo de caixa parecidos. Isso se mede — e medir evita o emparelhamento por
    registro, que põe a WEG ao lado da Plascar porque as duas se cadastraram na
    mesma linha do formulário.
    """
    from valuation.pares import (
        UniversoVazio,
        explicar,
        pares_proximos,
        perfil_de,
        universo_mais_proximo,
    )

    analise = estado.analise()
    if analise is None:
        return

    with st.expander("Sugerir comparáveis pelo perfil econômico", expanded=False):
        st.markdown(
            "Seis dimensões medidas — margem, ROIC, giro do capital, capex, "
            "crescimento e alavancagem — e a distância entre a companhia e cada "
            "outra da base da CVM. **Não há preço aqui**: comparável se escolhe "
            "pelo negócio, e o preço é o que se vai comparar depois."
        )

        dfs = estado.demonstracoes()
        # O universo de pares e por **exercicio**: numa serie trimestral os
        # quatro trimestres de 2025 procuram a safra de 2025, e nao quatro
        # safras. `int(a)` estourava em "1T25" e derrubava a tela inteira.
        anos = (
            sorted({a for a in (ano_do_rotulo(x) for x in dfs.anos) if a})
            if dfs is not None
            else []
        )
        if not anos:
            return

        encontrado = universo_mais_proximo(anos)
        if encontrado is None:
            st.info(
                "O universo de perfis ainda não foi construído. Ele importa as ~470 "
                "companhias com DFP consolidada e mede o perfil de cada uma — leva "
                "alguns minutos e depois fica em cache."
            )
            st.code(
                f"python -m valuation.pares --anos {anos[0]}-{anos[-1]}", language="bash"
            )
            return

        universo, anos_do_universo = encontrado
        if anos_do_universo[-1] != anos[-1]:
            st.warning(
                f"O universo em cache cobre {anos_do_universo[0]}–{anos_do_universo[-1]} "
                f"e a companhia foi importada até {anos[-1]}. A comparação continua "
                "válida, mas os perfis não são do mesmo período."
            )
        perfil = perfil_de(analise)
        codigo = (getattr(dfs, "fonte", None) or {}).get("codigo_cvm")

        # A receita tem que sair do **proprio universo**, e nao das demonstracoes
        # da sessao: elas podem ter sido escaladas para milhoes, e o universo esta
        # sempre em reais. Comparar as duas faria toda companhia parecer mil vezes
        # maior e o filtro de porte descartaria a base inteira -- deixando no topo
        # exatamente as companhias estranhas que ele existe para tirar.
        receita = (
            float(universo.perfis.loc[codigo, "receita"])
            if codigo in universo.perfis.index
            else float("nan")
        )

        colunas = st.columns(3)
        quantos = colunas[0].number_input("Quantos pares", 3, 30, 10, step=1)
        limitar_porte = colunas[1].checkbox(
            "Filtrar por porte",
            value=np.isfinite(receita),
            disabled=not np.isfinite(receita),
            help=None if np.isfinite(receita) else
            "A companhia não está no universo, então não há receita comparável "
            "para medir porte.",
        )
        faixa = colunas[2].number_input(
            "Faixa de porte (x receita)", 2.0, 50.0, 10.0, step=1.0,
            disabled=not limitar_porte,
        )

        try:
            tabela = pares_proximos(
                perfil,
                universo,
                quantos=int(quantos),
                receita=receita if (limitar_porte and np.isfinite(receita)) else None,
                faixa_de_porte=float(faixa) if limitar_porte else None,
                excluir=codigo,
            )
        except UniversoVazio as erro:
            st.warning(str(erro))
            return

        st.caption(
            f"Universo de {len(universo)} companhias, exercícios "
            f"{anos_do_universo[0]}–{anos_do_universo[-1]}."
        )
        st.dataframe(
            tabela.drop(columns=["codigo"]).style.format(
                {
                    "Distância": "{:.2f}",
                    "Receita": "{:,.0f}",
                    **{d: "{:.1%}" for d in universo.dimensoes if "EBITDA" not in d},
                    "Divida liquida / EBITDA": "{:.2f}",
                },
                na_rep="—",
            ),
            width="stretch",
        )

        escolhido = st.selectbox(
            "Ver por que este par apareceu", list(tabela.index), index=0
        )
        st.dataframe(
            explicar(perfil, universo.perfis.loc[tabela.loc[escolhido, "codigo"]], universo)
            .style.format("{:.3f}", na_rep="—"),
            width="stretch",
        )

        st.warning(
            "**Perfil parecido não é negócio parecido.** Uma concessionária de "
            "rodovia e um gasoduto têm margem alta, capex pesado, dívida longa e "
            "crescimento vegetativo — perfis gêmeos, riscos e regulações "
            "diferentes. Isto é ponto de partida para escolher comparáveis, não o "
            "critério final: confira cada nome antes de usar."
        )


def _peers_da_cvm() -> None:
    """Monta o peer group a partir do setor da própria companhia, na CVM.

    A CVM publica tudo que o comparável precisa menos o preço da ação. Como ela
    publica a quantidade de ações (emitidas menos tesouraria), o que sobra para
    o usuário é digitar a cotação — e não calcular o valor de mercado, que é
    onde o erro costuma entrar.
    """
    dfs = estado.demonstracoes()
    fonte = getattr(dfs, "fonte", None) or {} if dfs is not None else {}
    if fonte.get("tipo") != FONTE_CVM:
        return

    with st.expander("Montar peer group com dados da CVM", expanded=False):
        try:
            catalogo = _catalogo()
        except ErroCVM as erro:
            st.error(f"Não consegui obter o cadastro da CVM: {erro}")
            return

        st.caption(
            "O setor vem do **cadastro** da CVM, que é uma classificação de "
            "registro e não um agrupamento econômico: uma fabricante global pode "
            "aparecer como “Emp. Adm. Part.”, ao lado de companhias sem nenhuma "
            "semelhança de negócio ou porte. Troque o setor à vontade e confira "
            "cada nome — peer group ruim contamina o múltiplo mais do que a "
            "ausência de peer group."
        )

        setores = sorted({c.setor for c in catalogo if c.setor})
        padrao = fonte.get("setor")
        indice = setores.index(padrao) if padrao in setores else 0
        setor = st.selectbox("Setor", setores, index=indice)

        ano = ano_do_rotulo(dfs.anos[-1]) or 0
        candidatos = [
            c
            for c in catalogo
            if c.setor == setor and c.codigo_cvm != fonte.get("codigo_cvm")
        ]
        if not candidatos:
            st.info("Nenhuma outra companhia ativa neste setor.")
            return

        rotulos = {f"{c.nome} ({c.codigo_cvm})": c for c in candidatos}
        escolhidos = st.multiselect(
            f"Comparáveis ({len(candidatos)} no setor)",
            list(rotulos),
            help=f"Os números vêm da DFP de {ano}, a mesma data-base do histórico.",
        )
        _aviso_de_porte(escolhidos, rotulos, dfs, ano)
        if not escolhidos:
            st.caption(
                "Escolha as companhias. O app busca receita, EBITDA, EBIT, lucro, "
                "patrimônio, dívida líquida e quantidade de ações; falta só a cotação."
            )
            return

        if st.button(f"Buscar dados de {ano}", type="primary"):
            _buscar_peers([rotulos[e] for e in escolhidos], ano, dfs.unidade)

    if st.session_state.get("peers_cvm"):
        _precificar_peers()


FAIXA_DE_PORTE = 10.0


def fora_de_porte(receita_alvo: float, receita_peer: float) -> bool:
    """A diferença de porte já invalida a comparação?

    Múltiplo de empresa dez vezes menor não descreve a maior: muda o custo de
    capital, o acesso a crédito, a liquidez da ação e o prêmio de controle. A
    faixa é larga de propósito — serve para pegar o disparate, não para impor
    um universo de comparáveis.
    """
    if not (np.isfinite(receita_alvo) and np.isfinite(receita_peer)):
        return False
    if receita_alvo <= 0 or receita_peer <= 0:
        return False
    razao = max(receita_alvo, receita_peer) / min(receita_alvo, receita_peer)
    return razao > FAIXA_DE_PORTE


def _aviso_de_porte(escolhidos, rotulos, dfs, ano: int) -> None:
    """Avisa quando um comparável escolhido é de outro porte."""
    receita_alvo = dfs.valor("receita_liquida", ano)
    if not escolhidos or not np.isfinite(receita_alvo):
        return

    destoantes = []
    for rotulo in escolhidos:
        companhia = rotulos[rotulo]
        cache = st.session_state.setdefault("receita_peers", {})
        chave = (companhia.codigo_cvm, ano)
        if chave not in cache:
            try:
                cache[chave] = importar_cvm(companhia, [ano]).valor(
                    "receita_liquida", ano
                )
            except ErroCVM:
                cache[chave] = float("nan")
        if fora_de_porte(receita_alvo, cache[chave]):
            destoantes.append(companhia.nome)

    if destoantes:
        st.warning(
            "Fora da faixa de porte (mais de 10x de diferença de receita): "
            + ", ".join(destoantes)
            + ". O múltiplo de uma empresa muito menor não descreve esta: muda "
            "custo de capital, acesso a crédito e liquidez da ação."
        )


def _buscar_peers(companhias, ano: int, unidade: str) -> None:
    divisor = {"R$ milhões": 1e6, "R$ mil": 1e3, "R$ bilhões": 1e9}.get(unidade, 1.0)
    achados, falhas = [], []

    barra = st.progress(0.0, "Buscando…")
    for indice, companhia in enumerate(companhias, start=1):
        barra.progress(indice / len(companhias), f"{companhia.nome}…")
        try:
            d = importar_cvm(companhia, [ano])
        except ErroCVM:
            falhas.append(companhia.nome)
            continue
        achados.append(
            {
                "Empresa": companhia.nome,
                "Cotação (R$/ação)": None,
                "Ações": _serie(d, "acoes_em_circulacao", ano, divisor),
                "Dívida líquida": _serie_metodo(d.divida_liquida(), ano, divisor),
                "Receita": _serie(d, "receita_liquida", ano, divisor),
                "EBITDA": _serie_metodo(d.ebitda(), ano, divisor),
                "EBIT": _serie(d, "ebit", ano, divisor),
                "Lucro líquido": _serie(d, "lucro_liquido", ano, divisor),
                "Patrimônio líquido": _serie(d, "patrimonio_liquido", ano, divisor),
            }
        )
    barra.empty()

    st.session_state["peers_cvm"] = achados
    if falhas:
        st.warning("Sem DFP em " + str(ano) + " para: " + ", ".join(falhas))
    st.rerun()


def _serie(d, chave: str, ano: int, divisor: float) -> float:
    valor = d.valor(chave, ano)
    return float(valor) / divisor if np.isfinite(valor) else float("nan")


def _serie_metodo(serie, ano: int, divisor: float) -> float:
    valor = serie.get(ano, float("nan"))
    return float(valor) / divisor if np.isfinite(valor) else float("nan")


def _precificar_peers() -> None:
    st.markdown("**Informe a cotação de cada comparável**")
    st.caption(
        "O valor de mercado sai de cotação × ações em circulação. Use o preço da "
        "mesma data-base do balanço, ou aceite que o múltiplo mistura duas datas."
    )

    tabela = pd.DataFrame(st.session_state["peers_cvm"])
    editada = st.data_editor(
        tabela,
        width="stretch",
        key="editor_peers_cvm",
        disabled=[c for c in tabela.columns if c not in ("Cotação (R$/ação)",)],
        column_config={
            "Cotação (R$/ação)": st.column_config.NumberColumn(
                "Cotação (R$/ação)", format="%.2f", help="Preço por ação, em reais."
            ),
            # As acoes estao na unidade dos valores para que cotacao x acoes saia
            # na mesma unidade; sem casas decimais o numero apareceria como zero.
            "Ações": st.column_config.NumberColumn(
                "Ações", format="%.4f", help="Na mesma unidade dos valores."
            ),
        },
    )

    prontos = editada[editada["Cotação (R$/ação)"].notna()]
    if prontos.empty:
        return

    if st.button(f"Adicionar {len(prontos)} comparável(is)", type="primary"):
        novos = list(estado.comparaveis())
        existentes = {c.nome for c in novos}
        adicionados = 0
        for _, linha in prontos.iterrows():
            if linha["Empresa"] in existentes:
                continue
            comparavel = comparavel_de_peer(dict(linha))
            if comparavel is None:
                continue
            novos.append(comparavel)
            adicionados += 1
        estado.definir_comparaveis(novos)
        st.session_state.pop("peers_cvm", None)
        st.success(f"{adicionados} comparável(is) adicionado(s).")
        st.rerun()


def comparavel_de_peer(linha: dict) -> Comparavel | None:
    """Converte uma linha da tabela de cotação em um comparável.

    Separada da tela por ser onde a conta acontece: o valor de mercado sai de
    cotação x ações, e as ações já vêm na unidade dos valores, então o produto
    sai na mesma unidade do resto do modelo. Errar isso produz um múltiplo
    plausível e errado por um fator de mil.
    """
    cotacao = _num(linha.get("Cotação (R$/ação)"))
    acoes = _num(linha.get("Ações"))
    nome = str(linha.get("Empresa") or "").strip()
    if not nome or not np.isfinite(cotacao) or not np.isfinite(acoes) or acoes <= 0:
        return None

    return Comparavel(
        nome=nome,
        valor_mercado=cotacao * acoes,
        divida_liquida=_num(linha.get("Dívida líquida"), 0.0),
        receita=_num(linha.get("Receita")),
        ebitda=_num(linha.get("EBITDA")),
        ebit=_num(linha.get("EBIT")),
        lucro_liquido=_num(linha.get("Lucro líquido")),
        patrimonio_liquido=_num(linha.get("Patrimônio líquido")),
    )


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def _catalogo():
    return carregar_cadastro()


def _editor_peers() -> None:
    st.subheader("Empresas comparáveis")
    st.caption(
        "Use dados dos últimos 12 meses e da mesma data-base para todos. Dívida "
        "líquida pode ser negativa (caixa líquido). Deixe em branco o que não tiver."
    )

    comparaveis = estado.comparaveis()
    if comparaveis:
        base = pd.DataFrame(
            [
                {
                    "Empresa": c.nome,
                    "Valor de mercado": c.valor_mercado,
                    "Dívida líquida": c.divida_liquida,
                    "Receita": c.receita,
                    "EBITDA": c.ebitda,
                    "EBIT": c.ebit,
                    "Lucro líquido": c.lucro_liquido,
                    "Patrimônio líquido": c.patrimonio_liquido,
                }
                for c in comparaveis
            ]
        )
    else:
        base = pd.DataFrame([{coluna: (None if coluna != "Empresa" else "") for coluna in COLUNAS_PEERS}])

    editada = st.data_editor(
        base,
        num_rows="dynamic",
        width="stretch",
        key="editor_peers",
        column_config={
            coluna: st.column_config.NumberColumn(coluna, format="%.1f")
            for coluna in COLUNAS_PEERS[1:]
        },
    )

    if st.button("Salvar comparáveis", type="primary"):
        novos = []
        for _, linha in editada.iterrows():
            nome = str(linha.get("Empresa") or "").strip()
            mercado = linha.get("Valor de mercado")
            if not nome or mercado is None or not np.isfinite(float(mercado)):
                continue
            novos.append(
                Comparavel(
                    nome=nome,
                    valor_mercado=float(mercado),
                    divida_liquida=_num(linha.get("Dívida líquida"), 0.0),
                    receita=_num(linha.get("Receita")),
                    ebitda=_num(linha.get("EBITDA")),
                    ebit=_num(linha.get("EBIT")),
                    lucro_liquido=_num(linha.get("Lucro líquido")),
                    patrimonio_liquido=_num(linha.get("Patrimônio líquido")),
                )
            )
        estado.definir_comparaveis(novos)
        st.success(f"{len(novos)} comparável(is) salvo(s).")
        st.rerun()


def _num(valor, padrao: float = float("nan")) -> float:
    if valor is None:
        return padrao
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return padrao
    return numero if np.isfinite(numero) else padrao


def _alvo_atual() -> Alvo:
    """Monta o alvo a partir do histórico importado ou da projeção do ano 1."""
    empresa = estado.empresa()
    dfs = estado.demonstracoes()
    resultado = estado.resultado()

    if dfs is not None and dfs.tem("receita_liquida"):
        return Alvo(
            nome=empresa.nome,
            receita=dfs.valor("receita_liquida"),
            ebitda=float(dfs.ebitda().dropna().iloc[-1]) if dfs.ebitda().notna().any() else float("nan"),
            ebit=dfs.valor("ebit"),
            lucro_liquido=dfs.valor("lucro_liquido"),
            patrimonio_liquido=dfs.valor("patrimonio_liquido"),
            divida_liquida=empresa.ponte.divida_liquida,
            acoes_em_circulacao=empresa.ponte.acoes_em_circulacao,
        )

    if resultado is not None:
        projecao = resultado.projecao
        return Alvo(
            nome=empresa.nome,
            receita=float(projecao.receita[0]),
            ebitda=float(projecao.ebitda[0]),
            ebit=float(projecao.ebit[0]),
            lucro_liquido=float(projecao.nopat[0]),
            divida_liquida=empresa.ponte.divida_liquida,
            acoes_em_circulacao=empresa.ponte.acoes_em_circulacao,
        )

    return Alvo(nome=empresa.nome, divida_liquida=empresa.ponte.divida_liquida)


def _peer_group(comparaveis) -> None:
    tabela = tabela_comparaveis(comparaveis)
    st.markdown("**Múltiplos de cada comparável**")
    st.html(tabela_de_indicadores(tabela, "multiplo"))
    st.caption(
        "**n/a** marca múltiplo sem significado econômico — EBITDA ou lucro não "
        "positivo. Essas células ficam de fora das estatísticas em vez de puxar a "
        "mediana para um número que não quer dizer nada."
    )

    st.markdown("**Estatísticas do peer group**")
    resumo = estatisticas(comparaveis)
    st.html(tabela_de_indicadores(resumo, "multiplo"))
    st.caption(
        "A mediana é a referência preferida: com peer group pequeno, a média é "
        "facilmente distorcida por um único comparável de múltiplo extremo."
    )


def _implicito(alvo, comparaveis) -> None:
    referencia = st.selectbox(
        "Estatística aplicada ao alvo",
        ["Mediana", "Media", "1o quartil", "3o quartil"],
        index=0,
    )
    tabela = avaliar_por_multiplos(alvo, comparaveis, referencia)
    st.html(tabela_de_indicadores(tabela, "numero"))

    st.caption(
        "Múltiplos de **EV** (EV/Receita, EV/EBITDA, EV/EBIT) produzem o valor da "
        "empresa e passam pela ponte da dívida. Múltiplos de **equity** (P/L, P/VPA) "
        "já produzem o valor do acionista e não passam. Trocar isso é o erro mais "
        "frequente da avaliação relativa."
    )


def _comparar(alvo, comparaveis) -> None:
    resultado = estado.resultado()
    tabela = avaliar_por_multiplos(alvo, comparaveis)
    unidade = estado.empresa().unidade

    rotulos = list(tabela.index)
    valores = [float(v) for v in tabela["Equity Value"]]

    grafico(
        barras_de_faixa(
            rotulos,
            valores,
            referencia=resultado.equity_value if resultado else None,
            rotulo_referencia="DCF",
            titulo="Equity Value implícito por método",
            unidade=unidade,
        ),
        tabela.style.format("{:,.2f}", na_rep="n/a"),
    )

    validos = [v for v in valores if np.isfinite(v)]
    if not validos or resultado is None:
        return

    mediana_multiplos = float(np.median(validos))
    diferenca = (mediana_multiplos - resultado.equity_value) / abs(resultado.equity_value)

    if abs(diferenca) < 0.20:
        st.success(
            f"Os múltiplos sugerem {em_texto(mediana_multiplos, unidade)} contra "
            f"{em_texto(resultado.equity_value, unidade)} do DCF — uma diferença "
            f"de {formatar(abs(diferenca), 'pct')}. As duas abordagens contam a mesma "
            "história, o que reforça o resultado."
        )
    else:
        direcao = "acima" if diferenca > 0 else "abaixo"
        st.warning(
            f"Os múltiplos sugerem {em_texto(mediana_multiplos, unidade)}, "
            f"{formatar(abs(diferenca), 'pct')} {direcao} do DCF. Vale entender a "
            "divergência: ou o mercado precifica algo que a projeção não captura "
            "(ou o contrário), ou o peer group não é tão comparável quanto parece."
        )
