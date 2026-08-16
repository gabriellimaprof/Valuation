"""IFRS 16: as duas leituras do resultado, e o que a projecao faz com o aluguel.

Desde 2019 o aluguel saiu do resultado operacional e virou depreciacao de
direito de uso mais juros. O EBITDA subiu sem que nada tenha melhorado no
negocio, e para rede de farmacia, academia ou telecom isso muda a leitura
inteira -- medido: Smart Fit com margem EBITDA de 48% reportada e 21,8% sem o
aluguel.

Tres coisas precisam estar certas, e todas ja custaram dinheiro a alguem:

* **As duas visoes nao se misturam.** Divida com arrendamento sobre EBITDA sem
  aluguel infla a alavancagem; ao contrario, esconde.
* **Ausencia de dado nao vira zero.** Companhia que nao publica desembolso de
  arrendamento nao tem visao ex-IFRS 16 -- e diferente de ter uma igual a
  reportada.
* **Contrato novo de aluguel nao passa pelo capex.** Sem projetar a adicao, o
  FCFF de quem cresce abrindo pontos sai generoso demais.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from valuation import avaliar
from valuation.casos_especiais import ver_ex_ifrs16
from valuation.historico import analisar
from valuation.importacao import Demonstracoes
from valuation.premissas import PremissasMacro, PremissasOperacionais
from valuation.projecao import projetar

DADOS = Path(__file__).parent / "dados" / "cvm"


def _rede(aluguel_principal=100.0, aluguel_juros=60.0, arrendamento=900.0):
    """Uma rede de lojas: EBITDA alto por norma, aluguel pesado por baixo."""
    anos = {}
    for i, ano in enumerate((2023, 2024)):
        anos[ano] = {
            "receita_liquida": 1000.0 * (1.1**i),
            "ebit": 120.0 * (1.1**i),
            "depreciacao_amortizacao": 80.0 * (1.1**i),
            "divida_curto_prazo": 100.0,
            "divida_longo_prazo": 300.0,
            "caixa_equivalentes": 50.0,
            "arrendamento_curto_prazo": arrendamento * 0.2,
            "arrendamento_longo_prazo": arrendamento * 0.8,
            "arrendamento_principal_pago": aluguel_principal * (1.1**i),
            "arrendamento_juros_pagos": aluguel_juros * (1.1**i),
        }
    return analisar(Demonstracoes(empresa="Rede", valores=pd.DataFrame(anos)))


# ---------------------------------------------------------------------------
# A visao ex-IFRS 16
# ---------------------------------------------------------------------------


def test_o_aluguel_sai_do_ebitda_e_o_juro_sai_do_ebit():
    v = ver_ex_ifrs16(_rede())

    # EBITDA reportado = EBIT + D&A = 120 + 80 = 200; aluguel = 100 + 60 = 160.
    assert v.ebitda_reportado[2023] == pytest.approx(200.0)
    assert v.ebitda[2023] == pytest.approx(40.0)
    # EBIT ja desconta a depreciacao do direito de uso; sobra tirar o juro.
    assert v.ebit[2023] == pytest.approx(60.0)


def test_a_divida_ex_ifrs16_exclui_o_arrendamento():
    v = ver_ex_ifrs16(_rede())
    assert v.divida_bruta_reportada[2023] == pytest.approx(400.0)
    assert v.divida_bruta[2023] == pytest.approx(400.0 - 900.0)


def test_a_alavancagem_usa_os_dois_lados_coerentes():
    """O erro classico e cruzar: divida cheia sobre EBITDA sem aluguel."""
    v = ver_ex_ifrs16(_rede(arrendamento=300.0))

    reportada = v.alavancagem_reportada[2023]
    ex = v.alavancagem[2023]
    cruzada = (v.divida_bruta_reportada[2023] - v.caixa[2023]) / v.ebitda[2023]

    assert reportada == pytest.approx((400.0 - 50.0) / 200.0)
    assert ex == pytest.approx((400.0 - 300.0 - 50.0) / 40.0)
    # A cruzada e a que engana: divida de quem aluga sobre lucro de quem nao.
    assert cruzada > reportada * 3


def test_sem_desembolso_na_dfc_nao_ha_visao():
    """Ausencia de dado nao pode virar visao identica a reportada."""
    valores = pd.DataFrame(
        {2024: {"receita_liquida": 1000.0, "ebit": 120.0, "divida_curto_prazo": 100.0}}
    )
    assert ver_ex_ifrs16(analisar(Demonstracoes(empresa="X", valores=valores))) is None


def test_sem_juros_publicados_o_ajuste_e_declarado_como_piso():
    v = ver_ex_ifrs16(_rede(aluguel_juros=float("nan")))
    assert not v.tem_juros
    assert "piso" in v.ressalva


def test_o_peso_do_aluguel_decide_se_vale_olhar():
    pesada = ver_ex_ifrs16(_rede(aluguel_principal=100.0, aluguel_juros=60.0))
    leve = ver_ex_ifrs16(_rede(aluguel_principal=2.0, aluguel_juros=1.0))

    assert pesada.relevante and pesada.peso_do_aluguel == pytest.approx(0.80)
    assert not leve.relevante


def test_os_indicadores_ex_ifrs16_entram_no_historico():
    analise = _rede()
    for indicador in (
        "Aluguel (arrendamento pago) / Receita",
        "Aluguel / EBITDA",
        "Margem EBITDA (ex-IFRS 16)",
        "Margem EBIT (ex-IFRS 16)",
        "Divida liquida / EBITDA (ex-IFRS 16)",
    ):
        assert indicador in analise.indicadores.index, indicador

    assert analise.mediana("Margem EBITDA (ex-IFRS 16)") < analise.mediana("Margem EBITDA")


def test_farmacia_de_verdade_muda_de_leitura():
    """Raia Drogasil: a margem reportada e quase o dobro da ex-IFRS 16."""
    from valuation.importacao.cvm import importar_cvm

    cache = Path.home() / ".cache" / "valuation" / "cvm"
    if not (cache / "dfp_cia_aberta_2024.zip").exists():
        pytest.skip("cache da CVM sem o zip de 2024")

    analise = analisar(importar_cvm(5258, [2023, 2024], cache=cache).escalar(1e6, "R$ mi"))
    v = ver_ex_ifrs16(analise)

    assert v is not None and v.relevante
    reportada = float(v.margem_ebitda_reportada.dropna().iloc[-1])
    ex = float(v.margem_ebitda.dropna().iloc[-1])
    assert reportada > ex * 1.5, "o aluguel devia derrubar a margem pela metade"
    assert 0.09 < reportada < 0.13
    assert 0.04 < ex < 0.09


# ---------------------------------------------------------------------------
# A projecao
# ---------------------------------------------------------------------------


def _operacionais(**extras) -> PremissasOperacionais:
    return PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.15] * 5,
        margem_ebitda=[0.20] * 5,
        depreciacao_pct_receita=[0.05] * 5,
        capex_pct_receita=[0.05] * 5,
        capital_giro_pct_receita=[0.10] * 5,
        **extras,
    )


def test_adicao_de_arrendamento_reduz_o_fcff():
    """Contrato novo cria ativo e passivo sem tocar o capex."""
    sem = projetar(_operacionais(), PremissasMacro())
    com = projetar(_operacionais(arrendamento_pct_receita=[0.30] * 5), PremissasMacro())

    assert sem.variacao_arrendamento is None
    assert com.variacao_arrendamento is not None
    assert (com.variacao_arrendamento > 0).all(), "quem cresce assina mais contrato"
    assert (com.fcff < sem.fcff).all()
    assert com.fcff[0] == pytest.approx(sem.fcff[0] - com.variacao_arrendamento[0])


def test_a_linha_aparece_na_tabela_da_projecao():
    tabela = projetar(
        _operacionais(arrendamento_pct_receita=[0.30] * 5), PremissasMacro()
    ).tabela()
    assert "(-) Adicoes de arrendamento" in tabela.index

    sem = projetar(_operacionais(), PremissasMacro()).tabela()
    assert "(-) Adicoes de arrendamento" not in sem.index


def test_arrendamento_com_horizonte_diferente_e_recusado():
    with pytest.raises(ValueError, match="tamanhos diferentes"):
        _operacionais(arrendamento_pct_receita=[0.30] * 3)


def test_a_sugestao_so_propoe_arrendamento_para_quem_aluga():
    from valuation.historico import sugerir_premissas

    com_aluguel = sugerir_premissas(_rede(), horizonte=5)
    assert com_aluguel.operacionais.arrendamento_pct_receita is not None
    assert "arrendamento_pct_receita" in com_aluguel.justificativas

    valores = pd.DataFrame(
        {
            2023: {"receita_liquida": 1000.0, "ebit": 120.0, "depreciacao_amortizacao": 80.0},
            2024: {"receita_liquida": 1100.0, "ebit": 130.0, "depreciacao_amortizacao": 85.0},
        }
    )
    sem = sugerir_premissas(analisar(Demonstracoes(empresa="X", valores=valores)), horizonte=5)
    assert sem.operacionais.arrendamento_pct_receita is None


def test_projetar_arrendamento_derruba_o_valor_de_quem_cresce_alugando(empresa_exemplo):
    com = replace(
        empresa_exemplo, operacionais=_operacionais(arrendamento_pct_receita=[0.30] * 5)
    )
    sem = replace(empresa_exemplo, operacionais=_operacionais())

    assert avaliar(com).equity_value < avaliar(sem).equity_value


def test_o_arrendamento_projetado_sobrevive_ao_arquivo_salvo(empresa_exemplo):
    from valuation.projeto import Projeto, desserializar, serializar

    com = replace(
        empresa_exemplo, operacionais=_operacionais(arrendamento_pct_receita=[0.30] * 5)
    )
    voltou = desserializar(serializar(Projeto(empresa=com))).empresa
    assert voltou.operacionais.arrendamento_pct_receita == pytest.approx([0.30] * 5)


def test_o_relatorio_traz_as_duas_leituras_quando_o_aluguel_pesa():
    from valuation.relatorio import montar

    visao = ver_ex_ifrs16(_rede())
    texto = montar(avaliar(_empresa_rede()), analise=_rede(), ifrs16=visao)

    assert "## O aluguel, dentro e fora do EBITDA" in texto
    assert "não se misturam" in texto
    assert "Margem EBITDA ex-IFRS 16" in texto


def test_aluguel_pequeno_nao_ganha_secao_no_relatorio():
    """Secao inteira para dizer que os dois numeros sao iguais gasta atencao."""
    from valuation.relatorio import montar

    leve = ver_ex_ifrs16(_rede(aluguel_principal=2.0, aluguel_juros=1.0))
    texto = montar(avaliar(_empresa_rede()), ifrs16=leve)
    assert "## O aluguel, dentro e fora do EBITDA" not in texto


def test_o_relatorio_explica_a_linha_de_arrendamento_projetada():
    from valuation.relatorio import montar

    empresa = replace(
        _empresa_rede(),
        operacionais=_operacionais(arrendamento_pct_receita=[0.30] * 5),
    )
    texto = montar(avaliar(empresa))
    assert "Arrendamento / receita" in texto
    assert "não passa pelo capex" in texto


def _empresa_rede():
    from valuation.premissas import (
        Empresa,
        PonteValor,
        PremissasCustoCapital,
        PremissasPerpetuidade,
    )

    return Empresa(
        nome="Rede",
        macro=PremissasMacro(),
        operacionais=_operacionais(),
        custo_capital=PremissasCustoCapital(beta_alavancado_setor=1.0, divida_pl_alvo=0.5),
        perpetuidade=PremissasPerpetuidade(crescimento_perpetuo=0.045, roic_perpetuidade=0.15),
        ponte=PonteValor(divida_bruta=400.0, caixa=50.0),
        unidade="R$ mi",
    )
