"""Porter e VRIO: a evidencia medida, e a resposta que so o analista escreve.

Ate aqui esta secao existia **so no relatorio exportado**. Era a parte do
material que mais pede julgamento e a unica que o usuario nao podia ver antes de
gerar o arquivo -- e, pior, nao tinha onde escrever: o relatorio saia com o campo
em branco e o analista preenchia fora do app, num documento que nao volta.

A tela nao muda o principio do modulo do motor: **ela nao responde nada**. Traz o
que foi medido, diz o que os dados nao alcancam e abre o campo. O que ela
acrescenta e que a resposta agora **fica**, porque viaja no projeto salvo.
"""

from __future__ import annotations

import streamlit as st

from valuation.qualitativo import (
    por_que_nao_se_aplica,
    reunir_evidencias,
    reunir_vrio,
)

from .. import estado
from ..componentes import etapa, secao


def render() -> None:
    etapa(
        "Passo 10",
        "Qualitativo",
        "As perguntas que os números não respondem — com o que eles dizem sobre elas",
    )

    analise = estado.analise()
    if analise is None:
        st.info(
            "Nenhuma demonstração importada ainda. Vá em **Dados**: sem histórico "
            "não há evidência para sustentar nenhuma das perguntas, e a tela "
            "viraria um formulário em branco."
        )
        return

    # **A mesma recusa que o relatório já fazia.** Ele deixa a seção de fora no
    # caminho do banco; a tela mostrava os blocos, com margem EBITDA e capex
    # sobre receita descrevendo uma instituição financeira. A proteção existia
    # num consumidor e não no outro.
    recusa = por_que_nao_se_aplica(analise)
    if recusa is not None:
        st.warning(recusa)
        st.caption(
            "As perguntas continuam suas para responder — o que falta é a "
            "evidência, e ela pede indicadores de banco que este app não monta: "
            "custo de funding, composição da carteira, índice de capital."
        )
        return

    resultado = estado.resultado()
    if resultado is None:
        st.warning(
            "**As premissas atuais não fecham**, então os blocos que comparam com "
            "o WACC ficam sem essa metade. O resto da evidência não depende do "
            "modelo e continua aqui."
        )

    st.markdown(
        "Cada bloco traz a **pergunta**, o que foi **medido** sobre ela e o que os "
        "dados **não alcançam**. A resposta fica com você: nenhuma conta deste app "
        "sabe se a marca é forte, quando vence a concessão ou o que o concorrente "
        "fez semana passada. O que você escrever é salvo com o valuation."
    )

    respondidas = estado.respostas_qualitativas()
    abas = st.tabs(["Cinco forças e fosso", "VRIO"])
    with abas[0]:
        _blocos(reunir_evidencias(analise, resultado), respondidas)
    with abas[1]:
        st.caption(
            "As quatro perguntas de Barney não se distribuem igualmente entre "
            "medível e opinável — **imitabilidade é a que os dados menos "
            "alcançam**, e o bloco dela diz isso em vez de fingir um número. Não "
            "há nota de 1 a 5: pontuar converteria julgamento em medida."
        )
        _blocos(reunir_vrio(analise, resultado), respondidas)

    _placar(respondidas)


def _blocos(evidencias, respondidas: dict[str, str]) -> None:
    """Um expander por pergunta, aberto quando ainda não foi respondida."""
    for evidencia in evidencias:
        ja = respondidas.get(evidencia.tema, "")
        marca = "✍️" if ja else "○"
        with st.expander(f"{marca} {evidencia.tema}", expanded=not ja):
            st.markdown(f"**{evidencia.pergunta}**")

            if evidencia.medido:
                secao("O que foi medido")
                for linha in evidencia.medido:
                    st.markdown(f"- {linha}")
            else:
                # Ausencia declarada, e nao secao omitida: ameaca de substitutos
                # nao tem contrapartida contabil nenhuma, e sumir com ela faria
                # parecer que a pergunta nao existe.
                st.info(
                    "**Nada nas demonstrações responde a esta pergunta.** Ela "
                    "está aqui porque some-la faria parecer que não importa."
                )

            if evidencia.limite:
                st.caption(f"**O que os números não alcançam:** {evidencia.limite}")

            texto = st.text_area(
                "Sua resposta",
                value=ja,
                key=f"qual_{evidencia.tema}",
                height=120,
                placeholder="O que você conclui, e com base em quê.",
                label_visibility="collapsed",
            )
            if texto.strip() != ja:
                estado.definir_resposta_qualitativa(evidencia.tema, texto)


def _placar(respondidas: dict[str, str]) -> None:
    """Quantas das dez perguntas ja tem resposta escrita.

    O total vem do relatorio, e nao de um `10` escrito aqui: os dois contam a
    mesma coisa, e duas copias divergem no dia em que uma pergunta entrar.
    """
    from valuation.relatorio import PERGUNTAS_DE_FRAMEWORK

    total = PERGUNTAS_DE_FRAMEWORK
    feitas = len([v for v in respondidas.values() if v.strip()])
    st.divider()
    if feitas == 0:
        st.caption(
            f"Nenhuma das {total} perguntas respondida. O relatório exportado sai "
            "com os campos em branco — o que é honesto, e não é o material pronto."
        )
    elif feitas < total:
        st.caption(
            f"**{feitas} de {total}** respondidas. As demais saem em branco no "
            "relatório, marcadas como não respondidas."
        )
    else:
        st.success(f"As {total} perguntas respondidas. O relatório sai completo.")
