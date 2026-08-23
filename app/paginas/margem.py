"""Tela de margem de seguranca: a distancia entre o valor e o preco."""

from __future__ import annotations

import numpy as np
import streamlit as st

from valuation.erros import CombinacaoInviavel
from valuation.margem import (
    CARO,
    COM_MARGEM,
    MARGEM_EXIGIDA,
    expectativas_implicitas,
    margem_de_seguranca,
    valor_de_referencia,
)

from .. import estado
from ..componentes import aviso_sem_modelo, em_texto, etapa, formatar, metrica


def render() -> None:
    etapa(
        "Passo 8",
        "Margem de segurança",
        "O valuation só vira decisão quando encontra um preço",
    )

    resultado = estado.resultado()
    if resultado is None:
        aviso_sem_modelo(estado.erro_do_modelo())
        return

    empresa = estado.empresa()
    st.markdown(
        "Um DCF entrega um número, e nenhum número decide nada sozinho. A decisão "
        "está na **distância** entre o valor e o preço pedido — e no tamanho do erro "
        "que essa distância aguenta antes de a tese virar prejuízo."
    )

    preco, por_acao = _entrada_do_preco(resultado, empresa)
    if preco is None:
        return

    try:
        valor, metrica_chave = valor_de_referencia(resultado, por_acao)
    except CombinacaoInviavel as erro:
        st.warning(str(erro))
        return

    exigida = (
        st.slider(
            "Margem exigida (%)",
            min_value=0,
            max_value=60,
            value=int(MARGEM_EXIGIDA * 100),
            step=5,
            help=(
                "Quanto de desconto sobre o valor você exige para comprar. Graham "
                "falava em um terço; é convenção, não lei — o número certo depende "
                "de quanta confiança as premissas merecem."
            ),
        )
        / 100
    )

    m = margem_de_seguranca(valor, preco, exigida=exigida)
    unidade = "" if por_acao else empresa.unidade
    formato = "numero" if por_acao else "moeda"

    _placar(m, unidade, formato)
    st.divider()
    _expectativas(empresa, preco, metrica_chave, m)


def _entrada_do_preco(resultado, empresa):
    guardado = estado.preco()
    colunas = st.columns([2, 3])

    base = colunas[0].radio(
        "Comparar em",
        ["Valor total do equity", "Valor por ação"],
        index=1 if (guardado and guardado["por_acao"]) else 0,
        horizontal=True,
    )
    por_acao = base == "Valor por ação"

    if por_acao and resultado.valor_por_acao is None:
        colunas[1].warning(
            "A ponte não tem número de ações em circulação, então não há valor por "
            "ação. Informe as ações em **Dados** ou compare pelo equity total."
        )
        return None, por_acao

    # **O campo nasce vazio, e não igual ao valor calculado.** Preenchido com o
    # número do próprio DCF ele produzia margem de 0,0% e um "Preço pedido" no
    # placar que se lê como dado de mercado — um usuário leu ali o valor de
    # mercado da WEG e viu R$ 59,8 bi, que é o DCF do app e não a bolsa. O app
    # **não busca cotação em lugar nenhum**; este número vem de fora, e enquanto
    # não vier a tela não deve mostrar comparação nenhuma.
    padrao = (
        float(guardado["valor"])
        if guardado and guardado["por_acao"] == por_acao
        else None
    )

    preco = colunas[1].number_input(
        ("Cotação (R$/ação)" if por_acao else f"Valor de mercado ({empresa.unidade})"),
        value=padrao,
        step=1.0 if por_acao else 10.0,
        min_value=0.0,
        placeholder="quanto o mercado pede",
        help=(
            "**O app não busca cotação.** Este número vem de fora — do home "
            "broker, do site da companhia, de onde você preferir. Sem ele não há "
            "margem de segurança para calcular, porque margem é a distância "
            "entre o que a empresa vale e o que ela custa."
        ),
    )
    with colunas[1]:
        _buscar_cotacao(por_acao, resultado)

    if preco is None or preco <= 0:
        colunas[1].caption("Informe o preço para ver a margem.")
        return None, por_acao

    _mostrar_a_outra_leitura(colunas[1], preco, por_acao, resultado, empresa)

    estado.definir_preco(preco, por_acao=por_acao)
    return preco, por_acao



def _buscar_cotacao(por_acao: bool, resultado) -> None:
    """Busca o preço na B3 — **só quando o usuário pede**.

    Mesma regra do risco-país pela NTN-B e do Focus: nada é buscado ao abrir a
    tela, e nada troca sozinho. O botão preenche o campo e o usuário confirma —
    porque a fonte é um endpoint **não documentado** do Yahoo, que pode mudar ou
    sair do ar sem aviso, e um valuation não pode depender disso.

    As alternativas foram medidas antes: `brapi.dev` responde 401 e exige token
    (guardar credencial contraria a regra de o app não gravar nada em disco), e
    o stooq não tem os papéis da B3.
    """
    from valuation.mercado import ErroMercado, cotacao

    with st.popover("Buscar cotação na B3", width="stretch"):
        st.caption(
            "Fonte externa e **não oficial** (Yahoo Finance). O app não busca "
            "nada sozinho, e o número preenchido continua editável."
        )
        sugerido = _papel_sugerido()
        ticker = st.text_input(
            "Código do papel",
            value=sugerido or "",
            placeholder="WEGE3",
            key="ticker_b3",
            help=(
                "O cadastro da CVM **não traz o ticker**, então o app o procura "
                "pelo nome — e acha em cerca de 40% das companhias. Quando não "
                "acha, digite; o que você digitar fica lembrado."
            ),
        )
        if sugerido:
            st.caption(f"Sugerido pelo nome da companhia: **{sugerido}**. Confira.")
        if not st.button("Buscar", key="botao_cotacao") or not ticker.strip():
            return
        # O ticker confirmado fica na sessao: da segunda vez em diante nao ha
        # busca por nome nenhuma, e nem digitacao.
        estado.definir_config("ticker", ticker.strip().upper())

        try:
            achada = cotacao(ticker)
        except ErroMercado as erro:
            st.warning(f"Não consegui buscar: {erro}")
            return

        acoes = resultado.empresa.ponte.acoes_em_circulacao
        st.success(
            f"**{achada.nome}** — {em_texto(achada.preco, 'R$')} por ação, "
            f"negociado em {achada.negociado_em:%d/%m/%Y}."
        )
        if acoes:
            st.caption(
                "Valor de mercado: "
                f"**{em_texto(achada.valor_de_mercado(acoes), estado.empresa().unidade)}**"
            )
        # O valor vai para o campo, e nao direto para o modelo: quem decide se
        # aquele preco e o que interessa e quem esta olhando.
        estado.definir_preco(
            achada.preco if por_acao else achada.valor_de_mercado(acoes or 0.0),
            por_acao=por_acao,
        )
        st.rerun()


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _procurar_papel(nome: str):
    """Busca o papel pelo nome, no máximo uma vez por dia por companhia."""
    from valuation.mercado import procurar_papel

    return [p.ticker for p in procurar_papel(nome)]


def _papel_sugerido() -> str:
    """O ticker desta companhia: o confirmado, ou o que a busca sugere.

    **Sugestão, e não preenchimento.** Medido em 40 companhias sorteadas, a
    busca do Yahoo acha o papel certo em 40% e **devolve o papel de outra
    companhia em 0%** — o modo de falha é "não achei", que é visível. É esse
    número que permite mostrar o resultado no campo em vez de escondê-lo: o
    usuário vê o ticker antes de qualquer preço aparecer.

    Entre os 60% que ela não acha há companhia de capital fechado, onde "não
    achei" é a resposta certa, e listadas que ela perde mesmo assim — o Banco do
    Brasil é uma delas.
    """
    confirmado = estado.config().get("ticker")
    if confirmado:
        return confirmado

    dfs = estado.demonstracoes()
    nome = getattr(dfs, "empresa", "") if dfs is not None else ""
    if not nome:
        return ""
    try:
        achados = _procurar_papel(nome)
    except Exception:  # noqa: BLE001 - sugestao nunca derruba a tela
        return ""
    return achados[0] if achados else ""


def _mostrar_a_outra_leitura(coluna, preco, por_acao, resultado, empresa) -> None:
    """Cotação e valor de mercado, um ao lado do outro.

    Quem digita a cotação quer conferir o valor de mercado que ela implica, e
    quem digita o total quer o preço por ação. Sem isto o usuário sai da tela
    para multiplicar — e o número de ações já está aqui, lido da composição de
    capital que a CVM publica junto da DFP.
    """
    acoes = resultado.empresa.ponte.acoes_em_circulacao
    if not acoes:
        return
    if por_acao:
        coluna.caption(
            f"Valor de mercado implícito: **{em_texto(preco * acoes, empresa.unidade)}** "
            f"({formatar(acoes, 'numero')} ações em circulação)"
        )
    else:
        coluna.caption(
            rf"Cotação implícita: **R\$ {formatar(preco / acoes, 'numero')}** "
            f"({formatar(acoes, 'numero')} ações em circulação)"
        )


def _placar(m, unidade: str, formato: str) -> None:
    colunas = st.columns(4)
    with colunas[0]:
        metrica("Valor calculado", m.valor, formato, unidade)
    with colunas[1]:
        metrica("Preço pedido", m.preco, formato, unidade)
    with colunas[2]:
        metrica("Margem sobre o valor", m.margem, "pct")
    with colunas[3]:
        metrica("Potencial sobre o preço", m.potencial, "pct")

    st.caption(
        "Os dois últimos medem a mesma distância com denominadores diferentes: "
        "comprar a 70 o que vale 100 é **30% de margem** e **42,9% de potencial**. "
        "Quem exige “30% de margem” quase sempre quer dizer o primeiro."
    )

    if m.veredito == COM_MARGEM:
        st.success(m.resumo())
    elif m.veredito == CARO:
        st.error(m.resumo())
    else:
        st.warning(m.resumo())

    st.caption(
        f"Preço máximo para manter {formatar(m.exigida, 'pct')} de margem: "
        f"**{formatar(m.preco_maximo, formato, unidade)}**."
    )


def _expectativas(empresa, preco, metrica_chave, m) -> None:
    st.subheader("O que o mercado precisa acreditar")
    st.markdown(
        "O DCF ao contrário: para cada premissa, qual valor faria o modelo dar "
        "exatamente o preço pedido. É o que desarma a discussão improdutiva sobre "
        "quem tem o modelo certo — *“a este preço o mercado embute margem de 16,4%, "
        "contra os 20,1% que a empresa entregou”* é uma afirmação que dá para checar."
    )

    with st.spinner("Invertendo o modelo, uma premissa de cada vez..."):
        tabela = expectativas_implicitas(
            empresa, preco, metrica=metrica_chave, **estado.convencoes()
        )

    st.session_state["expectativas_implicitas"] = tabela

    visivel = tabela.drop(columns=["caminho"])
    st.dataframe(
        visivel.style.format(lambda v: formatar(v, "pct2") if np.isfinite(v) else "—"),
        width="stretch",
    )

    faltando = visivel["Implícita no preço"].isna()
    if faltando.any():
        nomes = ", ".join(visivel.index[faltando])
        st.info(
            f"Sem solução dentro da faixa plausível para: **{nomes}**. Isso é uma "
            "resposta, não uma falha — significa que nenhum valor razoável dessa "
            "premissa, sozinho, justifica o preço."
        )

    validos = visivel.dropna(subset=["Diferença"])
    if validos.empty:
        return

    if abs(m.margem) < 1e-6:
        st.markdown(
            "O preço é o próprio valor calculado, então nada precisa mudar — por isso "
            "a coluna **Diferença** está zerada. Troque o preço pela cotação de "
            "mercado para a tabela dizer alguma coisa."
        )
        return

    apertada = validos["Diferença"].abs().idxmin()
    linha = validos.loc[apertada]
    direcao = "abaixo" if linha["Diferença"] < 0 else "acima"
    if m.veredito == CARO:
        leitura = (
            f"O preço já está acima do valor, então estas são as premissas que "
            f"teriam de **melhorar** para justificá-lo. A mais próxima é "
            f"**{apertada}**: {formatar(abs(linha['Diferença']), 'pct2')} {direcao} "
            "do que está no modelo."
        )
    else:
        leitura = (
            f"A premissa com menos folga é **{apertada}**: bastam "
            f"{formatar(abs(linha['Diferença']), 'pct2')} {direcao} do que está no "
            "modelo para o valor encostar no preço. É de lá que vem o risco desta "
            "tese, e é ela que merece a próxima hora de trabalho."
        )
    st.markdown(leitura)
