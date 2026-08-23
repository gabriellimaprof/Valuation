"""As telas que ganharam a macro de longo prazo, sem navegador.

Duas coisas so podem ser verificadas com a tela rodando: que a ancora escolhida
em Premissas chega ao modelo, e que o estresse macro em Sensibilidade nao
quebra nem sai mudo. O resto -- a aritmetica da ancora -- esta em test_macro.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

CABECALHO = f"""
import sys
for caminho in ({str(RAIZ)!r}, {str(RAIZ / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from valuation import substituir_varios

estado.iniciar()
if st.session_state.get("alteracoes"):
    estado.definir_empresa(
        substituir_varios(estado.empresa(), st.session_state["alteracoes"])
    )
"""

TELA_PREMISSAS = CABECALHO + """
from app.paginas import premissas
premissas.render()
"""

TELA_SENSIBILIDADE = CABECALHO + """
from app.paginas import sensibilidade
sensibilidade.render()
"""


def _rodar(script: str, alteracoes: dict | None = None) -> AppTest:
    teste = AppTest.from_string(script, default_timeout=120)
    if alteracoes:
        teste.session_state["alteracoes"] = alteracoes
    teste.run()
    assert not teste.exception, teste.exception
    return teste


# ---------------------------------------------------------------------------
# Premissas
# ---------------------------------------------------------------------------


def test_a_tela_de_premissas_abre_com_a_ancora_livre():
    teste = _rodar(TELA_PREMISSAS)
    ancora = next(s for s in teste.selectbox if s.label == "De onde vem o g")
    assert ancora.value.startswith("Livre"), "ninguem pode ganhar uma ancora sem pedir"
    assert teste.session_state["empresa"].perpetuidade.ancora == "livre"


def test_escolher_a_ancora_grava_no_modelo():
    teste = _rodar(TELA_PREMISSAS)
    ancora = next(s for s in teste.selectbox if s.label == "De onde vem o g")
    ancora.select("PIB nominal").run()

    botao = next(b for b in teste.button if b.label == "Aplicar perpetuidade")
    botao.click().run()
    assert not teste.exception, teste.exception

    empresa = teste.session_state["empresa"]
    assert empresa.perpetuidade.ancora == "pib_nominal"
    assert empresa.perpetuidade.crescimento_perpetuo == pytest.approx(
        empresa.macro.pib_nominal
    )


def test_o_campo_do_g_fica_travado_quando_ancorado():
    """Ancorado, o g e derivado: deixar o campo editavel seria mentir na tela."""
    teste = _rodar(TELA_PREMISSAS, {"perpetuidade.ancora": "ipca"})
    campo = next(
        n for n in teste.number_input if n.label == "Crescimento perpétuo (%)"
    )
    assert campo.disabled
    assert campo.value == pytest.approx(teste.session_state["empresa"].macro.inflacao_brl * 100)


def test_o_pib_real_e_editavel_na_tela_de_premissas():
    teste = _rodar(TELA_PREMISSAS)
    campo = next(
        n for n in teste.number_input if n.label == "PIB real de longo prazo (%)"
    )
    campo.set_value(0.5).run()
    next(b for b in teste.button if b.label == "Aplicar perpetuidade").click().run()

    assert teste.session_state["empresa"].macro.pib_real == pytest.approx(0.005)


# ---------------------------------------------------------------------------
# Sensibilidade
# ---------------------------------------------------------------------------


def test_o_estresse_macro_roda_e_diz_alguma_coisa():
    teste = _rodar(TELA_SENSIBILIDADE)
    assert any("Estresse macro" in m.value for m in teste.markdown)
    assert any("risco-país move" in c.value for c in teste.caption), (
        "a leitura do estresse sumiu"
    )

    tabela = teste.session_state["tabela_cenarios_macro"]
    assert "Base" in tabela.columns
    assert tabela.shape[1] == 4


def test_o_estresse_macro_mede_cada_choque_separado():
    """Os tres cenarios tem que dar tres numeros distintos do base."""
    teste = _rodar(TELA_SENSIBILIDADE, {"perpetuidade.ancora": "pib_nominal"})
    tabela = teste.session_state["tabela_cenarios_macro"]

    por_nome = {c: float(tabela.loc["equity_value", c]) for c in tabela.columns}
    base = por_nome["Base"]
    ipca = next(v for c, v in por_nome.items() if c.startswith("IPCA"))
    # O nome do cenario acompanha o premio que move o Ke -- "Risco-pais" no
    # caminho em dolar, "Premio local" no padrao. O teste procura **o cenario
    # que nao e IPCA nem PIB**, que e o que ele quer medir.
    risco = next(
        v
        for c, v in por_nome.items()
        if c not in ("Base",) and not c.startswith(("IPCA", "PIB"))
    )
    pib = next(v for c, v in por_nome.items() if c.startswith("PIB"))

    assert ipca < base and risco < base
    assert pib < base, "ancorado em PIB nominal, o PIB fraco tem que doer"
    assert ipca != risco


def test_os_eixos_macro_existem_e_avisam_quando_nao_movem_nada():
    teste = _rodar(TELA_SENSIBILIDADE)
    eixos = [s for s in teste.selectbox if s.label in ("Nas linhas", "Nas colunas")]
    assert "PIB real de longo prazo" in eixos[0].options

    eixos[0].select("PIB real de longo prazo").run()
    assert not teste.exception, teste.exception
    avisos = [i.value for i in teste.info]
    assert any("não altera o valuation" in a for a in avisos), (
        "sem âncora em PIB nominal, o eixo sai achatado e a tela precisa dizer"
    )


# ---------------------------------------------------------------------------
# Risco-pais medido pela curva
# ---------------------------------------------------------------------------

TELA_CUSTO = CABECALHO + """
from app.paginas import custo_capital
custo_capital.render()
"""


def test_a_aba_de_risco_pais_existe_e_nao_toca_a_rede_sozinha():
    """Buscar dado externo sem o usuario pedir e o tipo de surpresa que nao cabe.

    Se a tela buscasse ao abrir, cada rerun do Streamlit -- e sao muitos --
    baixaria a curva do Tesouro de novo.
    """
    teste = _rodar(TELA_CUSTO)
    rotulos = [aba.label for aba in teste.tabs if aba.label]
    assert "Risco-país pela curva" in rotulos

    assert any(b.label == "Medir agora" for b in teste.button)
    assert any("Nada é buscado sem você pedir" in c.value for c in teste.caption)


def test_a_tela_avisa_que_a_medida_e_piso():
    """A NTN-B e indexada: nominalizar so pela inflacao esperada subestima."""
    teste = _rodar(TELA_CUSTO)
    avisos = " ".join(i.value for i in teste.info)
    assert "piso, não um ponto" in avisos


def test_a_ancora_do_g_aparece_onde_o_ipca_e_editado():
    """Quem mexe na inflacao aqui precisa saber que esta mexendo no g tambem."""
    limpo = _rodar(TELA_CUSTO)
    assert not any("ancorado em" in c.value for c in limpo.caption)

    ancorado = _rodar(TELA_CUSTO, {"perpetuidade.ancora": "ipca"})
    assert any("ancorado em **IPCA**" in c.value for c in ancorado.caption)


# ---------------------------------------------------------------------------
# A comparacao com o Focus
# ---------------------------------------------------------------------------


def test_o_focus_nasce_desligado():
    """Não busca nada sem o usuário pedir — mesma regra do risco-país da NTN-B.

    Uma tela que sai buscando na rede ao abrir custa segundos toda vez e põe um
    serviço de terceiro no caminho crítico de quem só queria ver a projeção.
    """
    teste = _rodar(TELA_PREMISSAS)
    alavancas = [t.label for t in teste.toggle]
    assert "Comparar com o Focus" in alavancas
    alavanca = next(t for t in teste.toggle if t.label == "Comparar com o Focus")
    assert alavanca.value is False


@pytest.fixture
def focus_offline(monkeypatch):
    """Serve o recorte real do Olinda no lugar da rede.

    Sem isto o teste alcanca o Banco Central de verdade: passa ou falha conforme
    o servico responde, e a suite inteira passou de 100s para 237s numa execucao
    em que ele demorou. Teste que depende de terceiro nao esta testando o app.
    """
    import json
    import urllib.parse

    from valuation import mercado

    recorte = json.loads(
        (Path(__file__).parent / "dados" / "mercado" / "focus.json").read_text(
            encoding="utf-8"
        )
    )

    def falso(url: str, cabecalhos=None) -> bytes:
        for indicador, dados in recorte.items():
            if urllib.parse.quote(f"Indicador eq '{indicador}'") in url:
                return json.dumps(dados).encode("utf-8")
        raise AssertionError(f"pedido inesperado: {url}")

    monkeypatch.setattr(mercado, "_buscar", falso)


def test_ligar_a_comparacao_nao_altera_premissa_nenhuma(focus_offline):
    """O padrão do app é a prática de quem o construiu; o consenso é referência.

    Aplicar tem que ser um segundo clique, explícito: IPCA de 5% contra os 3,5%
    do Focus é escolha, e não esquecimento.
    """
    teste = _rodar(TELA_PREMISSAS)
    antes = teste.session_state["empresa"].macro.inflacao_brl

    alavanca = next(t for t in teste.toggle if t.label == "Comparar com o Focus")
    alavanca.set_value(True).run()
    assert not teste.exception, [str(e.value) for e in teste.exception]

    # Os números aparecem — e mesmo assim a premissa não mudou sozinha.
    assert teste.session_state["empresa"].macro.inflacao_brl == antes
    rotulos = {m.label for m in teste.metric}
    assert "Selic (Focus)" in rotulos, rotulos


# ---------------------------------------------------------------------------
# A base do multiplo de saida: EV/EBITDA ou P/L
# ---------------------------------------------------------------------------


def _escolher_multiplo(teste):
    """Troca o metodo para "Multiplo de saida" e devolve a tela redesenhada.

    Os campos do multiplo **so existem quando ele e o metodo escolhido**: a tela
    desenhava os dois caminhos ao mesmo tempo, com o nao escolhido em cinza, e
    campo desabilitado nao ajuda quem nao vai usa-lo.
    """
    metodo = next(r for r in teste.radio if r.label == "Método")
    metodo.set_value("Múltiplo de saída").run()
    assert not teste.exception, teste.exception
    return teste


def test_a_tela_oferece_as_duas_bases_do_multiplo():
    """Depende do caso: uma industria sai por EV/EBITDA, outra sai por P/L."""
    teste = _escolher_multiplo(_rodar(TELA_PREMISSAS))
    escolha = next(r for r in teste.radio if r.label == "Múltiplo sobre")
    assert escolha.options == ["EV/EBITDA", "P/L"]
    assert escolha.value == "EV/EBITDA", "o padrao continua sendo o de firma"


def test_so_os_campos_do_metodo_escolhido_aparecem():
    """Oito controles a vista para quatro decisoes, metade deles inertes.

    Era a maior parte do "e muita opcao" da queixa: a tela desenhava Gordon e
    multiplo ao mesmo tempo, com o nao escolhido em cinza.
    """
    teste = _rodar(TELA_PREMISSAS)
    rotulos = {r.label for r in teste.radio}
    assert "Múltiplo sobre" not in rotulos, "campo do multiplo apareceu no Gordon"
    assert any(s.label == "De onde vem o g" for s in teste.selectbox)

    teste = _escolher_multiplo(teste)
    assert "Múltiplo sobre" in {r.label for r in teste.radio}
    assert not any(s.label == "De onde vem o g" for s in teste.selectbox), (
        "campo do Gordon sobreviveu ao multiplo"
    )


def test_o_rotulo_do_campo_acompanha_a_base_escolhida():
    """"Multiplo de saida (EV/EBITDA)" com um P/L digitado dentro engana."""
    teste = _rodar(
        TELA_PREMISSAS,
        {
            "perpetuidade.metodo": "multiplo",
            "perpetuidade.multiplo_saida": 12.0,
            "perpetuidade.base_do_multiplo": "lucro",
        },
    )
    rotulos = [n.label for n in teste.number_input]
    assert "Múltiplo de saída (P/L)" in rotulos
    assert "Múltiplo de saída (EV/EBITDA)" not in rotulos


def test_a_base_escolhida_chega_ao_modelo():
    """A escolha muda a moeda do valor terminal — ela e premissa, nao rotulo."""
    teste = _escolher_multiplo(_rodar(TELA_PREMISSAS))
    next(r for r in teste.radio if r.label == "Múltiplo sobre").set_value("P/L").run()
    next(b for b in teste.button if b.label == "Aplicar perpetuidade").click().run()
    assert not teste.exception, teste.exception

    from app import estado  # noqa: F401  (o estado vive no processo do AppTest)

    perpetuidade = teste.session_state["empresa"].perpetuidade
    assert perpetuidade.metodo == "multiplo"
    assert perpetuidade.base_do_multiplo == "lucro"


# ---------------------------------------------------------------------------
# A normalizacao pede o retorno do capital que o fluxo remunera
# ---------------------------------------------------------------------------

TELA_PREMISSAS_FCFE = CABECALHO + """
st.session_state["config"]["tipo_fluxo"] = "fcfe"
from app.paginas import premissas
premissas.render()
"""


def test_no_fcff_o_campo_pede_roic():
    teste = _rodar(TELA_PREMISSAS)
    rotulos = [n.label for n in teste.number_input]
    assert any("ROIC perpétuo" in r for r in rotulos), rotulos
    assert not any("ROE perpétuo" in r for r in rotulos)


def test_no_fcfe_o_campo_pede_roe():
    """Rotular sempre "ROIC" fazia o campo pedir uma coisa e o modelo usar outra.

    Crescer para sempre exige reinvestir para sempre, e a taxa e `g / retorno` --
    mas o retorno tem de descrever o mesmo capital que o fluxo remunera: ROIC
    para o fluxo da firma, ROE para o do acionista.
    """
    teste = _rodar(TELA_PREMISSAS_FCFE)
    rotulos = [n.label for n in teste.number_input]
    assert any("ROE perpétuo" in r for r in rotulos), rotulos
    assert not any("ROIC perpétuo" in r for r in rotulos)


def test_no_fcfe_o_numero_digitado_vai_para_o_campo_do_roe():
    """Deixar os dois preenchidos faria o motor escolher entre capitais diferentes."""
    teste = _rodar(TELA_PREMISSAS_FCFE)
    campo = next(n for n in teste.number_input if "ROE perpétuo" in n.label)
    campo.set_value(22.0).run()
    next(b for b in teste.button if b.label == "Aplicar perpetuidade").click().run()
    assert not teste.exception, teste.exception

    perpetuidade = teste.session_state["empresa"].perpetuidade
    assert perpetuidade.roe_perpetuidade == pytest.approx(0.22)
    assert perpetuidade.roic_perpetuidade is None


# ---------------------------------------------------------------------------
# Os dois caminhos do Ke, na tela
# ---------------------------------------------------------------------------

TELA_CUSTO = CABECALHO + """
from app.paginas import custo_capital
custo_capital.render()
"""


def _rotulos_numericos(teste) -> set[str]:
    return {n.label for n in teste.number_input}


def test_o_caminho_em_dolar_pede_rf_americano_e_risco_pais():
    """Ele deixou de ser o padrao, e virou a alternativa -- entao e escolhido."""
    teste = _rodar(TELA_CUSTO)
    caminho = next(r for r in teste.radio if r.label == "Caminho")
    caminho.set_value("Dólar + risco-país").run()
    assert not teste.exception, teste.exception
    rotulos = _rotulos_numericos(teste)
    assert "Taxa livre de risco em USD (%)" in rotulos
    assert "Prêmio de risco-país (%)" in rotulos
    assert "NTN-B — taxa real (%)" not in rotulos


def test_a_tela_abre_no_caminho_local():
    """Pedido do dono do projeto: a NTN-B e o ponto de partida."""
    teste = _rodar(TELA_CUSTO)
    caminho = next(r for r in teste.radio if r.label == "Caminho")
    assert caminho.value == "NTN-B + prêmio local"
    assert "NTN-B — taxa real (%)" in _rotulos_numericos(teste)


def test_o_caminho_local_troca_os_campos_e_tira_o_risco_pais():
    """No local o risco-pais **nao aparece**, e a ausencia e a decisao.

    O soberano brasileiro ja embute risco de credito do pais; oferecer um campo
    de risco-pais ali convidaria a conta-lo duas vezes.
    """
    teste = _rodar(TELA_CUSTO)
    rotulos = _rotulos_numericos(teste)
    assert "NTN-B — taxa real (%)" in rotulos
    assert "Prêmio de risco de ações local (%)" in rotulos
    assert "Prêmio de risco-país (%)" not in rotulos
    assert "Taxa livre de risco em USD (%)" not in rotulos
    # O lambda escala um termo que este caminho nao tem.
    assert "Lambda (exposição ao risco-país)" not in rotulos


def test_o_caminho_escolhido_chega_ao_modelo():
    teste = _rodar(TELA_CUSTO)
    next(b for b in teste.button if "Aplicar" in b.label).click().run()
    assert not teste.exception, teste.exception

    cc = teste.session_state["empresa"].custo_capital
    assert cc.metodo == "local"
    assert cc.rf_brl is not None and cc.rf_brl > 0


def test_a_tela_diz_que_o_rf_e_referencia_e_nao_atualiza_sozinho():
    """Numero embarcado com cara de numero buscado engana quem confia nele."""
    teste = _rodar(TELA_CUSTO)
    legendas = " ".join(c.value for c in teste.caption)
    avisos = " ".join(w.value for w in teste.warning)
    assert "não" in (legendas + avisos)
    assert "referência" in (legendas + avisos)
    assert "atualiza sozinho" in legendas or "busque a atual" in avisos
