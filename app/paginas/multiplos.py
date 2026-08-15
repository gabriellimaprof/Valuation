"""Tela de avaliacao relativa por multiplos de comparaveis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from valuation import Alvo, Comparavel, avaliar_por_multiplos, estatisticas, tabela_comparaveis

from .. import estado
from ..componentes import conceito, etapa, formatar, grafico
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

    abas = st.tabs(["Múltiplos do peer group", "Valor implícito", "Comparação com o DCF"])
    with abas[0]:
        _peer_group(comparaveis)
    with abas[1]:
        _implicito(alvo, comparaveis)
    with abas[2]:
        _comparar(alvo, comparaveis)


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
    st.dataframe(tabela.style.format("{:,.2f}", na_rep="n/a"), width="stretch")
    st.caption(
        "**n/a** marca múltiplo sem significado econômico — EBITDA ou lucro não "
        "positivo. Essas células ficam de fora das estatísticas em vez de puxar a "
        "mediana para um número que não quer dizer nada."
    )

    st.markdown("**Estatísticas do peer group**")
    resumo = estatisticas(comparaveis)
    st.dataframe(
        resumo.style.format(
            {c: "{:,.2f}" for c in resumo.columns if c != "n"}, na_rep="n/a"
        ),
        width="stretch",
    )
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
    st.dataframe(tabela.style.format("{:,.2f}", na_rep="n/a"), width="stretch")

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
            f"Os múltiplos sugerem {formatar(mediana_multiplos, 'moeda', unidade)} contra "
            f"{formatar(resultado.equity_value, 'moeda', unidade)} do DCF — uma diferença "
            f"de {formatar(abs(diferenca), 'pct')}. As duas abordagens contam a mesma "
            "história, o que reforça o resultado."
        )
    else:
        direcao = "acima" if diferenca > 0 else "abaixo"
        st.warning(
            f"Os múltiplos sugerem {formatar(mediana_multiplos, 'moeda', unidade)}, "
            f"{formatar(abs(diferenca), 'pct')} {direcao} do DCF. Vale entender a "
            "divergência: ou o mercado precifica algo que a projeção não captura "
            "(ou o contrário), ou o peer group não é tão comparável quanto parece."
        )
