"""Testes dos casos especiais: prejuizo fiscal, P&D, ciclicidade e leasing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from valuation import avaliar, substituir_varios
from valuation.casos_especiais import (
    capitalizar_leasing_operacional,
    capitalizar_pesquisa_desenvolvimento,
    normalizar_margem_ciclica,
)
from valuation.dados_setoriais import (
    buscar_setor,
    listar_setores,
    macro_do_pais,
    premissas_do_setor,
)
from valuation.historico import analisar
from valuation.importacao import Demonstracoes
from valuation.projecao import calcular_impostos

# ---------------------------------------------------------------------------
# Prejuizo fiscal acumulado (trava dos 30%)
# ---------------------------------------------------------------------------


def test_sem_prejuizo_o_imposto_e_o_normal():
    impostos, saldo = calcular_impostos(np.array([100.0, 100.0]), 0.34)
    assert impostos == pytest.approx([34.0, 34.0])
    assert saldo == pytest.approx([0.0, 0.0])


def test_trava_dos_30_por_cento():
    """Mesmo com prejuizo de sobra, so 30% do lucro do ano pode ser compensado."""
    impostos, saldo = calcular_impostos(np.array([100.0]), 0.34, prejuizo_acumulado=500.0)
    # Compensa 30 (30% de 100), tributa 70.
    assert impostos[0] == pytest.approx(70.0 * 0.34)
    assert saldo[0] == pytest.approx(470.0)


def test_prejuizo_pequeno_e_totalmente_compensado():
    """Abaixo da trava, o saldo e consumido inteiro."""
    impostos, saldo = calcular_impostos(np.array([100.0]), 0.34, prejuizo_acumulado=10.0)
    assert impostos[0] == pytest.approx(90.0 * 0.34)
    assert saldo[0] == pytest.approx(0.0)


def test_prejuizo_do_exercicio_engrossa_o_saldo():
    impostos, saldo = calcular_impostos(np.array([-50.0, 100.0]), 0.34)
    assert impostos[0] == 0.0          # prejuizo nao gera credito
    assert saldo[0] == pytest.approx(50.0)
    assert impostos[1] == pytest.approx(70.0 * 0.34)   # compensa 30 dos 50
    assert saldo[1] == pytest.approx(20.0)


def test_saldo_e_consumido_ao_longo_dos_anos():
    ebit = np.array([100.0, 100.0, 100.0, 100.0])
    _, saldo = calcular_impostos(ebit, 0.34, prejuizo_acumulado=100.0)
    assert saldo == pytest.approx([70.0, 40.0, 10.0, 0.0])


def test_prejuizo_negativo_e_rejeitado():
    with pytest.raises(ValueError, match="positivo"):
        calcular_impostos(np.array([100.0]), 0.34, prejuizo_acumulado=-10.0)


def test_prejuizo_fiscal_aumenta_o_valor_da_empresa(empresa_exemplo):
    """O beneficio fiscal e caixa a mais nos primeiros anos, que pesam mais no VP."""
    sem = avaliar(empresa_exemplo)
    com = avaliar(substituir_varios(empresa_exemplo, {"prejuizo_fiscal_acumulado": 300.0}))
    assert com.equity_value > sem.equity_value


# ---------------------------------------------------------------------------
# Capitalizacao de P&D
# ---------------------------------------------------------------------------


def test_capitalizacao_de_pd_com_conta_fechada():
    """Gasto constante de 100 por 5 anos, vida util de 5."""
    gastos = {2020: 100.0, 2021: 100.0, 2022: 100.0, 2023: 100.0, 2024: 100.0}
    ajuste = capitalizar_pesquisa_desenvolvimento(gastos, vida_util=5)

    # Ativo = 100*(5/5 + 4/5 + 3/5 + 2/5 + 1/5) = 100 * 3 = 300
    assert ajuste.ativo_de_pd == pytest.approx(300.0)
    # Amortizacao = 4 anos anteriores x 100/5 = 80 (o ano corrente ainda nao amortiza)
    assert ajuste.amortizacao_do_ano == pytest.approx(80.0)
    # EBIT sobe o gasto do ano menos a amortizacao
    assert ajuste.ajuste_no_ebit == pytest.approx(20.0)


def test_pd_ignora_gastos_mais_velhos_que_a_vida_util():
    gastos = {2018: 999.0, 2023: 100.0, 2024: 100.0}
    ajuste = capitalizar_pesquisa_desenvolvimento(gastos, vida_util=3)
    assert 2018 not in ajuste.detalhamento.index
    assert ajuste.ativo_de_pd == pytest.approx(100.0 + 100.0 * 2 / 3)


def test_pd_com_um_unico_ano():
    ajuste = capitalizar_pesquisa_desenvolvimento({2024: 100.0}, vida_util=5)
    assert ajuste.ativo_de_pd == pytest.approx(100.0)
    assert ajuste.amortizacao_do_ano == pytest.approx(0.0)
    assert ajuste.ajuste_no_ebit == pytest.approx(100.0)


def test_pd_tem_detalhamento_auditavel():
    ajuste = capitalizar_pesquisa_desenvolvimento({2023: 50.0, 2024: 60.0}, vida_util=3)
    assert list(ajuste.detalhamento.columns) == [
        "Gasto com P&D", "Idade (anos)", "Parcela nao amortizada",
        "Valor no ativo", "Amortizacao no ano corrente",
    ]
    assert ajuste.detalhamento["Valor no ativo"].sum() == pytest.approx(ajuste.ativo_de_pd)
    assert "P&D" in ajuste.explicacao


def test_pd_exige_dados():
    with pytest.raises(ValueError, match="ao menos um ano"):
        capitalizar_pesquisa_desenvolvimento({})
    with pytest.raises(ValueError, match="vida_util"):
        capitalizar_pesquisa_desenvolvimento({2024: 10.0}, vida_util=0)


# ---------------------------------------------------------------------------
# Normalizacao ciclica
# ---------------------------------------------------------------------------


def _analise_ciclica(margens: list[float]):
    anos = list(range(2024 - len(margens) + 1, 2025))
    receita = [1000.0] * len(margens)
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": receita[i],
                "ebit": receita[i] * margens[i],
                "lucro_liquido": receita[i] * margens[i] * 0.6,
                "ativo_total": 2000.0,
                "patrimonio_liquido": 1000.0,
                "caixa_equivalentes": 100.0,
            }
            for i, ano in enumerate(anos)
        }
    )
    return analisar(Demonstracoes(empresa="Ciclica S.A.", valores=valores))


def test_normalizacao_usa_a_mediana_do_ciclo():
    analise = _analise_ciclica([0.10, 0.25, 0.15, 0.30, 0.20])
    resultado = normalizar_margem_ciclica(analise)
    assert resultado.margem_normalizada == pytest.approx(0.20)
    assert resultado.margem_do_ultimo_ano == pytest.approx(0.20)
    assert resultado.amplitude == pytest.approx(0.20)


def test_identifica_pico_do_ciclo():
    analise = _analise_ciclica([0.10, 0.12, 0.15, 0.18, 0.30])
    resultado = normalizar_margem_ciclica(analise)
    assert resultado.posicao_no_ciclo == "pico"
    assert resultado.margem_normalizada < resultado.margem_do_ultimo_ano


def test_identifica_fundo_do_ciclo():
    analise = _analise_ciclica([0.30, 0.28, 0.22, 0.18, 0.08])
    resultado = normalizar_margem_ciclica(analise)
    assert resultado.posicao_no_ciclo == "fundo"
    assert resultado.margem_normalizada > resultado.margem_do_ultimo_ano


def test_normalizacao_exige_historico_suficiente():
    analise = _analise_ciclica([0.10, 0.20])
    with pytest.raises(ValueError, match="ao menos 3 anos"):
        normalizar_margem_ciclica(analise)


def test_explicacao_da_normalizacao_cita_a_posicao():
    analise = _analise_ciclica([0.10, 0.12, 0.15, 0.18, 0.30])
    assert "pico" in normalizar_margem_ciclica(analise).explicacao


# ---------------------------------------------------------------------------
# Leasing operacional
# ---------------------------------------------------------------------------


def test_leasing_e_valor_presente_dos_alugueis():
    ajuste = capitalizar_leasing_operacional(
        despesa_anual=100.0, prazo_anos=5, custo_divida=0.10
    )
    esperado = sum(100.0 / 1.10**t for t in range(1, 6))
    assert ajuste.divida_equivalente == pytest.approx(esperado)
    assert ajuste.ajuste_no_ebit == pytest.approx(esperado * 0.10)


def test_prazo_maior_gera_divida_maior():
    curto = capitalizar_leasing_operacional(100.0, 3, 0.10).divida_equivalente
    longo = capitalizar_leasing_operacional(100.0, 10, 0.10).divida_equivalente
    assert longo > curto


def test_leasing_valida_entradas():
    with pytest.raises(ValueError, match="prazo_anos"):
        capitalizar_leasing_operacional(100.0, 0, 0.10)
    with pytest.raises(ValueError, match="custo_divida"):
        capitalizar_leasing_operacional(100.0, 5, 0.0)


def test_leasing_tem_detalhamento_que_soma_a_divida():
    ajuste = capitalizar_leasing_operacional(100.0, 5, 0.10)
    assert ajuste.detalhamento["Valor presente"].sum() == pytest.approx(
        ajuste.divida_equivalente
    )


# ---------------------------------------------------------------------------
# Dados setoriais
# ---------------------------------------------------------------------------


def test_listar_setores():
    tabela = listar_setores()
    assert len(tabela) >= 20
    assert "Varejo" in tabela.index
    assert tabela.loc["Varejo", "Beta desalavancado"] > 0


def test_busca_de_setor_tolera_acento_e_caixa():
    assert buscar_setor("varejo").nome == "Varejo"
    assert buscar_setor("Energia Eletrica").nome == "Energia eletrica"
    assert buscar_setor("telecomunicacoes").nome == "Telecomunicacoes"


def test_setor_inexistente():
    with pytest.raises(ValueError, match="nao encontrado"):
        buscar_setor("Criptomoedas de terceira geracao")


def test_premissas_do_setor_usam_beta_desalavancado():
    """O beta do setor descreve o risco do negocio; a alavancagem e da empresa."""
    premissas = premissas_do_setor("Varejo", divida_pl_alvo=0.8)
    assert premissas.beta_desalavancado == pytest.approx(buscar_setor("Varejo").beta_desalavancado)
    assert premissas.divida_pl_alvo == pytest.approx(0.8)


def test_premissas_do_setor_usam_risco_pais_do_pais():
    brasil = premissas_do_setor("Varejo", pais="Brasil")
    eua = premissas_do_setor("Varejo", pais="Estados Unidos")
    assert brasil.risco_pais > eua.risco_pais
    assert eua.risco_pais == 0.0


def test_pais_inexistente():
    with pytest.raises(ValueError, match="nao encontrado"):
        premissas_do_setor("Varejo", pais="Atlantida")


def test_macro_do_pais():
    macro = macro_do_pais("Brasil")
    assert macro.inflacao_brl == pytest.approx(0.04)
    assert macro.aliquota_ir == pytest.approx(0.34)


def test_setor_gera_valuation_completo(empresa_exemplo):
    """Escolher o setor precisa produzir um modelo diretamente avaliavel."""
    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital": premissas_do_setor("Energia eletrica")}
    )
    resultado = avaliar(empresa)
    assert np.isfinite(resultado.equity_value)
    assert 0.05 < resultado.custo_capital.wacc_brl < 0.30


# ---------------------------------------------------------------------------
# Arrendamento ja no balanco
# ---------------------------------------------------------------------------


def test_ler_leasing_mede_peso_e_crescimento():
    """O que a ponte subtrai, e como aquilo se moveu."""
    import pandas as pd

    from valuation.casos_especiais import ler_leasing
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2022: {
                "receita_liquida": 1000.0,
                "ebit": 150.0,
                "arrendamento_curto_prazo": 40.0,
                "arrendamento_longo_prazo": 160.0,
                "divida_curto_prazo": 90.0,
                "divida_longo_prazo": 310.0,
            },
            2024: {
                "receita_liquida": 1440.0,
                "ebit": 220.0,
                "arrendamento_curto_prazo": 60.0,
                "arrendamento_longo_prazo": 240.0,
                "divida_curto_prazo": 130.0,
                "divida_longo_prazo": 470.0,
            },
        }
    )
    leasing = ler_leasing(analisar(Demonstracoes(empresa="X", valores=valores)))

    assert leasing.saldo == pytest.approx(300.0)
    assert leasing.peso == pytest.approx(0.50)
    assert leasing.relevante
    assert leasing.acompanha_a_receita
    # 200 -> 300 em uma observacao de intervalo: 50% no periodo.
    assert leasing.crescimento_anual == pytest.approx(0.50)
    assert "50,0%" in leasing.explicacao.replace(".", ",") or "50.0%" in leasing.explicacao


def test_sem_arrendamento_o_peso_e_ausente_e_nao_zero():
    """Conta que a companhia nao publica e ausencia de informacao, nao zero."""
    import numpy as np
    import pandas as pd

    from valuation.casos_especiais import ler_leasing
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {"receita_liquida": 1000.0, "ebit": 150.0, "divida_curto_prazo": 100.0},
            2024: {"receita_liquida": 1100.0, "ebit": 160.0, "divida_curto_prazo": 120.0},
        }
    )
    leasing = ler_leasing(analisar(Demonstracoes(empresa="X", valores=valores)))

    assert np.isnan(leasing.peso)
    assert not leasing.relevante
    assert "Não há passivo de arrendamento" in leasing.explicacao


def test_adicao_implicita_e_ordem_de_grandeza_do_que_a_projecao_ignora():
    from valuation.casos_especiais import LeasingNoBalanco

    leasing = LeasingNoBalanco(
        saldo=1000.0,
        divida_bruta=2000.0,
        peso=0.5,
        crescimento_anual=0.15,
        crescimento_receita=0.12,
        anos=5,
    )
    assert leasing.adicao_anual_implicita(0.10) == pytest.approx(100.0)
