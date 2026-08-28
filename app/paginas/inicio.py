"""Tela inicial: o que o app faz e onde a empresa esta no fluxo."""

from __future__ import annotations

import streamlit as st

from .. import estado
from ..componentes import (
    cartoes,
    em_texto,
    escapar_cifrao,
    etapa,
    formatar,
    secao,
    unidade_curta,
)
from ..navegacao import PASSOS, pagina
from ..textos import AVISO_FINAL, BOAS_VINDAS


def render() -> None:
    etapa("Começo", "Valuation de empresas", "Do histórico ao modelo em Excel")
    st.markdown(BOAS_VINDAS)

    empresa = estado.empresa()
    resultado = estado.resultado()

    st.divider()
    secao("Onde você está")

    fora_do_historico = estado.modelo_fora_do_historico()
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
                "—"
                if resultado is None or fora_do_historico is not None
                else formatar(resultado.equity_value, "moeda"),
            ),
        ]
    )
    # Um Equity Value da empresa de partida sob o nome da companhia importada e
    # pior que um traco: ele e plausivel. Ver `estado.modelo_fora_do_historico`.
    if fora_do_historico is not None:
        st.warning(
            "**O Equity Value ainda não é desta empresa.** O histórico foi "
            f"importado, mas as premissas continuam as de partida — "
            f"{escapar_cifrao(fora_do_historico)}."
        )
        # **Resolver aqui, e nao mandar procurar.** O link levava a Dados e o
        # botao mora no fim daquela tela: quem le o aviso tinha de atravessar e
        # rolar para fazer a unica coisa que o aviso pede. O caminho longo
        # continua existindo para quem quer ver as justificativas de cada
        # premissa, que so cabem la.
        colunas = st.columns([1, 1, 2])
        if colunas[0].button(
            "Derivar do histórico", type="primary", key="derivar_do_inicio"
        ):
            try:
                estado.derivar_premissas_do_historico()
            except ValueError as erro:
                st.error(f"Não consegui derivar premissas: {erro}")
            else:
                st.rerun()
        alvo = pagina("dados")
        if alvo is not None:
            colunas[1].page_link(
                alvo,
                label="Ver de onde vem cada uma",
                icon=":material/database:",
            )
    else:
        _confronto_com_o_mercado(resultado, empresa)

    _quanto_do_qualitativo_foi_respondido()

    st.divider()
    secao(
        "O caminho completo",
        "Você não precisa seguir na ordem — mas se está começando, ela é a mais "
        "produtiva. Clique em qualquer etapa para ir direto.",
    )
    _caminho()

    st.divider()
    st.caption(AVISO_FINAL)



def _quanto_do_qualitativo_foi_respondido() -> None:
    """O estado do trabalho que só o analista faz, na tela de abertura.

    O número de premissas preenchidas o app sabe sozinho; **as dez perguntas de
    framework só avançam com alguém escrevendo**, e por isso o placar delas é o
    que mede quanto do material está pronto. Ele existia dentro da própria tela
    de Qualitativo, que é o único lugar onde não ajuda: quem está lá já está
    fazendo.

    Some sem histórico — sem evidência as perguntas não têm o que ancorar, e um
    "0 de 10" ali seria cobrança por algo que ainda não dá para fazer.
    """
    if not estado.tem_historico():
        return

    from valuation.relatorio import PERGUNTAS_DE_FRAMEWORK

    total = PERGUNTAS_DE_FRAMEWORK
    feitas = len([v for v in estado.respostas_qualitativas().values() if v.strip()])
    alvo = pagina("qualitativo")
    if feitas == total:
        st.caption(f"As {total} perguntas de Porter e VRIO respondidas.")
        return

    st.caption(
        f"**{feitas} de {total}** perguntas de Porter e VRIO respondidas — é a "
        "parte que nenhuma conta deste app faz por você, e a que falta no "
        "relatório enquanto estiver em branco."
    )
    if alvo is not None:
        st.page_link(alvo, label="Responder agora", icon=":material/psychology:")


def _confronto_com_o_mercado(resultado, empresa) -> None:
    """O valor do modelo contra o do mercado, logo na abertura.

    É a pergunta que o app existe para responder, e ela não aparecia em lugar
    nenhum até a oitava tela. Sem preço a linha diz onde informá-lo — omitir o
    bloco esconderia que a comparação é possível.
    """
    de_mercado = estado.valor_de_mercado()
    if de_mercado is None or resultado is None:
        st.caption(
            "Informe a cotação em **Margem de segurança** para ver aqui o valor "
            "de mercado ao lado do que o modelo calcula."
        )
        return

    mercado, quando = de_mercado
    if not mercado:
        return
    distancia = resultado.equity_value / mercado - 1
    leitura = "acima" if distancia > 0 else "abaixo"
    st.caption(
        f"O mercado paga **{em_texto(mercado, empresa.unidade)}**"
        + (f" (preço de {quando})" if quando else "")
        + f" — o modelo vê **{formatar(abs(distancia), 'pct')} {leitura}** disso."
    )

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
