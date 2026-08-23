"""Testes da curva real e do risco-pais implicito.

O fixture e um recorte em bytes do arquivo do Tesouro Direto, com o latin-1, o
';' e o decimal com virgula originais. O erro que este modulo existe para nao
cometer -- somar premio a taxa real como se fosse nominal -- e aritmetico, e
por isso a conta esta separada da rede e testada sozinha.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from valuation.mercado import (
    ErroMercado,
    curva_ntnb,
    risco_pais_implicito,
    taxa_real_longa,
)

CURVA = Path(__file__).parent / "dados" / "mercado" / "tesouro_ipca.csv"


# ---------------------------------------------------------------------------
# A conta
# ---------------------------------------------------------------------------


def test_a_ntnb_e_nominalizada_antes_de_comparar():
    """Somar premio a 8% real seria subestimar a taxa em toda a inflacao."""
    r = risco_pais_implicito(taxa_real=0.08, ipca=0.035, rf_usd=0.045, inflacao_usd=0.023)

    # (1,08 x 1,035) - 1
    assert r.rf_brl_nominal == pytest.approx(0.1178, abs=1e-4)
    assert r.rf_brl_nominal > 0.08, "a taxa real nao pode ter passado direto"


def test_o_rf_americano_e_convertido_pelo_diferencial():
    r = risco_pais_implicito(taxa_real=0.08, ipca=0.035, rf_usd=0.045, inflacao_usd=0.023)
    esperado = 1.045 * 1.035 / 1.023 - 1
    assert r.rf_usd_em_brl == pytest.approx(esperado)


def test_a_diferenca_e_o_que_o_mercado_cobra_a_mais():
    r = risco_pais_implicito(taxa_real=0.08, ipca=0.035, rf_usd=0.045, inflacao_usd=0.023)
    assert r.diferenca == pytest.approx(r.rf_brl_nominal - r.rf_usd_em_brl)
    # Com estes numeros, bem acima dos 2,5% embarcados como padrao.
    assert r.diferenca > 0.04


def test_inflacao_maior_nao_cria_risco_pais():
    """Inflacao entra dos dois lados: sozinha, nao pode mover a diferenca.

    Se movesse, o indicador estaria medindo expectativa de inflacao e chamando
    isso de risco soberano.
    """
    baixa = risco_pais_implicito(0.08, 0.03, 0.045, 0.023).diferenca
    alta = risco_pais_implicito(0.08, 0.09, 0.045, 0.023).diferenca
    # A diferenca escala com o nivel de precos, mas em proporcao pequena.
    assert alta > baixa
    assert (alta - baixa) < 0.01, "inflacao nao pode dominar a medida"


def test_taxa_real_igual_ao_rf_convertido_zera_a_diferenca():
    """Sancao da aritmetica: sem premio, a diferenca tem que ser zero."""
    ipca, rf_usd, inflacao_usd = 0.035, 0.045, 0.023
    equivalente = (1 + rf_usd) / (1 + inflacao_usd) - 1
    r = risco_pais_implicito(equivalente, ipca, rf_usd, inflacao_usd)
    assert r.diferenca == pytest.approx(0.0, abs=1e-12)


def test_taxa_invalida_e_recusada():
    with pytest.raises(ValueError, match="numero"):
        risco_pais_implicito(float("nan"), 0.035, 0.045, 0.023)


def test_a_explicacao_mostra_as_parcelas():
    r = risco_pais_implicito(0.08, 0.035, 0.045, 0.023, vencimento="15/05/2035")
    assert "15/05/2035" in r.explicacao
    assert "8,00%".replace(",", ".") in r.explicacao or "8.00%" in r.explicacao
    assert "liquidez" in r.ressalva, "a ressalva tem que viajar junto do numero"


# ---------------------------------------------------------------------------
# A curva, contra o arquivo real
# ---------------------------------------------------------------------------


def test_le_a_curva_do_arquivo_do_tesouro():
    curva = curva_ntnb(CURVA)
    assert not curva.empty
    assert set(curva.columns) == {"vencimento", "data_base", "taxa_real"}
    # Uma coleta so: o arquivo tem historico, e a curva e de uma data.
    assert curva["data_base"].nunique() == 1
    # Taxas reais plausiveis, e ja em decimal.
    assert curva["taxa_real"].between(0.0, 0.20).all()


def test_a_curva_vem_ordenada_por_vencimento():
    curva = curva_ntnb(CURVA)
    assert list(curva["vencimento"]) == sorted(curva["vencimento"])


def test_taxa_longa_pega_o_vencimento_mais_proximo():
    curva = curva_ntnb(CURVA)
    dez_anos = taxa_real_longa(curva, anos=10)
    # O fixture tem 2035, que e o vencimento perto de dez anos de 2026.
    assert dez_anos == pytest.approx(0.0793, abs=1e-4)

    longa = taxa_real_longa(curva, anos=25)
    assert longa < dez_anos, "a curva real brasileira e invertida no longo"


def test_arquivo_sem_ntnb_e_erro_claro(tmp_path):
    vazio = tmp_path / "vazio.csv"
    vazio.write_bytes(b"Tipo Titulo;Data Vencimento\r\nTesouro Selic;01/03/2027\r\n")
    with pytest.raises(ErroMercado, match="NTN-B"):
        curva_ntnb(vazio)


def test_medida_com_a_curva_real():
    """Ponta a ponta sem rede: curva do arquivo, IPCA informado."""
    from valuation.mercado import medir_risco_pais

    r = medir_risco_pais(
        rf_usd=0.045, inflacao_usd=0.023, caminho_curva=CURVA, ipca=0.035
    )
    assert r.vencimento
    assert r.diferenca > 0.03, "o Brasil paga premio sobre o Tesouro americano"
    assert r.diferenca < 0.10, "e nao um premio absurdo"


# ---------------------------------------------------------------------------
# Focus: as duas bases de calculo, e o bloco macro inteiro
# ---------------------------------------------------------------------------

import json  # noqa: E402

FOCUS = Path(__file__).parent / "dados" / "mercado" / "focus.json"


@pytest.fixture
def focus_offline(monkeypatch):
    """Serve o recorte real do Olinda no lugar da rede.

    O fixture guarda **as duas** bases de cálculo de propósito: é a duplicata
    que o teste precisa ver para provar que o filtro funciona.
    """
    from valuation import mercado

    recorte = json.loads(FOCUS.read_text(encoding="utf-8"))

    def falso(url: str, cabecalhos=None) -> bytes:
        for indicador, dados in recorte.items():
            if urllib.parse.quote(f"Indicador eq '{indicador}'") in url:
                return json.dumps(dados).encode("utf-8")
        raise AssertionError(f"pedido inesperado: {url}")

    monkeypatch.setattr(mercado, "_buscar", falso)
    return recorte


def test_o_focus_publica_o_mesmo_ano_duas_vezes(focus_offline):
    """``baseCalculo`` 0 são os últimos 30 dias; 1, os últimos 5 dias úteis.

    Sem filtrar, cada ano volta duplicado e o código pegava um dos dois por
    ordem de linha. Medido na coleta de 14/08/2026: IPCA de 2027 com mediana
    4,2402 na base 0 (148 casas) e 4,2060 na base 1 (69 casas).
    """
    linhas = focus_offline["IPCA"]["value"]
    bases = {linha["baseCalculo"] for linha in linhas}
    assert bases == {0, 1}, "o fixture deixou de ter as duas bases"

    anos = [linha["DataReferencia"] for linha in linhas]
    assert len(anos) != len(set(anos)), "o fixture deixou de ter ano repetido"


def test_expectativas_devolve_um_ano_uma_vez(focus_offline):
    from valuation.mercado import expectativas

    tabela = expectativas("IPCA")
    assert list(tabela.index) == sorted(set(tabela.index))
    assert tabela.index.is_unique


def test_a_base_padrao_e_a_de_30_dias_por_ter_mais_casas(focus_offline):
    """A base 0 é a do relatório publicado e tem mais que o dobro de respondentes."""
    from valuation.mercado import BASE_5_DIAS, expectativas

    trinta = expectativas("IPCA")
    cinco = expectativas("IPCA", base=BASE_5_DIAS)
    assert int(trinta["numeroRespondentes"].iloc[0]) > int(
        cinco["numeroRespondentes"].iloc[0]
    )


def test_a_data_da_coleta_acompanha_o_numero(focus_offline):
    """Projeção sem data é projeção sem validade."""
    from valuation.mercado import expectativas

    assert expectativas("IPCA").attrs["coleta"] == "2026-08-14"


def test_o_bloco_macro_sai_em_decimal_menos_o_cambio(focus_offline):
    """Câmbio é preço em reais por dólar, e não taxa: não se divide por 100."""
    from valuation.mercado import macro_do_focus

    macro = macro_do_focus(anos_a_frente=3)
    assert 0.0 < macro.ipca < 0.20
    assert 0.0 < macro.pib_real < 0.20
    assert 0.0 < macro.selic < 0.50
    assert 3.0 < macro.cambio < 10.0
    assert macro.coleta == "2026-08-14"
    assert all(n > 0 for n in macro.respondentes.values())


def test_o_bloco_macro_usa_o_ano_mais_distante_da_janela(focus_offline):
    """A projeção curta carrega o choque corrente; perpetuidade quer regime.

    Medido na coleta de 14/08/2026: IPCA de 5,02% para 2026 contra 3,50% para
    2029. Pegar o ano errado projeta um ciclo como se fosse regime.
    """
    from valuation.mercado import expectativas, macro_do_focus

    macro = macro_do_focus(anos_a_frente=3)
    tabela = expectativas("IPCA")
    proximo = float(tabela["Mediana"].iloc[0]) / 100
    assert macro.ipca == pytest.approx(float(tabela.loc[macro.ano_de_referencia, "Mediana"]) / 100)
    assert macro.ipca < proximo


def test_a_comparacao_poe_modelo_e_focus_lado_a_lado(focus_offline):
    """A pergunta que o analista faz ao abrir a tela, respondida de uma vez."""
    from valuation.mercado import macro_do_focus
    from valuation.premissas import PremissasMacro

    tabela = macro_do_focus().comparar(PremissasMacro(inflacao_brl=0.05, pib_real=0.015))
    assert list(tabela.index) == ["IPCA", "PIB real"]
    assert tabela.loc["IPCA", "No modelo"] == pytest.approx(0.05)
    assert tabela.loc["IPCA", "Diferença"] == pytest.approx(
        0.05 - tabela.loc["IPCA", "Focus"]
    )


# ---------------------------------------------------------------------------
# Cotacao da B3
# ---------------------------------------------------------------------------

COTACAO_WEGE3 = Path(__file__).parent / "dados" / "cotacao_wege3.json"


def test_interpreta_a_cotacao_do_recorte_real():
    """Contra a resposta real do endpoint, gravada -- e nao contra um mock.

    O teste **nao alcanca a rede**: a suite ja passou de 100s para 237s uma vez
    por causa de um teste que dependia do Banco Central, e falhou quando ele
    demorou. Teste que depende de terceiro nao esta testando o app.
    """
    from valuation.mercado import interpretar_cotacao

    c = interpretar_cotacao(COTACAO_WEGE3.read_bytes(), "WEGE3.SA")
    assert c.moeda == "BRL"
    assert 1 < c.preco < 1000, c.preco
    assert "WEG" in c.nome.upper()


def test_o_valor_de_mercado_fecha_com_o_da_bolsa():
    """A ponta que faltava: acoes da CVM x preco da B3.

    O app lia 4.195.695.973 acoes da composicao de capital e nunca tinha como
    conferir isso contra o mercado -- e um usuario leu R$ 59,8 bi (que era o DCF
    do proprio app) achando que era o valor de mercado da WEG, que vale ~R$ 207
    bi. Com as duas pontas juntas, a conferencia e uma multiplicacao.
    """
    from valuation.mercado import interpretar_cotacao

    c = interpretar_cotacao(COTACAO_WEGE3.read_bytes(), "WEGE3.SA")
    acoes = 4_195_695_973
    em_bilhoes = c.valor_de_mercado(acoes) / 1e9
    assert 150 < em_bilhoes < 300, f"R$ {em_bilhoes:,.1f} bi"


def test_ticker_ganha_o_sufixo_da_b3():
    """Sem `.SA` o Yahoo acha outro papel, ou nada -- e "nada" e o melhor caso."""
    from valuation.mercado import _normalizar_ticker

    assert _normalizar_ticker("wege3") == "WEGE3.SA"
    assert _normalizar_ticker(" PETR4 ") == "PETR4.SA"
    assert _normalizar_ticker("AAPL.US") == "AAPL.US"


def test_ticker_vazio_e_resposta_estranha_viram_erro_tratado():
    """Falha de cotacao e recusa normal: o campo manual continua sendo o caminho."""
    from valuation.mercado import ErroMercado, _normalizar_ticker, interpretar_cotacao

    with pytest.raises(ErroMercado):
        _normalizar_ticker("   ")
    with pytest.raises(ErroMercado):
        interpretar_cotacao(b"{}", "X.SA")
    with pytest.raises(ErroMercado):
        interpretar_cotacao(b"nao e json", "X.SA")
