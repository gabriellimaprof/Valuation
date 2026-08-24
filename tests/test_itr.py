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
    assert list(tri.valores.columns) == [
        "1T24", "2T24", "3T24", "1T25", "2T25", "3T25",
    ]

    ltm = importar_ltm(WEG, cache=DADOS, ano=2025)
    # O acumulado de nove meses e o que o ano movel soma ao exercicio fechado.
    do_ano = receita[["1T25", "2T25", "3T25"]]
    assert float(do_ano.sum()) == pytest.approx(30_557_000_000.0, rel=0.001)


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


# ---------------------------------------------------------------------------
# O mesmo trimestre do exercicio anterior
# ---------------------------------------------------------------------------


def test_a_serie_trimestral_traz_o_exercicio_anterior():
    """O `PENULTIMO` dobra a serie sem baixar outro zip.

    O par que se compara e 3T contra 3T, e ate aqui a serie tinha um exercicio
    so -- o par nao existia dentro dela. O ITR publica o mesmo trimestre do ano
    passado ao lado do corrente, e ele estava sendo lido so no caminho do ano
    movel.
    """
    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    assert list(tri.valores.columns) == [
        "1T24", "2T24", "3T24", "1T25", "2T25", "3T25",
    ]
    receita = tri.valores.loc["receita_liquida"]
    # 3T25 contra 3T24, que e a leitura sem sazonalidade.
    assert float(receita["3T24"]) == pytest.approx(9_856_900_000.0, rel=0.001)
    assert float(receita["3T25"]) == pytest.approx(10_271_500_000.0, rel=0.001)


def test_o_ano_anterior_bate_com_o_itr_do_proprio_ano():
    """Lido de dois jeitos, o mesmo trimestre tem de dar o mesmo numero.

    E a conferencia que separa "li o `PENULTIMO`" de "li alguma outra linha":
    o 3T24 vindo do `PENULTIMO` do ITR de 2025 contra o 3T24 vindo do `ULTIMO`
    do ITR de 2024.
    """
    from valuation.importacao.cvm import importar_trimestral

    de_2025 = importar_trimestral(WEG, cache=DADOS, ano=2025)
    de_2024 = importar_trimestral(WEG, cache=DADOS, ano=2024)
    for conta in ("receita_liquida", "lucro_liquido", "lucro_bruto"):
        for coluna in ("1T24", "2T24", "3T24"):
            assert float(de_2025.valores.loc[conta, coluna]) == pytest.approx(
                float(de_2024.valores.loc[conta, coluna]), rel=1e-6
            ), f"{conta} em {coluna}"


def test_o_ano_anterior_nao_inventa_balanco_nem_caixa():
    """Faltar e honesto; estar errado, nao.

    O `PENULTIMO` do balanco e o saldo de **31/12**, igual nas tres datas de
    referencia -- entra-lo como "1T24", "2T24" e "3T24" poria o mesmo saldo de
    dezembro em tres colunas de trimestres diferentes. E a DFC do ano anterior
    so tem o acumulado: o de nove meses entraria rotulado como um trimestre,
    tres vezes maior. As duas linhas tem de vir **vazias**.
    """
    import numpy as np

    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    for conta in ("patrimonio_liquido", "ativo_total", "caixa_operacional"):
        if conta not in tri.valores.index:
            continue
        anteriores = tri.valores.loc[conta, ["1T24", "2T24", "3T24"]]
        assert anteriores.isna().all() or (anteriores == 0).all(), (
            f"{conta} veio preenchido no exercicio anterior: "
            f"{anteriores.to_dict()}"
        )
    # E o exercicio corrente continua trazendo o balanco.
    assert np.isfinite(float(tri.valores.loc["patrimonio_liquido", "3T25"]))


def test_o_balanco_nao_soma_no_trimestre():
    """Saldo é uma data, e não um período.

    Somar o patrimônio pelos trimestres produziria um número que não existe —
    é o mesmo erro que o ano móvel separa por construção.
    """
    from valuation.importacao.cvm import importar_trimestral

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    # So o exercicio corrente: o balanco do ano anterior nao existe no ITR, e
    # vem vazio de proposito (ver ``test_o_ano_anterior_nao_inventa_balanco``).
    patrimonio = tri.valores.loc["patrimonio_liquido", ["1T25", "2T25", "3T25"]]
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


def test_o_crescimento_trimestral_e_ano_contra_ano():
    """1T25 se compara com 1T24, e nunca com a coluna à esquerda.

    A coluna à esquerda de 1T25 é 3T24: dividir uma pela outra mede a distância
    entre épocas diferentes do ano **e** pula o 4T24, que nem está na série. Na
    WEG a diferença é o oposto de pequena — a leitura sequencial dizia +0,6% no
    3T25 e a leitura certa diz +4,2%, com desaceleração de 25,5% para 4,2% ao
    longo do ano, que a sequencial escondia por completo.
    """
    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_trimestral

    indicadores = analisar(
        importar_trimestral(WEG, cache=DADOS, ano=2025)
    ).indicadores
    crescimento = indicadores.loc["Crescimento da receita"]

    # O primeiro exercicio nao tem com o que se comparar.
    assert crescimento[["1T24", "2T24", "3T24"]].isna().all()
    assert float(crescimento["1T25"]) == pytest.approx(0.2546, abs=0.001)
    assert float(crescimento["3T25"]) == pytest.approx(0.0421, abs=0.001)

    # E a conta e mesmo contra o mesmo trimestre do ano anterior.
    receita = importar_trimestral(WEG, cache=DADOS, ano=2025).valores.loc[
        "receita_liquida"
    ]
    assert float(crescimento["3T25"]) == pytest.approx(
        float(receita["3T25"]) / float(receita["3T24"]) - 1, rel=1e-9
    )


def test_o_crescimento_anual_continua_sendo_o_ano_anterior():
    """A série anual não muda: ali o par comparável já é a coluna à esquerda."""
    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm

    dfs = importar_cvm(WEG, [2023, 2024, 2025], cache=DADOS)
    indicadores = analisar(dfs).indicadores
    crescimento = indicadores.loc["Crescimento da receita"]
    receita = dfs.valores.loc["receita_liquida"]

    import math

    assert math.isnan(float(crescimento.iloc[0]))
    for anterior, atual in zip(dfs.valores.columns, dfs.valores.columns[1:]):
        assert float(crescimento[atual]) == pytest.approx(
            float(receita[atual]) / float(receita[anterior]) - 1, rel=1e-9
        )


def test_o_rotulo_de_trimestre_diz_o_periodo():
    """O rótulo já carrega o que a coluna é — não é preciso um sinalizador."""
    from valuation.importacao.series import anterior_comparavel, periodo_do_rotulo

    assert periodo_do_rotulo("3T25") == (2025, 3)
    assert periodo_do_rotulo("1T2024") == (2024, 1)
    assert periodo_do_rotulo(2024) is None
    assert periodo_do_rotulo("5T25") is None

    trimestral = anterior_comparavel(["1T24", "2T24", "3T24", "1T25", "2T25", "3T25"])
    assert trimestral == {"1T25": "1T24", "2T25": "2T24", "3T25": "3T24"}

    anual = anterior_comparavel([2022, 2023, 2024])
    assert anual == {2023: 2022, 2024: 2023}


# ---------------------------------------------------------------------------
# A serie trimestral atravessa o app inteiro
# ---------------------------------------------------------------------------


def test_um_valuation_trimestral_pode_ser_salvo():
    """Salvar forçava `int(ano)` em toda coluna, e `int("1T24")` estoura.

    O defeito é anterior à série do ano anterior — os rótulos já eram `1T25` —,
    e ninguém o tinha visto porque a série trimestral nunca fora percorrida no
    navegador. Um valuation montado sobre ela **não podia ser salvo**.

    Converter para o ano do exercício não serve: 1T24, 2T24 e 3T24 virariam a
    mesma chave 2024 e três trimestres colapsariam em um. O rótulo é guardado
    como ele é.
    """
    import tempfile

    from valuation.importacao.cvm import importar_trimestral
    from valuation.projeto import Projeto, carregar, salvar
    from valuation.premissas import (
        PonteValor,
        PremissasCustoCapital,
        PremissasMacro,
        PremissasOperacionais,
        PremissasPerpetuidade,
    )
    from valuation.modelo import Empresa

    tri = importar_trimestral(WEG, cache=DADOS, ano=2025)
    empresa = Empresa(
        nome="WEG SA",
        macro=PremissasMacro(),
        custo_capital=PremissasCustoCapital(
            beta_alavancado_setor=1.0, divida_pl_setor=0.4, divida_pl_alvo=0.4
        ),
        operacionais=PremissasOperacionais(
            receita_base=1000.0,
            crescimento_receita=[0.05] * 5,
            margem_ebitda=[0.20] * 5,
            depreciacao_pct_receita=[0.045] * 5,
            capex_pct_receita=[0.05] * 5,
            capital_giro_pct_receita=[0.12] * 5,
        ),
        perpetuidade=PremissasPerpetuidade(crescimento_perpetuo=0.03),
        ponte=PonteValor(divida_bruta=400.0, caixa=120.0, acoes_em_circulacao=100.0),
    )

    with tempfile.TemporaryDirectory() as pasta:
        caminho = salvar(
            Projeto(empresa=empresa, demonstracoes=tri), Path(pasta) / "t.json"
        )
        de_volta = carregar(caminho)

    assert de_volta.demonstracoes is not None
    # Os seis trimestres continuam seis, e na ordem.
    assert list(de_volta.demonstracoes.valores.columns) == list(
        tri.valores.columns
    )
    assert float(de_volta.demonstracoes.valores.loc["receita_liquida", "3T25"]) == (
        pytest.approx(float(tri.valores.loc["receita_liquida", "3T25"]))
    )
    # E a arvore publicada tambem: o filtro `isinstance(ano, int)` a salvava
    # vazia numa serie trimestral, sem que nada dissesse.
    assert de_volta.demonstracoes.detalhe is not None
    assert not de_volta.demonstracoes.detalhe.empty


def test_o_ano_do_exercicio_sai_de_qualquer_rotulo():
    """As telas precisam do exercício; a coluna precisa do rótulo inteiro.

    São duas perguntas diferentes, e confundi-las é o que quebrava Múltiplos,
    Valor e Exportar: a safra do universo de pares é por exercício, mas
    `int("1T25")` estoura.
    """
    from valuation.importacao.series import ano_do_rotulo

    assert ano_do_rotulo("3T25") == 2025
    assert ano_do_rotulo(2024) == 2024
    assert ano_do_rotulo("2024") == 2024
    assert ano_do_rotulo("nada") is None


def test_sem_dados_nao_ha_ebitda_e_ele_nao_vira_o_ebit():
    """Zero publicado é dado; ausência não é — e a soma não confunde os dois.

    `ebitda()` somava com `fill_value=0`, então uma coluna sem D&A devolvia o
    próprio EBIT. É o defeito que o projeto já documentou como o maior da base
    ("as outras 142 tinham EBITDA igual ao EBIT"), e a série trimestral o
    tornava alcançável de novo: no mesmo trimestre do exercício anterior a DFC
    não existe, então a D&A da coluna vem vazia e a margem EBITDA saía igual à
    margem EBIT, calada.
    """
    import numpy as np
    import pandas as pd

    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            2023: {"receita_liquida": 1000.0, "ebit": 100.0,
                   "depreciacao_amortizacao": 0.0},
            2024: {"receita_liquida": 1000.0, "ebit": 100.0,
                   "depreciacao_amortizacao": 40.0},
            2025: {"receita_liquida": 1000.0, "ebit": 100.0},
        }
    )
    ebitda = Demonstracoes(empresa="Teste", valores=valores).ebitda()

    # Zero publicado: o EBITDA e o EBIT, e isso e a leitura correta.
    assert float(ebitda[2023]) == pytest.approx(100.0)
    assert float(ebitda[2024]) == pytest.approx(140.0)
    # Ausente: vazio, e nao 100.
    assert not np.isfinite(float(ebitda[2025]))
