"""Testes do diagnostico automatico do modelo."""

from __future__ import annotations

import pandas as pd
import pytest

from valuation import avaliar, substituir_varios
from valuation.diagnostico import ALERTA, ERRO, diagnosticar
from valuation.historico import analisar
from valuation.importacao import Demonstracoes


def _codigos(diagnostico) -> set[str]:
    return {achado.codigo for achado in diagnostico.achados}


def test_modelo_saudavel_nao_gera_erro(empresa_exemplo):
    diagnostico = diagnosticar(avaliar(empresa_exemplo))
    assert diagnostico.aprovado
    assert not diagnostico.erros


def test_crescimento_perpetuo_acima_da_economia(empresa_exemplo):
    """Nenhuma empresa cresce acima do PIB para sempre sem virar o PIB."""
    empresa = substituir_varios(
        empresa_exemplo, {"perpetuidade.crescimento_perpetuo": 0.09}
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert "g_acima_da_economia" in _codigos(diagnostico)


def test_spread_estreito_entre_wacc_e_g(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.crescimento_perpetuo": resultado.dcf.taxa_desconto - 0.01},
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert "spread_wacc_g_estreito" in _codigos(diagnostico)


def test_perpetuidade_sem_reinvestimento(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"perpetuidade.roic_perpetuidade": None})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "perpetuidade_sem_reinvestimento" in _codigos(diagnostico)


def test_roic_perpetuo_abaixo_do_wacc(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.08})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "roic_perpetuo_abaixo_do_wacc" in _codigos(diagnostico)


def test_roic_perpetuo_excepcional(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.40})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "roic_perpetuo_excepcional" in _codigos(diagnostico)


def test_capex_abaixo_da_depreciacao_com_crescimento(empresa_exemplo):
    empresa = substituir_varios(
        empresa_exemplo,
        {
            "operacionais.capex_pct_receita": 0.02,
            "operacionais.depreciacao_pct_receita": 0.06,
        },
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert "capex_abaixo_da_depreciacao" in _codigos(diagnostico)


def test_beta_fora_da_faixa(empresa_exemplo):
    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital.beta_alavancado_setor": 4.0}
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert "beta_fora_da_faixa" in _codigos(diagnostico)


def test_wacc_fora_da_faixa_pega_erro_de_unidade(empresa_exemplo):
    """O caso real: alguem digita 4,5 em vez de 0,045 na taxa livre de risco."""
    empresa = substituir_varios(empresa_exemplo, {"custo_capital.rf_usd": 0.45})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "wacc_fora_da_faixa" in _codigos(diagnostico)


def test_kd_acima_do_ke(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"custo_capital.custo_divida_brl": 0.60})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "kd_acima_do_ke" in _codigos(diagnostico)


def test_peso_da_perpetuidade_alto(empresa_exemplo):
    """Projecao curta com margem baixa joga quase tudo para a perpetuidade."""
    empresa = substituir_varios(empresa_exemplo, {"operacionais.margem_ebitda": 0.08})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "peso_da_perpetuidade" in _codigos(diagnostico)


def test_equity_negativo_e_erro(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"ponte.divida_bruta": 100000.0})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "equity_negativo" in _codigos(diagnostico)
    assert not diagnostico.aprovado
    assert diagnostico.erros[0].severidade == ERRO


def test_achados_vem_ordenados_por_severidade(empresa_exemplo):
    empresa = substituir_varios(
        empresa_exemplo,
        {"ponte.divida_bruta": 100000.0, "perpetuidade.crescimento_perpetuo": 0.09},
    )
    diagnostico = diagnosticar(avaliar(empresa))
    severidades = [a.severidade for a in diagnostico.achados]
    assert severidades[0] == ERRO
    assert severidades == sorted(severidades, key=lambda s: {"erro": 0, "alerta": 1, "informacao": 2}[s])


def test_todo_achado_explica_e_orienta(empresa_exemplo):
    """O valor educacional depende disso: dizer o que houve, por que e o que fazer."""
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.crescimento_perpetuo": 0.09, "custo_capital.beta_alavancado_setor": 4.0},
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert len(diagnostico) >= 2
    for achado in diagnostico.achados:
        assert len(achado.titulo) > 10
        assert len(achado.detalhe) > 40
        assert len(achado.acao) > 15


def test_tabela_do_diagnostico(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"perpetuidade.crescimento_perpetuo": 0.09})
    tabela = diagnosticar(avaliar(empresa)).tabela()
    assert list(tabela.columns) == [
        "Severidade", "Achado", "Detalhe", "O que fazer", "Referencia"
    ]


# ---------------------------------------------------------------------------
# Comparacoes com o historico da propria empresa
# ---------------------------------------------------------------------------


@pytest.fixture
def analise_historica():
    valores = pd.DataFrame(
        {
            2022: {
                "receita_liquida": 1000.0, "ebit": 150.0, "lucro_liquido": 80.0,
                "ativo_total": 1200.0, "patrimonio_liquido": 500.0,
                "caixa_equivalentes": 100.0, "divida_longo_prazo": 400.0,
                "depreciacao_amortizacao": 50.0, "capex": 60.0,
                "lucro_antes_impostos": 120.0, "impostos": 40.0,
            },
            2023: {
                "receita_liquida": 1050.0, "ebit": 158.0, "lucro_liquido": 84.0,
                "ativo_total": 1250.0, "patrimonio_liquido": 540.0,
                "caixa_equivalentes": 110.0, "divida_longo_prazo": 410.0,
                "depreciacao_amortizacao": 52.0, "capex": 62.0,
                "lucro_antes_impostos": 126.0, "impostos": 42.0,
            },
            2024: {
                "receita_liquida": 1100.0, "ebit": 165.0, "lucro_liquido": 88.0,
                "ativo_total": 1300.0, "patrimonio_liquido": 580.0,
                "caixa_equivalentes": 120.0, "divida_longo_prazo": 420.0,
                "depreciacao_amortizacao": 55.0, "capex": 65.0,
                "lucro_antes_impostos": 132.0, "impostos": 44.0,
            },
        }
    )
    return analisar(Demonstracoes(empresa="Historico S.A.", valores=valores))


def test_margem_projetada_acima_do_melhor_ano_historico(empresa_exemplo, analise_historica):
    """A margem historica ronda 20%; projetar 35% precisa de justificativa."""
    empresa = substituir_varios(empresa_exemplo, {"operacionais.margem_ebitda": 0.35})
    diagnostico = diagnosticar(avaliar(empresa), analise=analise_historica)
    assert "margem_acima_do_historico" in _codigos(diagnostico)


def test_crescimento_projetado_acima_do_historico(empresa_exemplo, analise_historica):
    empresa = substituir_varios(empresa_exemplo, {"operacionais.crescimento_receita": 0.25})
    diagnostico = diagnosticar(avaliar(empresa), analise=analise_historica)
    assert "crescimento_acima_do_historico" in _codigos(diagnostico)


def test_roic_perpetuo_acima_do_historico(empresa_exemplo, analise_historica):
    empresa = substituir_varios(empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.45})
    diagnostico = diagnosticar(avaliar(empresa), analise=analise_historica)
    assert "roic_perpetuo_acima_do_historico" in _codigos(diagnostico)


def test_sem_historico_as_comparacoes_sao_puladas(empresa_exemplo):
    empresa = substituir_varios(empresa_exemplo, {"operacionais.margem_ebitda": 0.35})
    diagnostico = diagnosticar(avaliar(empresa))
    assert "margem_acima_do_historico" not in _codigos(diagnostico)


# ---------------------------------------------------------------------------
# Verificacoes sobre a tese de retorno
# ---------------------------------------------------------------------------


def _decomposicao(tsr_alvo: str = "bom", **ajustes):
    """Monta uma decomposicao de TSR com a caracteristica que o teste precisa."""
    from valuation.retorno import decompor_tsr

    base = dict(
        preco_entrada=100.0,
        lucro_entrada=10.0,
        lucro_saida=10.0 * 1.10**5,
        dividendos=[5.0] * 5,
        multiplo_saida=None,
    )
    base.update(ajustes)
    return decompor_tsr(**base)


def test_retorno_abaixo_do_exigido(empresa_exemplo):
    """Comprar caro faz o retorno esperado ficar abaixo do que o risco pede."""
    resultado = avaliar(empresa_exemplo)
    caro = _decomposicao(preco_entrada=400.0, dividendos=[1.0] * 5)
    diagnostico = diagnosticar(resultado, retorno=caro)
    assert "retorno_abaixo_do_exigido" in _codigos(diagnostico)


def test_retorno_acima_do_exigido_nao_gera_achado(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    barato = _decomposicao(preco_entrada=60.0)
    diagnostico = diagnosticar(resultado, retorno=barato)
    assert "retorno_abaixo_do_exigido" not in _codigos(diagnostico)


def test_retorno_dependente_de_rerating(empresa_exemplo):
    """Empresa parada e multiplo dobrando: o ganho e do mercado, nao do negocio."""
    resultado = avaliar(empresa_exemplo)
    rerating = _decomposicao(
        lucro_saida=10.0, dividendos=[0.0] * 5, multiplo_saida=20.0
    )
    diagnostico = diagnosticar(resultado, retorno=rerating)
    assert "retorno_depende_de_rerating" in _codigos(diagnostico)
    achado = next(
        a for a in diagnostico.achados if a.codigo == "retorno_depende_de_rerating"
    )
    assert "expansão" in achado.titulo


def test_contracao_de_multiplo_tambem_e_sinalizada(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    contracao = _decomposicao(
        preco_entrada=200.0, lucro_saida=10.0, dividendos=[0.0] * 5, multiplo_saida=8.0
    )
    diagnostico = diagnosticar(resultado, retorno=contracao)
    achados = [a for a in diagnostico.achados if a.codigo == "retorno_depende_de_rerating"]
    assert achados and "contração" in achados[0].titulo


def test_retorno_implausivel(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    absurdo = _decomposicao(preco_entrada=20.0, dividendos=[8.0] * 5)
    diagnostico = diagnosticar(resultado, retorno=absurdo)
    assert "retorno_implausivel" in _codigos(diagnostico)


def test_multiplo_de_saida_generoso(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    generoso = _decomposicao(multiplo_saida=14.0)  # entrada e 10x
    diagnostico = diagnosticar(resultado, retorno=generoso)
    assert "multiplo_de_saida_generoso" in _codigos(diagnostico)


def test_sem_rerating_nao_ha_achado_de_multiplo(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    neutro = _decomposicao()  # sai pelo mesmo multiplo da entrada
    codigos = _codigos(diagnosticar(resultado, retorno=neutro))
    assert "multiplo_de_saida_generoso" not in codigos
    assert "retorno_depende_de_rerating" not in codigos


def test_sem_retorno_informado_as_verificacoes_sao_puladas(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    codigos = _codigos(diagnosticar(resultado))
    assert not any(c.startswith("retorno_") for c in codigos)


def test_achados_de_retorno_tambem_explicam_e_orientam(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    rerating = _decomposicao(
        lucro_saida=10.0, dividendos=[0.0] * 5, multiplo_saida=20.0
    )
    diagnostico = diagnosticar(resultado, retorno=rerating)
    for achado in diagnostico.achados:
        if achado.codigo.startswith("retorno_") or "multiplo_de_saida" in achado.codigo:
            assert len(achado.detalhe) > 40
            assert len(achado.acao) > 15


def test_arrendamento_que_cresce_e_nao_e_projetado_vira_alerta(empresa_exemplo):
    """O achado fala do fluxo, nao do estoque.

    Contrato novo de aluguel cria passivo sem passar pelo capex: a projecao
    mostra EBITDA subindo, capex parado e FCFF generoso, enquanto a divida real
    cresce todo ano. A ponte, congelada na data-base, nunca ve isso.
    """
    import pandas as pd

    from valuation import avaliar
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    def demonstracoes(arrendamento_final: float) -> Demonstracoes:
        return Demonstracoes(
            empresa="Rede de Lojas",
            valores=pd.DataFrame(
                {
                    2022: {
                        "receita_liquida": 1000.0,
                        "ebit": 150.0,
                        "arrendamento_longo_prazo": 200.0,
                        "divida_longo_prazo": 400.0,
                    },
                    2024: {
                        "receita_liquida": 1440.0,
                        "ebit": 220.0,
                        "arrendamento_longo_prazo": arrendamento_final,
                        "divida_longo_prazo": 600.0,
                    },
                }
            ),
        )

    resultado = avaliar(empresa_exemplo)

    cresce = diagnosticar(resultado, analise=analisar(demonstracoes(400.0)))
    assert "arrendamento_cresce_e_nao_e_projetado" in {a.codigo for a in cresce.achados}

    # Arrendamento encolhendo nao levanta o achado: nao ha adicao a projetar.
    encolhe = diagnosticar(resultado, analise=analisar(demonstracoes(100.0)))
    assert "arrendamento_cresce_e_nao_e_projetado" not in {a.codigo for a in encolhe.achados}


# ---------------------------------------------------------------------------
# A perpetuidade do arrendamento
# ---------------------------------------------------------------------------


def test_o_valor_terminal_supoe_abertura_de_pontos_para_sempre(empresa_exemplo):
    """O fluxo que entra no Gordon já vem líquido da adição de arrendamento.

    Como a adição acompanha a receita e a receita cresce a ``g``, a hipótese
    embutida é que a razão arrendamento/receita fica constante **para sempre**.
    É consistente — quem cresce mantendo intensidade de aluguel precisa mesmo de
    contrato novo — e é o padrão por isso. Mas não é neutra, e ninguém a escolheu.

    Medido em companhias reais, a distância para a leitura alternativa (a rede
    para de crescer em área no fim do horizonte) vai de **+6,9%** de equity nas
    Lojas Renner a **+96,7%** no Grupo SBF.
    """
    horizonte = len(empresa_exemplo.operacionais.crescimento_receita)
    com_aluguel = substituir_varios(
        empresa_exemplo,
        {"operacionais.arrendamento_pct_receita": [0.20] * horizonte},
    )
    diagnostico = diagnosticar(avaliar(com_aluguel))
    assert "arrendamento_cresce_para_sempre" in _codigos(diagnostico)

    achado = next(
        a for a in diagnostico.achados if a.codigo == "arrendamento_cresce_para_sempre"
    )
    assert "para sempre" in achado.titulo
    # Diz **quanto custa**, que é o que permite escolher.
    assert "maior" in achado.detalhe


def test_sem_arrendamento_projetado_nao_ha_o_que_avisar(empresa_exemplo):
    """Quem não aluga nada não pode receber um alerta sobre aluguel."""
    diagnostico = diagnosticar(avaliar(empresa_exemplo))
    assert "arrendamento_cresce_para_sempre" not in _codigos(diagnostico)


def test_adicao_pequena_nao_vira_achado(empresa_exemplo):
    """Abaixo de 10% do FCFF terminal é detalhe do fluxo, e não premissa de valor.

    Sinal que dispara em todo mundo não dirige atenção, gasta.
    """
    horizonte = len(empresa_exemplo.operacionais.crescimento_receita)
    pouco = substituir_varios(
        empresa_exemplo,
        {"operacionais.arrendamento_pct_receita": [0.005] * horizonte},
    )
    assert "arrendamento_cresce_para_sempre" not in _codigos(
        diagnosticar(avaliar(pouco))
    )
