"""Tela de custo de capital: montagem do Ke pelo CAPM e do WACC."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import streamlit as st

from valuation.premissas import METODOS_DE_CUSTO_DE_CAPITAL
from valuation.dados_setoriais import (
    AVISO_REFERENCIA,
    PAISES_POR_NOME,
    SETORES,
    buscar_setor,
    listar_setores,
)

from .. import estado
from ..componentes import conceito, etapa, formatar, metrica, secao


def render() -> None:
    etapa("Passo 4", "Custo de capital", "A taxa que traz o futuro para hoje")

    conceito("wacc", "O que estamos montando")

    empresa = estado.empresa()
    premissas = empresa.custo_capital

    abas = st.tabs(
        [
            "Montagem",
            "Como o número se forma",
            "Risco-país pela curva",
            "Referências por setor",
        ]
    )

    with abas[0]:
        _montagem(empresa, premissas)
    with abas[1]:
        _decomposicao()
    with abas[2]:
        _risco_pais_de_mercado(empresa)
    with abas[3]:
        _referencias()


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _medida_de_mercado(rf_usd: float, inflacao_usd: float, anos: int):
    """Busca curva e Focus. Em cache por uma hora: a curva é diária.

    O cache é por argumento, então trocar o rf refaz a conta sem rebaixar o
    arquivo de 30 MB do Tesouro de novo.
    """
    from valuation.mercado import medir_risco_pais

    return medir_risco_pais(rf_usd=rf_usd, inflacao_usd=inflacao_usd, anos=anos)


def _risco_pais_de_mercado(empresa) -> None:
    """O prêmio de risco-país observado, em vez do valor de referência."""
    from valuation.mercado import ANOS_REFERENCIA, ErroMercado

    premissas = empresa.custo_capital
    st.markdown(
        "O risco-país embarcado no app é um valor de referência. A curva de NTN-B "
        "permite **observá-lo**: a taxa real longa, nominalizada pela inflação "
        "esperada, comparada com o Treasury americano convertido para reais pelo "
        "mesmo diferencial de inflação que o motor já usa."
    )

    st.info(
        "**Esta medida é um piso, não um ponto.** A NTN-B é indexada: quem a carrega "
        "não corre risco de inflação, e quem carrega título nominal corre e cobra por "
        "isso. Nominalizar só pela inflação esperada omite esse prêmio, então o "
        "risco-país sai subestimado. A correção — usar a inflação implícita entre "
        "prefixado e NTN-B de mesmo prazo — está ao alcance e ainda não foi feita."
    )

    colunas = st.columns(3)
    anos = colunas[0].number_input(
        "Prazo de referência (anos)",
        min_value=3,
        max_value=30,
        value=ANOS_REFERENCIA,
        help="Longo o bastante para não depender do ciclo de juros, curto o bastante "
        "para ter liquidez.",
    )
    colunas[1].metric("Risco-país no modelo", formatar(premissas.risco_pais, "pct2"), border=True)

    if not colunas[2].button("Medir agora", type="primary"):
        st.caption(
            "A medição baixa a curva do Tesouro Direto e as projeções do Focus. "
            "Nada é buscado sem você pedir."
        )
        return

    try:
        with st.spinner("Baixando a curva do Tesouro e o Focus..."):
            medida = _medida_de_mercado(premissas.rf_usd, empresa.macro.inflacao_usd, int(anos))
    except ErroMercado as erro:
        st.error(f"Não consegui medir: {erro}")
        return

    colunas = st.columns(4)
    with colunas[0]:
        metrica("NTN-B (taxa real)", medida.taxa_real_ntnb, "pct2")
    with colunas[1]:
        metrica("Nominalizada em BRL", medida.rf_brl_nominal, "pct2")
    with colunas[2]:
        metrica("Treasury convertido", medida.rf_usd_em_brl, "pct2")
    with colunas[3]:
        metrica(
            "Risco-país implícito",
            medida.diferenca,
            "pct2",
            delta=formatar(medida.diferenca - premissas.risco_pais, "pct2"),
        )

    st.markdown(medida.explicacao)
    st.warning(medida.ressalva)
    st.markdown(
        "**O padrão do app não muda sozinho.** Medido em 120 companhias, trocar o "
        "risco-país de referência pelo implícito derrubou a mediana do equity value "
        "em 35,7%. Reprecificar uma carteira inteira por conta de um número que a "
        "própria função adverte não ser risco soberano puro é decisão de quem tem o "
        "julgamento, não do app."
    )

    if st.button(f"Usar {formatar(medida.diferenca, 'pct2')} no modelo"):
        estado.atualizar({"custo_capital.risco_pais": float(medida.diferenca)})
        st.rerun()






@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def _taxa_real_do_dia():
    """A taxa real da NTN-B, buscada no máximo uma vez por dia.

    O cache é duplo de propósito: o do Streamlit evita repetir a chamada dentro
    da sessão, e o de disco em `mercado.taxa_real_ntnb` faz a busca acontecer
    **uma vez por dia por máquina** — a primeira sessão do dia paga os ~6s, as
    demais leem um JSON de duas linhas em 0,02s.
    """
    from valuation.mercado import taxa_real_ntnb

    return taxa_real_ntnb()


def _taxa_real_de_partida() -> tuple[float, str]:
    """A taxa real com que o campo abre, e de onde ela veio.

    **Automática, e não silenciosa.** A atualização acontece sem clique — que é
    o que se espera de uma taxa de mercado —, mas a origem vai escrita ao lado
    do campo. Sem isso, o número de hoje e o embarcado de três meses atrás teriam
    a mesma aparência, que é o defeito que a safra dos percentis já custou.

    Rede fora não é erro: cai na referência embarcada e diz que caiu.
    """
    from valuation.custo_capital import (
        NTNB_REAL_REFERENCIA,
        idade_da_referencia_ntnb,
    )
    from valuation.mercado import ErroMercado

    try:
        do_dia = _taxa_real_do_dia()
    except (ErroMercado, ValueError):
        dias = idade_da_referencia_ntnb()
        return NTNB_REAL_REFERENCIA, (
            f"⚠️ Sem conexão com o Tesouro: usando o valor de referência de "
            f"{dias} dia(s) atrás."
        )

    if do_dia.dias == 0:
        quando = "hoje"
    elif do_dia.dias == 1:
        quando = "ontem"
    else:
        quando = f"há {do_dia.dias} dias"
    return do_dia.taxa, (
        f"Curva do Tesouro, coletada **{quando}** ({do_dia.coletada_em:%d/%m/%Y}). "
        "Atualiza sozinho uma vez por dia."
    )


def _campos_em_dolar(premissas, paises):
    """Taxa americana, prêmio maduro e risco-país — a construção original."""
    colunas = st.columns(4)
    pais = colunas[0].selectbox(
        "País", paises, index=paises.index(estado.config().get("pais", "Brasil"))
    )
    dados_pais = PAISES_POR_NOME[pais]

    rf = colunas[1].number_input(
        "Taxa livre de risco em USD (%)",
        value=float(premissas.rf_usd * 100),
        step=0.1,
        format="%.2f",
        help="T-Bond de 10 anos. O modelo monta o Ke em USD e converte para a moeda local.",
    )
    colunas[1].caption(
        "De fonte externa — o app não busca. Confira a data."
    )
    erp = colunas[2].number_input(
        "Prêmio de risco de mercado maduro (%)",
        value=float(premissas.erp_maduro * 100),
        step=0.1,
        format="%.2f",
    )
    colunas[2].caption(
        "Referência de ordem de grandeza, e não a base oficial do Damodaran."
    )
    risco_pais = colunas[3].number_input(
        "Prêmio de risco-país (%)",
        value=float(dados_pais.risco_pais * 100),
        step=0.1,
        format="%.2f",
    )
    colunas[3].caption(
        "Valor de **referência**, não medido. A aba **Risco-país pela curva** "
        "mede o que o mercado cobra hoje, pela NTN-B."
    )
    return pais, rf, erp, risco_pais


def _campos_locais(premissas, empresa, paises):
    """NTN-B nominalizada como `rf`, e o prêmio de risco local.

    **Aqui não há termo de risco-país**, e a ausência é a decisão: o soberano
    brasileiro já embute risco de crédito do país e expectativa de inflação.
    Somar um prêmio de risco-país em cima seria contá-lo duas vezes — o mesmo
    erro que o caminho em dólar evita, pelo outro lado.

    O custo desta construção está no prêmio de risco: um ERP estimado na série
    brasileira é ruidoso demais para ser observado, então ele é **premissa do
    analista** — e é o número que mais move o Ke aqui.
    """
    from valuation.custo_capital import rf_local

    ipca = empresa.macro.inflacao_brl
    colunas = st.columns(4)

    pais = colunas[0].selectbox(
        "País", paises, index=paises.index(estado.config().get("pais", "Brasil"))
    )

    # A taxa que **você** digitou ganha de tudo. Sem ela, a do dia, buscada
    # automaticamente; sem rede, a de referência embarcada. As três aparecem
    # rotuladas: um número de mercado sem data é indistinguível de um embarcado.
    real_padrao = premissas.rf_brl
    origem = None
    if real_padrao is None:
        real_padrao, origem = _taxa_real_de_partida()
    else:
        real_padrao = (1 + real_padrao) / (1 + ipca) - 1
    taxa_real = colunas[1].number_input(
        "NTN-B — taxa real (%)",
        value=float(real_padrao * 100),
        step=0.1,
        format="%.2f",
        help=(
            "A taxa real do título indexado. Use um vencimento longo, próximo do "
            "horizonte do valuation."
        ),
    )
    if origem:
        colunas[1].caption(origem)
    rf_brl = rf_local(taxa_real / 100, ipca)
    colunas[1].caption(
        f"Nominalizada a {formatar(ipca, 'pct')} de IPCA: "
        f"**{formatar(rf_brl, 'pct')}** — composto, não somado."
    )

    erp_local = colunas[2].number_input(
        "Prêmio de risco de ações local (%)",
        value=float(premissas.erp_local * 100),
        step=0.25,
        format="%.2f",
        help=(
            "Quanto se exige de uma ação **acima do soberano brasileiro**. Não é "
            "observável com precisão: a série brasileira é curta e volátil "
            "demais para estimá-lo, e por isso ele é premissa e não medida."
        ),
    )
    with colunas[2]:
        _baliza_do_premio_local(premissas, empresa, rf_brl, erp_local / 100)
    colunas[3].info(
        "**Não há risco-país neste caminho.** Ele já está dentro da NTN-B — "
        "somá-lo de novo o contaria duas vezes."
    )
    _buscar_ntnb(ipca)
    return pais, premissas.rf_usd * 100, premissas.erp_maduro * 100, 0.0, rf_brl, erp_local / 100



def _baliza_do_premio_local(premissas, empresa, rf_brl: float, erp: float) -> None:
    """O prêmio local não é observável — mas o Ke que ele produz é comparável.

    Não há percentil aqui, e inventar um seria pior que não ter: a série
    brasileira é curta e volátil demais para estimar um prêmio de ações, e é
    exatamente por isso que este campo é premissa. As duas âncoras que existem
    são indiretas e honestas:

    * **o Ke que sai** — o número que de fato desconta o fluxo, mostrado junto
      do prêmio para a escolha não ser abstrata;
    * **o que o outro caminho daria** com o mesmo beta. Os dois discordam por
      construção, e a distância entre eles é a informação: ela mede o quanto o
      prêmio escolhido se afasta do que o mercado americano mais risco-país
      implicaria.
    """
    from valuation.custo_capital import calcular_custo_capital

    ke = rf_brl + premissas.premio_tamanho
    try:
        em_dolar = calcular_custo_capital(
            replace(premissas, metodo="usd"), empresa.macro
        )
        ke_local = rf_brl + em_dolar.beta_realavancado * erp + premissas.premio_tamanho
        st.caption(
            f"Com este prêmio o Ke sai **{formatar(ke_local, 'pct')}**. "
            f"Pelo caminho em dólar, com o mesmo beta, sairia "
            f"{formatar(em_dolar.ke_brl, 'pct')}."
        )
    except (ValueError, ZeroDivisionError):
        st.caption(f"Sobre um soberano de {formatar(ke, 'pct')}.")


def _buscar_ntnb(ipca: float) -> None:
    """A curva de verdade, a um clique — e nada é buscado sem o clique.

    O resultado **pode ser aplicado**, e antes não podia: a versão anterior só
    mostrava o número e mandava digitar acima. Ler um número na tela e
    transcrevê-lo à mão dois centímetros abaixo é trabalho braçal, e é onde
    entra erro de digitação — justamente no campo que decide o WACC inteiro.

    Aplicar continua sendo **decisão de quem clica**: o botão existe, mas nada
    acontece sem ele.
    """
    from valuation.custo_capital import rf_local
    from valuation.mercado import ErroMercado, curva_ntnb, taxa_real_longa

    with st.popover("Buscar a curva de NTN-B", width="stretch"):
        st.caption(
            "Tesouro Transparente, fonte oficial. Nada é buscado ao abrir a "
            "tela, e o número **não troca sozinho**."
        )
        if st.button("Buscar a curva", key="botao_ntnb"):
            try:
                st.session_state["ntnb_buscada"] = taxa_real_longa(curva_ntnb())
            except (ErroMercado, ValueError) as erro:
                st.warning(f"Não consegui buscar: {erro}")
                return

        real = st.session_state.get("ntnb_buscada")
        if real is None:
            return

        st.success(
            f"Taxa real longa: **{formatar(real, 'pct')}**. "
            f"Nominalizada a {formatar(ipca, 'pct')} de IPCA, o rf fica em "
            f"**{formatar(rf_local(real, ipca), 'pct')}**."
        )
        if st.button("Usar esta taxa", key="usar_ntnb", type="primary"):
            estado.atualizar({"custo_capital.rf_brl": rf_local(real, ipca)})
            st.session_state.pop("ntnb_buscada", None)
            st.rerun()


def _baliza_do_kd(kd: float) -> None:
    """O que a empresa **paga**, contra o que foi digitado.

    É a âncora mais forte desta tela e o app já a calculava: o juro pago da DFC
    sobre a dívida média. Ela estava em Histórico, e quem preenchia o Kd aqui
    tinha de ir buscá-la lá.

    As duas leituras aparecem porque discordam de propósito. A de **competência**
    — despesa financeira da DRE sobre dívida — costuma superestimar: a linha
    `3.06.02` da CVM junta variação cambial e monetária de todo o passivo. Medido
    na WEG de 2024, ela dá 48% da dívida contra 4,5% de juro efetivamente pago.
    """
    analise = estado.analise()
    if analise is None:
        return

    partes = []
    for indicador, rotulo in (
        ("Custo da divida pelo caixa", "juro pago"),
        ("Custo da divida efetivo", "competência"),
    ):
        if indicador not in analise.indicadores.index:
            continue
        valor = float(analise.mediana(indicador))
        if np.isfinite(valor):
            partes.append(f"**{formatar(valor, 'pct')}** {rotulo}")

    if not partes:
        return
    st.caption(
        "Na empresa: "
        + " · ".join(partes)
        + ". O WACC usa o **juro pago**; a competência costuma superestimar."
    )


def _baliza_da_inflacao(ipca: float) -> None:
    """O IPCA digitado, contra o que o Focus projeta.

    O confronto já existe em **Premissas**, com um clique. Aqui vale a nota de
    que os dois números são a mesma premissa: a inflação local entra no WACC e,
    quando o `g` está ancorado, entra também no fluxo.
    """
    st.caption(
        "Entra no WACC **e**, se o `g` estiver ancorado, no crescimento. "
        "Em **Premissas** há a comparação com o Focus."
    )

def _baliza_do_divida_pl(alvo: float) -> None:
    """A estrutura de hoje e o corte da base, ao lado do alvo digitado."""
    from valuation.diagnostico import DIVIDA_PL_ALTA

    partes = []
    analise = estado.analise()
    if analise is not None:
        try:
            hoje = float(analise.mediana("Divida bruta / Patrimonio liquido"))
        except Exception:  # noqa: BLE001 - indicador ausente
            hoje = float("nan")
        if np.isfinite(hoje):
            anos = analise.anos
            partes.append(
                f"a empresa tem **{formatar(hoje, 'numero')}** ({anos[0]}–{anos[-1]})"
            )

    # O percentil diz onde o alvo cai; o corte diz o que ele significa. Faltando
    # um dos dois, o leitor ou estranha o normal do mercado ou aceita o quartil
    # alto por ele existir -- a mesma razao pela qual o sinal de conversao cita
    # os dois.
    from valuation import referencias

    # O sujeito do percentil precisa estar escrito: "no percentil 27" logo
    # depois de "a empresa tem 0,19" se le como se o 0,19 fosse o percentilado,
    # e o percentil e do **alvo** digitado.
    onde = referencias.descrever("Divida bruta / Patrimonio liquido", alvo)
    if onde:
        partes.append(
            f"o alvo de {formatar(alvo, 'numero')} fica "
            + onde.replace("companhias brasileiras", "da base")
        )
    if alvo >= DIVIDA_PL_ALTA:
        partes.append(
            f"**alavancado**: acima de {formatar(DIVIDA_PL_ALTA, 'numero')}, o "
            "corte que o diagnóstico usa"
        )

    st.caption(" · ".join(partes))

def _montagem(empresa, premissas) -> None:
    st.subheader("Risco do negócio")
    conceito("beta", "Beta: risco do setor, alavancagem da empresa")

    colunas = st.columns([2, 1, 1])
    nomes = ["(informar beta manualmente)"] + [s.nome for s in SETORES]
    escolha = colunas[0].selectbox(
        "Setor",
        nomes,
        index=nomes.index(estado.config().get("setor"))
        if estado.config().get("setor") in nomes
        else 0,
        help="Traz o beta desalavancado típico do setor.",
    )

    if escolha != "(informar beta manualmente)":
        setor = buscar_setor(escolha)
        beta_desalavancado = colunas[1].number_input(
            "Beta desalavancado", value=float(setor.beta_desalavancado), step=0.05
        )
        colunas[2].caption(setor.observacao or "—")
    else:
        beta_desalavancado = colunas[1].number_input(
            "Beta desalavancado",
            value=float(
                premissas.beta_desalavancado
                if premissas.beta_desalavancado is not None
                else 1.0
            ),
            step=0.05,
        )

    secao("Por onde montar o Ke")
    rotulos = list(METODOS_DE_CUSTO_DE_CAPITAL.values())
    escolhido = st.radio(
        "Caminho",
        rotulos,
        index=rotulos.index(METODOS_DE_CUSTO_DE_CAPITAL[premissas.metodo]),
        horizontal=True,
        help=(
            "**Dólar + risco-país**: taxa americana, prêmio maduro e risco-país, "
            "com o resultado convertido por diferencial de inflação. "
            "**NTN-B + prêmio local**: o soberano brasileiro já é o ponto de "
            "partida, e o prêmio de risco é o local."
        ),
    )
    metodo = next(
        k for k, v in METODOS_DE_CUSTO_DE_CAPITAL.items() if v == escolhido
    )
    local = metodo == "local"

    paises = list(PAISES_POR_NOME)
    dados_pais = PAISES_POR_NOME[estado.config().get("pais", "Brasil")]

    if local:
        pais, rf, erp, risco_pais, rf_brl, erp_local = _campos_locais(
            premissas, empresa, paises
        )
    else:
        pais, rf, erp, risco_pais = _campos_em_dolar(premissas, paises)
        rf_brl, erp_local = premissas.rf_brl, premissas.erp_local

    colunas = st.columns(4)
    # O lambda escala o **termo de risco-país**, e no caminho local não há termo
    # nenhum para escalar: ele já está dentro da NTN-B. Deixá-lo à vista ali
    # seria oferecer um controle que não move nada.
    if local:
        lambda_pais = premissas.lambda_pais
        colunas[0].caption(
            "A **exposição ao risco-país** (lambda) não aparece aqui: ela escala "
            "um termo que este caminho não tem."
        )
    else:
        lambda_pais = colunas[0].number_input(
            "Lambda (exposição ao risco-país)",
            value=float(premissas.lambda_pais),
            step=0.1,
            help=(
                "1,0 para empresa 100% exposta ao país. Exportadoras com receita em "
                "moeda forte usam valores menores."
            ),
        )
    premio_tamanho = colunas[1].number_input(
        "Prêmio de tamanho (%)",
        value=float(premissas.premio_tamanho * 100),
        step=0.1,
        format="%.2f",
    )
    inflacao_brl = colunas[2].number_input(
        "Inflação local de longo prazo (%)",
        value=float(empresa.macro.inflacao_brl * 100),
        step=0.1,
        format="%.2f",
    )
    inflacao_usd = colunas[3].number_input(
        "Inflação em USD de longo prazo (%)",
        value=float(empresa.macro.inflacao_usd * 100),
        step=0.1,
        format="%.2f",
    )
    with colunas[2]:
        _baliza_da_inflacao(inflacao_brl / 100)

    if empresa.perpetuidade.ancora != "livre":
        rotulo = "IPCA" if empresa.perpetuidade.ancora == "ipca" else "PIB nominal"
        st.caption(
            f"O crescimento perpétuo está ancorado em **{rotulo}** — a inflação local "
            "daqui move o **g** junto com o WACC. É a mesma premissa entrando dos dois "
            "lados do desconto."
        )

    st.subheader("Estrutura de capital e dívida")
    colunas = st.columns(4)
    divida_pl = colunas[0].number_input(
        "Dívida / Patrimônio alvo",
        value=float(premissas.divida_pl_alvo),
        step=0.05,
        min_value=0.0,
        help=(
            "Estrutura-alvo, não a de hoje: o WACC deve refletir como a empresa vai "
            "se financiar ao longo da projeção."
        ),
    )
    with colunas[0]:
        # "Alvo" nao quer dizer "inventado": a estrutura de hoje e o ponto de
        # partida obvio, e ela estava a duas telas de distancia. O corte de
        # `DIVIDA_PL_ALTA` entra junto porque e o quartil superior medido -- diz
        # se o alvo escolhido e alavancado para o padrao brasileiro.
        _baliza_do_divida_pl(divida_pl)
    informar_kd = colunas[1].checkbox(
        "Informar Kd diretamente", value=premissas.custo_divida_brl is not None
    )
    kd = colunas[2].number_input(
        "Custo da dívida bruto (%)",
        value=float((premissas.custo_divida_brl or 0.13) * 100),
        step=0.25,
        format="%.2f",
        disabled=not informar_kd,
    )
    with colunas[2]:
        _baliza_do_kd(kd / 100)
    spread = colunas[3].number_input(
        "Spread de crédito (%)",
        value=float(premissas.spread_credito * 100),
        step=0.25,
        format="%.2f",
        disabled=informar_kd,
        help="Usado para montar o Kd sinteticamente quando ele não é informado.",
    )
    aliquota = st.number_input(
        "Alíquota de IR/CSLL (%)",
        value=float(empresa.macro.aliquota_ir * 100),
        step=1.0,
        format="%.2f",
    )

    if st.button("Aplicar custo de capital", type="primary"):
        estado.config()["setor"] = escolha
        estado.config()["pais"] = pais
        try:
            estado.atualizar(
                {
                    "custo_capital.beta_desalavancado": beta_desalavancado,
                    "custo_capital.beta_alavancado_setor": None,
                    "custo_capital.metodo": metodo,
                    "custo_capital.rf_brl": rf_brl,
                    "custo_capital.erp_local": erp_local,
                    "custo_capital.divida_pl_alvo": divida_pl,
                    "custo_capital.rf_usd": rf / 100,
                    "custo_capital.erp_maduro": erp / 100,
                    "custo_capital.risco_pais": risco_pais / 100,
                    "custo_capital.lambda_pais": lambda_pais,
                    "custo_capital.premio_tamanho": premio_tamanho / 100,
                    "custo_capital.custo_divida_brl": (kd / 100) if informar_kd else None,
                    "custo_capital.spread_credito": spread / 100,
                    "macro.inflacao_brl": inflacao_brl / 100,
                    "macro.inflacao_usd": inflacao_usd / 100,
                    "macro.aliquota_ir": aliquota / 100,
                }
            )
        except ValueError as erro:
            st.error(str(erro))
        else:
            st.rerun()

    st.divider()
    resultado = estado.resultado()
    if resultado is None:
        st.error(estado.erro_do_modelo() or "As premissas atuais não fecham.")
        return

    cc = resultado.custo_capital
    colunas = st.columns(4)
    with colunas[0]:
        metrica("WACC (moeda local)", cc.wacc_brl, "pct2")
    with colunas[1]:
        metrica("Ke — capital próprio", cc.ke_brl, "pct2")
    with colunas[2]:
        metrica("Kd após IR", cc.kd_liquido_brl, "pct2")
    with colunas[3]:
        metrica("Beta realavancado", cc.beta_realavancado, "numero")


def _decomposicao() -> None:
    conceito("capm", "Por que montamos em dólar e convertemos depois")

    resultado = estado.resultado()
    if resultado is None:
        st.info("Ajuste as premissas na aba de montagem primeiro.")
        return

    cc = resultado.custo_capital
    premissas = estado.empresa().custo_capital
    macro = estado.empresa().macro

    st.markdown("#### Do risco do setor até a taxa de desconto")
    passos = [
        (
            "1. Beta desalavancado do setor",
            formatar(cc.beta_desalavancado, "numero"),
            "Mede o risco do negócio, sem o efeito de dívida.",
        ),
        (
            "2. Beta realavancado",
            formatar(cc.beta_realavancado, "numero"),
            f"βu × (1 + (1 − IR) × D/E), com D/E alvo de "
            f"{formatar(premissas.divida_pl_alvo, 'numero')}.",
        ),
        (
            "3. Ke em USD nominal",
            formatar(cc.ke_usd, "pct2"),
            f"{formatar(premissas.rf_usd, 'pct2')} (livre de risco) + β × "
            f"{formatar(premissas.erp_maduro, 'pct2')} (prêmio de mercado) + "
            f"{formatar(premissas.lambda_pais * premissas.risco_pais, 'pct2')} (risco-país).",
        ),
        (
            "4. Ke em moeda local",
            formatar(cc.ke_brl, "pct2"),
            f"Convertido pelo diferencial de inflação "
            f"({formatar(macro.inflacao_brl, 'pct')} local x "
            f"{formatar(macro.inflacao_usd, 'pct')} em USD).",
        ),
        (
            "5. Kd após imposto",
            formatar(cc.kd_liquido_brl, "pct2"),
            f"{formatar(cc.kd_bruto_brl, 'pct2')} × (1 − "
            f"{formatar(macro.aliquota_ir, 'pct')}). Juros são dedutíveis, então o "
            "governo banca parte do custo da dívida.",
        ),
        (
            "6. WACC",
            formatar(cc.wacc_brl, "pct2"),
            f"{formatar(cc.peso_equity, 'pct')} × Ke + "
            f"{formatar(cc.peso_divida, 'pct')} × Kd após IR.",
        ),
    ]

    for titulo, valor, explicacao in passos:
        with st.container(border=True):
            colunas = st.columns([3, 1, 6])
            colunas[0].markdown(f"**{titulo}**")
            colunas[1].markdown(f"**{valor}**")
            colunas[2].caption(explicacao)


def _referencias() -> None:
    st.warning(AVISO_REFERENCIA)
    st.markdown(
        "Para trabalho que vai para cliente ou comitê, baixe as planilhas oficiais em "
        "`pages.stern.nyu.edu/~adamodar/New_Home_Page/data.html` — os valores abaixo "
        "servem para orientar a ordem de grandeza, não para citar como fonte."
    )
    st.dataframe(
        listar_setores().style.format(
            {
                "Beta desalavancado": "{:.2f}",
                "D/E tipico": "{:.2f}",
                "Margem EBITDA tipica": "{:.1%}",
            },
            na_rep="—",
        ),
        width="stretch",
    )

    st.markdown("#### Parâmetros por país")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "País": p.nome,
                    "Risco-país": p.risco_pais,
                    "Inflação de longo prazo": p.inflacao_longo_prazo,
                    "Alíquota de IR": p.aliquota_ir,
                }
                for p in PAISES_POR_NOME.values()
            ]
        )
        .set_index("País")
        .style.format("{:.1%}"),
        width="stretch",
    )
