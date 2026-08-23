"""Tela inicial: o que o app faz e onde a empresa esta no fluxo."""

from __future__ import annotations

import streamlit as st

from .. import estado
from ..componentes import cartoes, etapa, formatar, secao, unidade_curta
from ..navegacao import PASSOS, pagina
from ..textos import AVISO_FINAL, BOAS_VINDAS


def render() -> None:
    etapa("Começo", "Valuation de empresas", "Do histórico ao modelo em Excel")
    st.markdown(BOAS_VINDAS)

    empresa = estado.empresa()
    resultado = estado.resultado()

    st.divider()
    secao("Onde você está")

    cartoes(
        [
            ("Empresa", empresa.nome),
            (
                "Histórico importado",
                f"{len(estado.demonstracoes().anos)} anos"
                if estado.tem_historico()
                else "—",
            ),
            (
                "Horizonte projetado",
                f"{empresa.operacionais.horizonte} anos"
                if empresa.operacionais
                else "—",
            ),
            (
                f"Equity Value ({unidade_curta(empresa.unidade)})",
                formatar(resultado.equity_value, "moeda")
                if resultado is not None
                else "—",
            ),
        ]
    )

    st.divider()
    secao(
        "O caminho completo",
        "Você não precisa seguir na ordem — mas se está começando, ela é a mais "
        "produtiva. Clique em qualquer etapa para ir direto.",
    )
    _caminho()

    st.divider()
    st.caption(AVISO_FINAL)


def _caminho() -> None:
    """As etapas como uma lista navegavel, e nao como uma lista de leitura.

    Antes eram doze caixas de texto identicas: para ir a uma delas era preciso
    ler o nome aqui e procura-lo no menu. Cada linha agora e o link da propria
    etapa -- a lista que explica o caminho e a lista que percorre o caminho.

    O numero fica, porque a ordem e a informacao principal desta tela, e o
    historico ja importado marca as etapas que dependiam dele.
    """
    tem_historico = estado.tem_historico()

    for indice, passo in enumerate(PASSOS[1:], start=1):
        alvo = pagina(passo.chave)
        bloqueada = passo.exige == "demonstracoes" and not tem_historico

        with st.container(border=True):
            colunas = st.columns([1, 20], vertical_alignment="center")
            colunas[0].markdown(
                f'<div class="numero-do-passo">{indice}</div>',
                unsafe_allow_html=True,
            )
            with colunas[1]:
                if alvo is not None:
                    st.page_link(
                        alvo,
                        label=f"**{passo.titulo} — {passo.acao}**",
                        icon=passo.icone_material,
                    )
                else:
                    st.markdown(f"**{passo.titulo} — {passo.acao}**")
                st.caption(
                    f"{passo.resumo} _Precisa do histórico importado._"
                    if bloqueada
                    else passo.resumo
                )
