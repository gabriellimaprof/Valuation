"""Testes da curva real e do risco-pais implicito.

O fixture e um recorte em bytes do arquivo do Tesouro Direto, com o latin-1, o
';' e o decimal com virgula originais. O erro que este modulo existe para nao
cometer -- somar premio a taxa real como se fosse nominal -- e aritmetico, e
por isso a conta esta separada da rede e testada sozinha.
"""

from __future__ import annotations

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
