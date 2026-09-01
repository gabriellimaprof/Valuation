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
from valuation.carteira import montar_da_biblioteca

from ..componentes import escapar_cifrao, etapa, secao, unidade_curta


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

    secao(
        "A distância de cada premissa para o histórico",
        "Positivo significa que a projeção pede melhora sobre o que a companhia "
        "entregou — e isso pode ter todo motivo. O número diz onde olhar.",
    )
    distancias = carteira.distancias()
    st.dataframe(
        distancias.style.format("{:+.1%}", na_rep="—").background_gradient(
            cmap="RdYlGn_r", axis=None
        ),
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
    unidades = carteira.unidades
    rotulo_unidade = unidade_curta(next(iter(unidades))) if len(unidades) == 1 else ""
    if rotulo_unidade:
        resumo = resumo.rename(
            columns={
                "Equity value": f"Equity value ({rotulo_unidade})",
                "Valor por acao": "Valor por ação (R$)",
                "Preco": "Preço (R$)",
                "g perpetuo": "g perpétuo",
                "Margem de seguranca": "Margem de segurança",
                "Conversao de caixa": "Conversão de caixa",
            }
        )
    st.dataframe(
        resumo.style.format(
            {
                c: "{:.1%}"
                for c in resumo.columns
                if c
                in (
                    "WACC",
                    "g perpétuo",
                    "Margem de segurança",
                    "Conversão de caixa",
                )
            }
            | {
                c: "{:,.1f}"
                for c in resumo.columns
                if "Equity" in c or "Valor por" in c or "Preço" in c
            },
            na_rep="—",
        ),
        width="stretch",
    )
    st.caption(
        "Margem de segurança só aparece com preço informado — o app não busca "
        "cotação sozinho, e zero ali significaria “está no preço justo”, que é "
        "uma afirmação."
    )
