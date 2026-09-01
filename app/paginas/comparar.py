"""Varios valuations lado a lado, e a distancia de cada um para o proprio passado.

Nao e um passo do caminho de uma empresa -- e a mesa onde tres ou quatro delas se
olham juntas. Por isso entra depois de Exportar: primeiro se monta um valuation,
depois se compara o que foi montado.

**A tela depende da biblioteca, que nasce desligada.** Sem
``VALUATION_BIBLIOTECA`` nao ha valuations guardados para comparar, e a tela diz
isso em vez de existir vazia -- a mesma propriedade que o botao de salvar ja
tem: quando desligada, ela nao promete o que nao pode entregar.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from valuation import biblioteca
from valuation.apresentacao import escala_do_documento
from valuation.carteira import montar_da_biblioteca

from ..componentes import (
    escapar_cifrao,
    etapa,
    pintar_por_intensidade,
    secao,
    unidade_curta,
)


def render() -> None:
    etapa(
        "Comparar",
        "Vários modelos lado a lado",
        "As premissas de cada um contra o que aquela companhia entregou",
    )

    if not biblioteca.esta_ligada():
        st.info(
            "**A biblioteca de valuations está desligada.** Ela é onde os modelos "
            "salvos ficam, e é ela que esta tela compara. Para ligá-la, defina a "
            "variável de ambiente `VALUATION_BIBLIOTECA` apontando para uma pasta "
            "na sua máquina — o app só grava em disco quando você manda."
        )
        return

    entradas = [e for e in biblioteca.listar() if e.legivel]
    if len(entradas) < 2:
        st.info(
            "**Há menos de dois valuations guardados.** Comparação precisa de "
            "dois: com um só, toda frase desta tela seria sobre nada. Salve "
            "modelos em **Exportar** e volte aqui."
        )
        return

    st.caption(
        "O que se compara entre negócios diferentes **não é o nível da premissa** "
        "— margem de 22% numa varejista e de 31% numa geradora não dizem qual "
        "projeção é mais agressiva. É a **distância** entre o que se projetou e o "
        "que aquela companhia entregou: essa atravessa setores."
    )

    rotulos = {f"{e.empresa} · {e.periodo}": e.caminho for e in entradas}
    escolhidos = st.multiselect(
        "Modelos na mesa",
        options=list(rotulos),
        default=list(rotulos)[: min(3, len(rotulos))],
        help="Duas versões da mesma companhia são tão comparáveis quanto duas companhias.",
    )
    if len(escolhidos) < 2:
        st.info("Escolha ao menos dois modelos.")
        return

    carteira = montar_da_biblioteca([rotulos[r] for r in escolhidos])

    quebrados = [m for m in carteira.modelos if not m.legivel]
    for m in quebrados:
        st.warning(
            escapar_cifrao(
                f"**{m.nome}** não pôde ser avaliado e ficou de fora da "
                f"comparação: {m.erro}"
            )
        )
    if len(carteira.legiveis) < 2:
        return

    for frase in carteira.leitura():
        st.markdown(escapar_cifrao(frase))

    proximidade = carteira.proximidade()
    if not proximidade.empty:
        with st.expander("Estes modelos são comparáveis entre si?"):
            st.caption(
                "Distância de perfil econômico, pelo critério de `pares.py` — "
                "risco, crescimento e fluxo de caixa parecidos. Na base, a "
                "mediana entre companhias quaisquer é **1,3**; os pares mais "
                "próximos da WEG ficam entre 0,28 e 0,41."
            )
            st.dataframe(
                pintar_por_intensidade(proximidade).format("{:.2f}", na_rep="—"),
                width="stretch",
            )

    secao(
        "A distância de cada premissa para o histórico",
        "Positivo significa que a projeção pede melhora sobre o que a companhia "
        "entregou — e isso pode ter todo motivo. O número diz onde olhar.",
    )
    distancias = carteira.distancias()
    st.dataframe(
        pintar_por_intensidade(distancias).format("{:+.1%}", na_rep="—"),
        width="stretch",
    )

    with st.expander("Ver projetado e entregue, lado a lado"):
        st.caption(
            "As duas colunas que sustentam a distância. Elas **não** se comparam "
            "na horizontal: só a distância faz sentido entre companhias."
        )
        st.dataframe(
            carteira.premissas().style.format("{:.1%}", na_rep="—"),
            width="stretch",
        )

    secao("O que cada modelo diz que a companhia vale")
    resumo = carteira.resumo()

    # **A escala e uma so para a tabela**, pelo maior equity que ela mostra, e
    # declarada no cabecalho -- "17.686.979.396,2" e um numero que ninguem
    # processa, e trocar de escala entre linhas faria comparar bilhao com milhao
    # sem perceber. E a mesma decisao do material do comite.
    divisor, sufixo = escala_do_documento(resumo.get("Equity value", pd.Series(dtype=float)))
    unidades = carteira.unidades
    base = unidade_curta(next(iter(unidades))) if len(unidades) == 1 else ""
    rotulo_valor = " ".join(x for x in (base, sufixo) if x) or "valor"
    if "Equity value" in resumo.columns:
        resumo["Equity value"] = resumo["Equity value"] / divisor

    resumo = resumo.rename(
        columns={
            "Equity value": f"Equity value ({rotulo_valor})",
            "Valor por acao": "Valor por ação (R$)",
            "Preco": "Preço (R$)",
            "g perpetuo": "g perpétuo",
            "Margem de seguranca": "Margem de segurança",
            "Conversao de caixa": "Conversão de caixa",
        }
    )
    # **Coluna inteiramente vazia nao vira coluna.** O `st.dataframe` mostra o
    # nulo bruto do Arrow -- "None" em toda linha --, e mesmo com travessao uma
    # coluna sem nenhum numero nao informa nada. A ausencia fica na legenda, que
    # diz **por que** ela nao esta la.
    vazias = [c for c in resumo.columns if resumo[c].isna().all()]
    resumo = resumo.drop(columns=vazias)

    percentuais = [
        c
        for c in resumo.columns
        if c in ("WACC", "g perpétuo", "Margem de segurança", "Conversão de caixa")
    ]
    monetarias = [
        c for c in resumo.columns if "Equity" in c or "Valor por" in c or "Preço" in c
    ]
    st.dataframe(
        resumo.style.format(
            {c: "{:.1%}" for c in percentuais} | {c: "{:,.1f}" for c in monetarias},
            # `None` numa coluna vazia se le como um valor; o travessao diz que
            # nao ha numero. O `subset` e o que faz o `na_rep` alcancar tambem as
            # colunas de texto, onde o Styler nao o aplicaria sozinho.
            na_rep="—",
            subset=percentuais + monetarias,
        ),
        width="stretch",
    )
    st.caption(
        "Margem de segurança só aparece com preço informado — o app não busca "
        "cotação sozinho, e zero ali significaria “está no preço justo”, que é "
        "uma afirmação."
    )
