"""ITR trimestral e o ano movel que sai dele.

O fixture e um recorte em bytes do ``itr_cia_aberta_2025.zip`` publicado, com
tres companhias escolhidas por comportamento: WEG fecha o exercicio em dezembro,
Sao Martinho em marco, e Raia Drogasil e varejo com arrendamento pesado.

A armadilha propria do ITR, confirmada no arquivo antes de existir codigo: para
``DT_REFER`` de 30/09 a DRE traz **duas** linhas da mesma conta -- o acumulado do
exercicio e o trimestre isolado. Somar as duas infla em um terco; pegar a errada
muda o numero pela metade. E no primeiro trimestre ha uma linha so, entao "pegar
a ultima" acerta em marco e erra em setembro.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from valuation.importacao.cvm import (
    ErroCVM,
    _linhas_do_itr,
    importar_cvm,
    importar_ltm,
    periodo_acumulado,
    trimestres_disponiveis,
)

DADOS = Path(__file__).parent / "dados" / "cvm"
ITR = DADOS / "itr_cia_aberta_2025.zip"
WEG, SAO_MARTINHO, RAIA = 5410, 20516, 5258


# ---------------------------------------------------------------------------
# O contrato do arquivo
# ---------------------------------------------------------------------------


def test_o_itr_traz_um_registro_por_trimestre_entregue():
    assert trimestres_disponiveis(ITR, 2025, WEG) == [
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
    ]


def test_o_acumulado_e_a_linha_de_periodo_mais_longo():
    """A regra que funciona em qualquer trimestre, e nao so no primeiro."""
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-09-30", "ultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]

    assert len(receita) == 1, "sobrou o trimestre isolado junto do acumulado"
    # Acumulado de janeiro a setembro de 2025, direto do arquivo.
    assert receita[0].valor == pytest.approx(30_557_320_000.0)


def test_no_primeiro_trimestre_acumulado_e_trimestre_coincidem():
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-03-31", "ultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]
    assert len(receita) == 1
    assert receita[0].valor == pytest.approx(10_078_571_000.0)


def test_o_penultimo_do_itr_e_dado_util_e_nao_lixo():
    """No DFP o PENULTIMO duplica anos; aqui e a metade que falta do ano movel."""
    linhas = _linhas_do_itr(ITR, 2025, "dre", WEG, [], "con", "2025-09-30", "penultimo")
    receita = [linha for linha in linhas if linha.codigo == "3.01"]
    assert receita[0].valor == pytest.approx(27_164_665_000.0)


def test_o_periodo_acumulado_segue_o_exercicio_social():
    """Sao Martinho fecha em marco: o acumulado comeca em abril, nao em janeiro."""
    assert periodo_acumulado(ITR, 2025, WEG, "con", "2025-09-30") == (
        "2025-01-01",
        "2025-09-30",
    )
    assert periodo_acumulado(ITR, 2025, SAO_MARTINHO, "con", "2025-12-31") == (
        "2025-04-01",
        "2025-12-31",
    )


def test_o_balanco_do_itr_e_saldo_e_nao_periodo():
    linhas = _linhas_do_itr(ITR, 2025, "bp", WEG, [], "con", "2025-09-30", "ultimo")
    ativo = [linha for linha in linhas if linha.codigo == "1"]
    assert len(ativo) == 1
    assert ativo[0].valor == pytest.approx(41_494_475_000.0)


# ---------------------------------------------------------------------------
# O ano movel
# ---------------------------------------------------------------------------


def test_o_ano_movel_fecha_a_conta_de_ponta_a_ponta():
    """LTM = exercicio fechado + acumulado - mesmo periodo do ano anterior."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    anual = importar_cvm(WEG, [2024], cache=DADOS)

    esperado = (
        anual.valor("receita_liquida", 2024) + 30_557_320_000.0 - 27_164_665_000.0
    )
    assert ltm.valor("receita_liquida") == pytest.approx(esperado)
    assert ltm.fonte["ano_base"] == 2024
    assert ltm.fonte["ltm"] == "2025-09-30"


def test_o_balanco_do_ano_movel_e_o_saldo_do_trimestre():
    """Somar balanco pela formula do LTM daria um patrimonio que nao existe."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    assert ltm.valor("ativo_total") == pytest.approx(41_494_475_000.0)
    # E continua fechando a identidade contabil.
    assert ltm.valor("ativo_total") == pytest.approx(ltm.valor("passivo_total"))


def test_exercicio_social_quebrado_escolhe_a_base_certa():
    """Sao Martinho acumula de abril; a base e o exercicio encerrado em marco."""
    ltm = importar_ltm(SAO_MARTINHO, cache=DADOS, ano=2025)
    assert ltm.fonte["ano_base"] == 2025, "pegou o exercicio errado"

    anual = importar_cvm(SAO_MARTINHO, [2025], cache=DADOS)
    esperado = (
        anual.valor("receita_liquida", 2025) + 5_188_107_000.0 - 5_424_459_000.0
    )
    assert ltm.valor("receita_liquida") == pytest.approx(esperado)


def test_o_ano_movel_avisa_que_nao_e_exercicio_social():
    """Ler "2025" numa coluna de ano movel e entender ano cheio."""
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    aviso = " ".join(ltm.avisos)
    assert "não é um exercício social" in aviso
    assert "2025-09-30" in aviso


def test_a_origem_de_cada_conta_diz_como_ela_foi_montada():
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    assert "acumulado" in ltm.mapeamento["receita_liquida"]
    assert "saldo em 2025-09-30" == ltm.mapeamento["ativo_total"]


def test_companhia_sem_itr_no_ano_da_erro_claro():
    with pytest.raises(ErroCVM, match="ITR"):
        importar_ltm(999_999, cache=DADOS, ano=2025)


def test_o_ano_movel_alimenta_a_analise_historica():
    """O ponto do LTM e plugar no motor sem que nada mais mude."""
    from valuation.historico import analisar

    ltm = importar_ltm(RAIA, cache=DADOS, ano=2025).escalar(1e6, "R$ milhões")
    analise = analisar(ltm)

    assert "Margem EBITDA" in analise.indicadores.index
    margem = analise.mediana("Margem EBITDA")
    assert 0.05 < margem < 0.20, f"margem implausivel para varejo: {margem}"


def test_o_ano_movel_se_junta_a_serie_anual_sem_duplicar_coluna():
    """A tela emenda o LTM na serie; duas colunas do mesmo ano seriam um degrau falso."""
    from dataclasses import replace

    anual = importar_cvm(WEG, [2023, 2024], cache=DADOS)
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    rotulo = ltm.anos[-1]

    valores = anual.valores.drop(columns=[rotulo], errors="ignore").join(
        ltm.valores, how="outer"
    )
    juntas = replace(
        anual,
        valores=valores[sorted(valores.columns)],
        avisos=list(anual.avisos) + list(ltm.avisos),
    )

    assert juntas.anos == [2023, 2024, 2025]
    assert len(set(juntas.anos)) == len(juntas.anos), "coluna duplicada"
    assert juntas.valor("receita_liquida", 2025) > juntas.valor("receita_liquida", 2024)
    assert any("exercício social" in aviso for aviso in juntas.avisos)


# ---------------------------------------------------------------------------
# A varredura de qualidade, aplicada ao trimestral
# ---------------------------------------------------------------------------


def test_o_metodo_direto_e_detectado_tambem_no_trimestral():
    """``grupo`` não viajava na ``LinhaCVM`` do ITR.

    Sem ele ``detectar_metodo_da_dfc`` não vê o ``DFC_MD`` do trimestral, e a DFC
    direta é lida com os códigos do indireto — o mesmo defeito que o anual já
    tinha corrigido. Medido no ITR de 2025: a detecção passou de 3 para 12
    companhias.
    """
    from valuation.importacao.cvm import LinhaCVM, detectar_metodo_da_dfc

    def linha(grupo: str) -> LinhaCVM:
        return LinhaCVM(
            codigo="6.01.01",
            descricao="Recebimentos proprios",
            valor=1.0,
            ano=2025,
            demonstracao="dfc",
            escala="MIL",
            escopo="con",
            grupo=grupo,
        )

    assert detectar_metodo_da_dfc([linha("DFC_MD")]) == "direto"
    assert detectar_metodo_da_dfc([linha("DFC_MI")]) == "indireto"


def test_a_ponte_que_nao_fecha_no_ano_movel_vira_aviso():
    """O ano móvel soma três períodos, e a identidade não sobrevive à soma.

    Medido no ITR de 2025: a ponte fecha em 430 das 454, e das 24 que sobram
    **18 quebram no lucro dos controladores** — a Melhoramentos de São Paulo
    reconcilia no exercício fechado e não no ano móvel, porque a divisão com
    minoritários mudou entre os trimestres. Não dá para saber qual atribuição
    descreve o período móvel, então o app avisa em vez de derivar por diferença.
    """
    import pandas as pd

    from valuation.importacao.cvm import _avisar_se_a_dre_do_ano_movel_nao_fecha

    quebrada = pd.DataFrame(
        {
            2025: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "lucro_bruto": 400.0,
                "ebit": 200.0,
                "lucro_antes_impostos": 170.0,
                "impostos": 50.0,
                "lucro_liquido": 120.0,
                # A atribuicao nao fecha: 40 + 0 != 120.
                "lucro_controladores": 40.0,
                "lucro_nao_controladores": 0.0,
            }
        }
    )
    avisos: list[str] = []
    _avisar_se_a_dre_do_ano_movel_nao_fecha(quebrada, 2025, avisos)
    assert avisos and "Controladores" in avisos[0]
    assert "avisa em vez de derivar" in avisos[0]


def test_ano_movel_que_fecha_nao_gera_aviso():
    """Aviso que dispara em quem está certo treina o leitor a ignorar."""
    import pandas as pd

    from valuation.importacao.cvm import _avisar_se_a_dre_do_ano_movel_nao_fecha

    inteira = pd.DataFrame(
        {
            2025: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "lucro_bruto": 400.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "resultado_financeiro": -30.0,
                "receitas_financeiras": 20.0,
                "despesas_financeiras": 50.0,
                "lucro_antes_impostos": 170.0,
                "imposto_corrente": -40.0,
                "imposto_diferido": -10.0,
                "impostos": 50.0,
                "lucro_liquido": 120.0,
                "lucro_controladores": 120.0,
                "lucro_nao_controladores": 0.0,
            }
        }
    )
    avisos: list[str] = []
    _avisar_se_a_dre_do_ano_movel_nao_fecha(inteira, 2025, avisos)
    assert not avisos, avisos


def test_a_ponte_prefere_o_par_de_impostos_que_reconcilia():
    """No ano móvel a abertura vem de fontes diferentes e pode não somar o total.

    Na Magalu, a de 2024 traz ``3.08.01`` e ``3.08.02`` **zerados** com o imposto
    todo no pai; somar as filhas das três fontes perdia R$ 361,3 mi e a ponte
    quebrava por essa diferença exata. A condição anterior era só "as duas filhas
    são zero", que não alcança a mistura de fontes.
    """
    import numpy as np
    import pandas as pd

    from valuation.importacao import Demonstracoes

    incoerente = Demonstracoes(
        empresa="Teste",
        valores=pd.DataFrame(
            {
                2025: {
                    "receita_liquida": 1000.0,
                    "custo_produtos_vendidos": 600.0,
                    "lucro_bruto": 400.0,
                    "ebit": 200.0,
                    "resultado_financeiro": -30.0,
                    "receitas_financeiras": 20.0,
                    "despesas_financeiras": 50.0,
                    "lucro_antes_impostos": 170.0,
                    # A abertura soma -10, mas o total diz -50.
                    "imposto_corrente": -8.0,
                    "imposto_diferido": -2.0,
                    "impostos": 50.0,
                    "lucro_liquido": 120.0,
                    "lucro_controladores": 120.0,
                    "lucro_nao_controladores": 0.0,
                }
            }
        ),
    )
    conferencia = incoerente.conferir_dre_gerencial()
    pior = float(np.nanmax(conferencia.to_numpy(dtype=float)))
    assert pior < 1e-9, conferencia.to_string()


def test_o_ano_movel_le_as_seis_demonstracoes():
    """O ITR lia três; o zip trimestral traz as mesmas seis do anual.

    Medido no ITR de 2025: DVA com 116.854 linhas de 460 companhias, DRA com
    32.114 e DMPL com 623.847. Fora dali ficavam **sete contas canônicas que só
    existem na DVA** — receita bruta, pessoal, impostos e taxas, aluguel, juros e
    o valor adicionado —, que respondem o que a DRE padronizada não abre e sumiam
    do ano móvel sem que nada dissesse.
    """
    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    assert ltm.detalhe is not None and not ltm.detalhe.empty
    presentes = set(ltm.detalhe["demonstracao"])
    for demonstracao in ("dre", "bp", "dfc", "dva"):
        assert demonstracao in presentes, presentes


def test_a_dva_do_ano_movel_traz_a_receita_bruta():
    """Contra a líquida do ``3.01``, a diferença são impostos sobre vendas.

    Na WEG dá 9,3% no ano móvel, contra os 9,0% medidos no exercício fechado — a
    conta atravessa o ano móvel sem perder o sentido.
    """
    import numpy as np

    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    bruta = ltm.valor("receita_bruta")
    liquida = ltm.valor("receita_liquida")
    assert np.isfinite(bruta) and np.isfinite(liquida)
    assert bruta > liquida
    assert 0.05 < (bruta - liquida) / bruta < 0.15


def test_o_aviso_do_ano_movel_diz_o_tamanho_da_diferenca():
    """"Não fecha" sem tamanho não ajuda a decidir.

    Quem lê precisa saber se o problema vale 0,3% ou 78% do resultado: no
    primeiro caso segue, no segundo para e vai ao arquivo. Medido no ITR de 2025:
    a Melhoramentos de São Paulo quebra em **78% do lucro consolidado** e a Azul
    em **690%** — e as duas apareciam com o mesmo texto.
    """
    import pandas as pd

    from valuation.importacao.cvm import _avisar_se_a_dre_do_ano_movel_nao_fecha

    tabela = pd.DataFrame(
        {
            2025: {
                "receita_liquida": 1000.0,
                "custo_produtos_vendidos": 600.0,
                "lucro_bruto": 400.0,
                "ebit": 200.0,
                "lucro_antes_impostos": 170.0,
                "impostos": 50.0,
                "lucro_liquido": 120.0,
                "lucro_controladores": 40.0,
                "lucro_nao_controladores": 0.0,
            }
        }
    )
    avisos: list[str] = []
    _avisar_se_a_dre_do_ano_movel_nao_fecha(tabela, 2025, avisos)
    assert avisos
    # 120 - 0 - 40 = 80, que e 67% do lucro consolidado.
    assert "80" in avisos[0]
    assert "67% do lucro consolidado" in avisos[0]


def test_sem_lucro_consolidado_o_aviso_nao_inventa_percentual():
    """Dividir por zero para dar um percentual seria pior que não dá-lo."""
    import pandas as pd

    from valuation.importacao.cvm import _tamanho_da_diferenca

    sem_lucro = pd.DataFrame(
        {2025: {"lucro_liquido": 0.0, "lucro_controladores": 40.0}}
    )
    texto = _tamanho_da_diferenca(sem_lucro, 2025, ["Controladores"])
    assert "%" not in texto


def test_quebra_fora_dos_controladores_nao_ganha_o_tamanho():
    """O cálculo é sobre a atribuição a minoritários; noutro passo não se aplica."""
    import pandas as pd

    from valuation.importacao.cvm import _tamanho_da_diferenca

    tabela = pd.DataFrame(
        {2025: {"lucro_liquido": 120.0, "lucro_controladores": 40.0}}
    )
    assert _tamanho_da_diferenca(tabela, 2025, ["LAIR"]) == ""


# ---------------------------------------------------------------------------
# As tres leituras do tempo
# ---------------------------------------------------------------------------


def test_o_trimestre_isolado_soma_o_acumulado():
    """Os três meses sozinhos, e não o acumulado do exercício.

    É a verificação que prova qual das duas linhas foi lida: a CVM publica as
    duas lado a lado na mesma conta, e a escolha é por **duração**. Somados, os
    trimestres isolados têm que dar o acumulado — na WEG, 10.079 + 10.207 +
    10.272 = 30.558 contra os 30.557 do acumulado de nove meses.
    """
    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    receita = tri.valores.loc["receita_liquida"]
    assert list(tri.valores.columns) == ["1T25", "2T25", "3T25"]

    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    # O acumulado de nove meses e o que o ano movel soma ao exercicio fechado.
    assert float(receita.sum()) == pytest.approx(30_557_000_000.0, rel=0.001)


def test_o_trimestre_isolado_nao_e_o_acumulado():
    """Se fossem iguais, a leitura teria pego a linha errada.

    No primeiro trimestre as duas coincidem por construção — há uma linha só —,
    e é por isso que a escolha é por duração e não por posição.
    """
    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    receita = tri.valores.loc["receita_liquida"]
    # Cada trimestre e cerca de um terco do acumulado de nove meses.
    for valor in receita:
        assert 8e9 < float(valor) < 13e9, receita.to_dict()


def test_o_balanco_nao_soma_no_trimestre():
    """Saldo é uma data, e não um período.

    Somar o patrimônio pelos trimestres produziria um número que não existe —
    é o mesmo erro que o ano móvel separa por construção.
    """
    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    patrimonio = tri.valores.loc["patrimonio_liquido"]
    # Cresce trimestre a trimestre, e cada um e o saldo -- nao um terco do total.
    assert list(patrimonio) == sorted(patrimonio)
    assert float(patrimonio.iloc[-1]) > 20e9


def test_o_ano_movel_rolante_e_uma_serie_e_mostra_tendencia():
    """Um ano móvel sozinho não mostra tendência.

    Doze meses em queda e doze em alta dão o mesmo ponto no último trimestre; a
    série é o que separa os dois. Na WEG a receita móvel sobe de 40.032 para
    41.380 ao longo de 2025.
    """
    from valuation.importacao.cvm import importar_ltm_rolante

    rolante = importar_ltm_rolante(WEG, cache=DADOS, ano=2025)
    assert list(rolante.valores.columns) == ["1T25", "2T25", "3T25"]
    receita = [float(v) for v in rolante.valores.loc["receita_liquida"]]
    assert receita == sorted(receita)
    # E cada coluna e um ano inteiro, e nao um trimestre.
    assert all(v > 35e9 for v in receita)


def test_a_ultima_coluna_do_rolante_e_o_ano_movel_pontual():
    """A série reusa a mesma função, e não reimplementa a fórmula.

    Duas implementações da mesma conta divergem no dia em que uma das duas muda.
    """
    from valuation.importacao.cvm import importar_ltm_rolante

    rolante = importar_ltm_rolante(WEG, cache=DADOS, ano=2025)
    pontual = importar_ltm(WEG, cache=DADOS, ano=2025)
    for chave in ("receita_liquida", "ebit", "lucro_liquido", "patrimonio_liquido"):
        assert float(rolante.valores.loc[chave].iloc[-1]) == pytest.approx(
            float(pontual.valor(chave))
        )


def test_cada_serie_declara_o_que_ela_e():
    """Misturar as três leituras é o erro clássico, e o aviso existe para isso."""
    from valuation.importacao.cvm import importar_ltm_rolante, importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    assert any("sazonalidade" in a for a in tri.avisos)
    assert any("isolados" in a for a in tri.avisos)

    rolante = importar_ltm_rolante(WEG, cache=DADOS, ano=2025)
    assert any("doze meses" in a for a in rolante.avisos)
    assert any("nao e um exercicio social" in a or "não é um exercício social" in a.lower()
               for a in rolante.avisos)
