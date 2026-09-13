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


@pytest.mark.parametrize(
    ("metodo", "campo"),
    [("usd", "custo_capital.rf_usd"), ("local", "custo_capital.rf_brl")],
)
def test_wacc_fora_da_faixa_pega_erro_de_unidade(empresa_exemplo, metodo, campo):
    """O caso real: alguem digita 4,5 em vez de 0,045 na taxa livre de risco.

    O campo em que o engano acontece **depende do caminho** que monta o Ke, e o
    teste antes so cobria um deles -- entao quando o padrao mudou ele passou a
    testar um numero que nao entra na conta. A verificacao em si nunca dependeu
    do caminho: ela olha o WACC que saiu.
    """
    empresa = substituir_varios(
        empresa_exemplo, {"custo_capital.metodo": metodo, campo: 0.45}
    )
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


# ---------------------------------------------------------------------------
# O achado de conversao olha o degrau de cima antes de acusar a operacao
# ---------------------------------------------------------------------------


def _analise_com_dfc(cgo, giro, imposto, juro, ebit=800.0, da=200.0):
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    fco = cgo + giro - abs(imposto) - abs(juro)
    linha = {
        "receita_liquida": 5000.0, "ebit": ebit, "depreciacao_amortizacao": da,
        "lucro_liquido": 500.0, "lucro_antes_impostos": 700.0, "impostos": 200.0,
        "patrimonio_liquido": 3000.0, "ativo_total": 6000.0,
        "caixa_das_operacoes": cgo, "fluxo_operacional": fco,
        "variacao_capital_giro": giro, "impostos_pagos": imposto,
        "juros_pagos": juro,
    }
    valores = pd.DataFrame({2023: dict(linha), 2024: dict(linha)})
    return analisar(
        Demonstracoes(empresa="Teste", valores=valores, unidade="R$ milhões")
    )


def _achado_da_conversao(resultado, analise):
    from valuation.diagnostico import diagnosticar

    return next(
        (
            a
            for a in diagnosticar(resultado, analise).achados
            if a.codigo == "ebitda_nao_vira_caixa"
        ),
        None,
    )


def test_o_achado_nao_acusa_a_operacao_quando_o_cgo_e_alto(empresa_exemplo):
    """Metade da base tem CGO alto e FCO baixo.

    O achado dizia "receita reconhecida antes de ser recebida" para todas elas,
    quando o resultado vira caixa e o consumo esta abaixo da operacao.
    """
    from valuation import avaliar

    # CGO = 110% do EBITDA, e juro come 85% dele.
    analise = _analise_com_dfc(cgo=1100.0, giro=-50.0, imposto=100.0, juro=850.0)
    achado = _achado_da_conversao(avaliar(empresa_exemplo), analise)

    assert achado is not None, "o achado precisa continuar disparando"
    assert "a operação converte" in achado.titulo
    assert "resultado vira caixa" in achado.detalhe
    assert "ponte" in achado.acao


def test_o_achado_acusa_a_operacao_quando_o_cgo_e_baixo(empresa_exemplo):
    """A ressalva nao pode virar desculpa."""
    from valuation import avaliar

    analise = _analise_com_dfc(cgo=200.0, giro=-50.0, imposto=50.0, juro=50.0)
    achado = _achado_da_conversao(avaliar(empresa_exemplo), analise)

    assert achado is not None
    assert "a operação converte" not in achado.titulo
    assert "antes de ser recebida" in achado.detalhe


def test_capex_perpetuo_muito_acima_da_depreciacao(empresa_exemplo):
    """O inverso de `capex_abaixo_da_depreciacao`, e ele faltava.

    A lacuna apareceu medindo a correção do capex de imóvel de renda: com
    "propriedades para investimento" dentro da conta, a premissa da Multiplan
    foi de 1,5% para 28,2% da receita e o equity caiu **59,8%**. A leitura ficou
    certa — o dinheiro saiu mesmo —, e a projeção passou a supor que ela
    constrói shopping no mesmo ritmo eternamente.

    O corte é o P90 medido na safra 2021-2025 (n=389), onde a mediana é 1,0x:
    repor o que se deprecia. O teste monta o caso a partir da constante, e não
    de um número solto — corte recalibrado não pode virar falha sozinho.
    """
    from valuation.diagnostico import CAPEX_MUITO_ACIMA_DA_DEPRECIACAO

    deprec = 0.05
    empresa = substituir_varios(
        empresa_exemplo,
        {
            "operacionais.depreciacao_pct_receita": deprec,
            "operacionais.capex_pct_receita": deprec * (CAPEX_MUITO_ACIMA_DA_DEPRECIACAO + 1),
        },
    )
    diagnostico = diagnosticar(avaliar(empresa))
    assert "capex_perpetuo_acima_da_depreciacao" in _codigos(diagnostico)

    achado = next(
        a for a in diagnostico.achados
        if a.codigo == "capex_perpetuo_acima_da_depreciacao"
    )
    # O achado tem de dizer **quanto custa** a hipótese, e não só que ela está
    # montada: "supõe expansão para sempre" sem tamanho não ajuda a decidir.
    assert "maior" in achado.detalhe


def test_capex_no_estado_estacionario_nao_acusa(empresa_exemplo):
    """Capex igual à depreciação é o estado estacionário, e é a mediana da base.

    O contrapeso do teste acima: um sinal que dispara na mediana não dirige
    atenção, gasta — foi assim que `DESCOLAMENTO_DO_JURO` precisou ser
    recalibrado duas vezes neste projeto.
    """
    empresa = substituir_varios(
        empresa_exemplo,
        {
            "operacionais.depreciacao_pct_receita": 0.05,
            "operacionais.capex_pct_receita": 0.05,
        },
    )
    assert "capex_perpetuo_acima_da_depreciacao" not in _codigos(
        diagnosticar(avaliar(empresa))
    )


def _com_ciclo(receitas: list[float], recebiveis: list[float], estoques: list[float]):
    """Empresa com giro legível em quatro exercícios."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    anos = [2022, 2023, 2024, 2025]
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": receitas[i],
                "custo_produtos_vendidos": receitas[i] * 0.6,
                "ebit": receitas[i] * 0.15,
                "contas_receber": recebiveis[i],
                "estoques": estoques[i],
                "fornecedores": 100.0,
            }
            for i, ano in enumerate(anos)
        }
    )
    return analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$"))


def test_ciclo_alongando_com_receita_parada(empresa_exemplo):
    """O sinal é o cruzamento, e não o ciclo crescendo sozinho.

    Medido na safra 2021-2025 (n=392): alongar mais de 20 dias por ano acontece
    em 10,5% da base, e **cruzado com receita abaixo da inflação, em 3,1%** — a
    raridade de um sinal que pede ação. As companhias que ele pega são o caso
    clássico: Taurus com o ciclo indo de 158 para 313 dias e a receita caindo
    14,5% ao ano, Tegra de 523 para 828.
    """
    from valuation.diagnostico import CICLO_ALONGANDO

    # Receita parada e estoque inchando: o ciclo alonga bem acima do corte.
    analise = _com_ciclo(
        receitas=[1000.0, 1000.0, 1000.0, 1000.0],
        recebiveis=[200.0, 210.0, 220.0, 230.0],
        estoques=[150.0, 300.0, 450.0, 600.0],
    )
    diagnostico = diagnosticar(avaliar(empresa_exemplo), analise=analise)
    assert "ciclo_alonga_com_receita_parada" in _codigos(diagnostico)

    achado = next(
        a for a in diagnostico.achados if a.codigo == "ciclo_alonga_com_receita_parada"
    )
    # O achado nomeia **qual perna** puxou: "o ciclo alongou" sem dizer onde
    # manda o analista procurar nos três lugares.
    assert "estoque" in achado.detalhe
    # E traz o tamanho em caixa, porque dias não decidem nada sozinhos.
    assert "prendeu" in achado.detalhe
    assert str(int(CICLO_ALONGANDO)) in achado.detalhe


def test_ciclo_alongando_com_a_empresa_crescendo_nao_acusa(empresa_exemplo):
    """Crescer prende caixa no giro, e isso é consequência da venda maior.

    O contrapeso: sem esta condição o sinal acusaria toda empresa em expansão, e
    alarme que dispara no saudável treina quem lê a ignorá-lo — o defeito que
    `DESCOLAMENTO_DO_JURO` já custou duas recalibrações a este projeto.
    """
    analise = _com_ciclo(
        receitas=[1000.0, 1300.0, 1700.0, 2200.0],
        recebiveis=[200.0, 280.0, 380.0, 500.0],
        estoques=[150.0, 300.0, 450.0, 600.0],
    )
    assert "ciclo_alonga_com_receita_parada" not in _codigos(
        diagnosticar(avaliar(empresa_exemplo), analise=analise)
    )


def test_dois_pontos_nao_fazem_tendencia(empresa_exemplo):
    """Com um exercício de diferença, uma entrega concentrada basta para disparar."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 150.0,
                "contas_receber": 200.0,
                "estoques": 150.0 + i * 900.0,
                "fornecedores": 100.0,
            }
            for i, ano in enumerate([2024, 2025])
        }
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$"))
    assert "ciclo_alonga_com_receita_parada" not in _codigos(
        diagnosticar(avaliar(empresa_exemplo), analise=analise)
    )


def _analise_de(periodicidade, colunas):
    """Uma análise mínima com a periodicidade declarada."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            c: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "divida_bruta": 400.0,
                "juros_pagos": 20.0,
                "despesa_financeira": 40.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
                "caixa_das_operacoes": 150.0,
                "fluxo_operacional": 120.0,
            }
            for c in colunas
        }
    )
    return analisar(
        Demonstracoes(
            empresa="T",
            valores=valores,
            unidade="R$",
            periodicidade=periodicidade,
        )
    )


def test_a_serie_trimestral_omite_os_confrontos_e_diz_quais():
    """Lista de achados menor não é modelo mais limpo.

    Sete verificações confrontam a premissa — que é de um exercício — com o
    histórico da companhia. Numa série trimestral, um indicador que mistura
    fluxo com estoque sai a um quarto e o achado **inverte de sinal**: medido na
    WEG, o ROIC histórico é 36,6% na leitura anual e 8,2% na trimestral, então
    uma premissa de 15% aparece como "abaixo do histórico" num caso e "acima" no
    outro.

    O caso mais escondido era o Kd, que nem percentil tem: o achado publicava
    "a despesa financeira (41,3% da dívida)" na leitura anual e **18,8%** na
    trimestral — uma taxa de trimestre impressa como taxa ao ano.
    """
    from valuation.diagnostico import verificacoes_omitidas

    anual = _analise_de("anual", [2022, 2023, 2024, 2025])
    trimestral = _analise_de("trimestral", ["1T25", "2T25", "3T25"])

    assert verificacoes_omitidas(anual) == []
    omitidas = verificacoes_omitidas(trimestral)
    assert "ROIC" in omitidas
    assert "Custo da divida efetivo" in omitidas
    assert "Custo da divida pelo caixa" in omitidas
    assert "Crescimento da receita" in omitidas
    assert len(omitidas) == 7


def test_a_omissao_viaja_dentro_do_diagnostico(empresa_exemplo):
    """Ela mora no `Diagnostico`, e não em cada consumidor.

    São quatro — a tela, o relatório, o material do comitê e a barra lateral —,
    e a regra que cada um carrega por conta própria é a que um deles esquece.
    Foi exatamente assim que a mesa de comparação nasceu sem guarda de
    frequência.
    """
    from valuation import avaliar
    from valuation.diagnostico import diagnosticar

    resultado = avaliar(empresa_exemplo)
    trimestral = _analise_de("trimestral", ["1T25", "2T25", "3T25"])

    diag = diagnosticar(resultado, trimestral)
    assert diag.omitidas
    assert "ROIC" in diag.omitidas

    # E o relatorio e o material do comite dizem, em vez de calar.
    from valuation.relatorio import _omissoes_por_frequencia

    texto = " ".join(_omissoes_por_frequencia(diag))
    assert "não rodaram" in texto
    assert "ROIC" in texto

    from valuation.apresentacao import _avisos

    html = _avisos(diag)
    assert "não rodaram" in html


def test_serie_anual_nao_ganha_aviso_de_omissao(empresa_exemplo):
    """O controle: a guarda não pode aparecer no caminho normal."""
    from valuation import avaliar
    from valuation.apresentacao import _avisos
    from valuation.diagnostico import diagnosticar
    from valuation.relatorio import _omissoes_por_frequencia

    diag = diagnosticar(avaliar(empresa_exemplo), _analise_de("anual", [2022, 2023, 2024]))
    assert diag.omitidas == ()
    assert _omissoes_por_frequencia(diag) == []
    assert "não rodaram" not in _avisos(diag)


def _com_minoritarios(consolidado: float, controladores: float):
    """Uma análise com a atribuição do resultado que se quer testar."""
    import pandas as pd

    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
                "lucro_liquido": consolidado,
                "lucro_controladores": controladores,
            }
            for ano in (2023, 2024)
        }
    )
    return analisar(
        Demonstracoes(
            empresa="T", valores=valores, unidade="R$ milhões", periodicidade="anual"
        )
    )


def test_o_lucro_do_controlador_com_outro_sinal_vira_alerta():
    """**A leitura inverte**, e a imprensa noticiou o número errado para a ação.

    Medido no DFP consolidado de 2024, em 415 companhias: em **10 (2,4%)** o
    lucro consolidado e o dos controladores não têm o mesmo sinal. A Usiminas
    fecha 2024 com consolidado de **+R$ 3 mi** e **−R$ 146 mi** para o
    controlador — e a manchete foi "lucro líquido de R$ 3 milhões".

    Margem líquida, ROE e P/L sobre o consolidado descrevem o grupo, e não a
    ação. O app **não corrige** — o consolidado é leitura fiel do que a
    companhia publicou, e o ROE dele é consistente (consolidado sobre patrimônio
    consolidado, que também inclui minoritário). O que faltava era dizer.
    """
    from valuation.diagnostico import ALERTA, _minoritarios

    achados = _minoritarios(_com_minoritarios(3.4, -145.9))
    assert len(achados) == 1
    assert achados[0].codigo == "lucro_do_controlador_tem_outro_sinal"
    assert achados[0].severidade == ALERTA
    # O valor sai **com a unidade**: sem ela, "3,4" numa base em reais se lê
    # como milhões e o alerta erra a ordem de grandeza que ele quer mostrar.
    assert "R$ milhões" in achados[0].titulo


def test_minoritario_relevante_vira_informacao():
    """Na Metalúrgica Gerdau, **66% do lucro não é do acionista da listada**.

    O corte é 25% e acusa 13% da base — "um quarto do lucro não é seu" é limiar
    com significado próprio, e não só um quantil.
    """
    from valuation.diagnostico import INFORMACAO, _minoritarios

    achados = _minoritarios(_com_minoritarios(4611.0, 1545.0))
    assert len(achados) == 1
    assert achados[0].codigo == "lucro_em_boa_parte_dos_minoritarios"
    assert achados[0].severidade == INFORMACAO
    assert "66%" in achados[0].titulo


def test_sem_minoritario_relevante_nao_ha_achado():
    """O controle. Na WEG os controladores ficam com 97% — não é notícia."""
    from valuation.diagnostico import _minoritarios

    assert _minoritarios(_com_minoritarios(1000.0, 970.0)) == []


def test_o_indicador_do_controlador_existe_e_e_a_fracao():
    """Ele torna a distância comparável entre companhias, e não só um aviso."""
    import numpy as np

    analise = _com_minoritarios(4611.0, 1545.0)
    valor = float(analise.mediana("Lucro dos controladores / Lucro liquido"))
    assert np.isclose(valor, 1545.0 / 4611.0, atol=1e-6)


def test_o_achado_do_arrendamento_reconcilia_com_o_release():
    """A dívida do app inclui arrendamento; a manchete do release quase nunca.

    Conferido contra o divulgado de 2024: a Suzano publica dívida líquida de
    **R$ 79,0 bi** e o app lê **R$ 86,4 bi** — a diferença são os R$ 7,0 bi de
    arrendamento, e tirando-os o app dá **R$ 79,4 bi**, 0,6% do publicado. Na
    SmartFit a distância é de **2,8x** (8,4 contra 3,0), porque ela aluga todas
    as academias.

    Nenhum dos dois está errado, e incluir o arrendamento é a escolha certa para
    valuation — ele é dívida. O que faltava era a **ponte**: sem ela quem confere
    contra o release conclui que a leitura falhou, e o custo é o analista deixar
    de confiar no resto.
    """
    import pandas as pd

    from valuation.diagnostico import _ponte_com_o_release
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "ativo_total": 3000.0,
                "patrimonio_liquido": 1000.0,
                "divida_curto_prazo": 200.0,
                "divida_longo_prazo": 800.0,
                "caixa_equivalentes": 100.0,
                "arrendamento_curto_prazo": 40.0,
                "arrendamento_longo_prazo": 260.0,
            }
            for ano in (2023, 2024)
        }
    )
    analise = analisar(
        Demonstracoes(empresa="T", valores=valores, unidade="R$ milhões")
    )

    ponte = _ponte_com_o_release(analise)
    # **Ela entrega as parcelas, e nao uma alternativa composta.** Conferido
    # contra dois releases de 2024, cada companhia usa a sua definicao: a Suzano
    # tira o arrendamento (o app da 79.445 contra 79.000 publicados) e a Ultrapar
    # abate a aplicacao de longo prazo mantendo o arrendamento (11.163 - 3.407 =
    # 7.756, exato). Somar as duas nao bate com nenhuma.
    assert "900,0" in ponte  # a divida liquida do app: 1.000 - 100 de caixa
    assert "300,0" in ponte  # a parcela de arrendamento, para quem quiser tirar
    assert "R$ milhões" in ponte


def test_sem_arrendamento_nao_ha_ponte_a_fazer():
    """Frase que aparece sem ter o que reconciliar é ruído."""
    import pandas as pd

    from valuation.diagnostico import _ponte_com_o_release
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0,
                "ebit": 200.0,
                "ativo_total": 3000.0,
                "patrimonio_liquido": 1000.0,
                "divida_curto_prazo": 200.0,
                "divida_longo_prazo": 800.0,
            }
            for ano in (2023, 2024)
        }
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))
    assert _ponte_com_o_release(analise) == ""
