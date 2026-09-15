"""Verifica que as formulas gravadas no Excel reproduzem os numeros do Python.

Este e o teste mais importante do exportador: uma planilha bonita que calcula
diferente do motor e pior do que nenhuma planilha, porque o erro so aparece na
mao de quem recebeu o arquivo.

O teste depende do pacote ``formulas`` para avaliar o workbook fora do Excel;
sem ele, o teste e pulado em vez de dar falso positivo.
"""

from __future__ import annotations

import pytest

from valuation import avaliar, exportar_excel

formulas = pytest.importorskip("formulas", reason="pacote 'formulas' nao instalado")


def _valores_calculados(caminho) -> dict[str, float]:
    """Avalia o workbook e devolve o mapa de celula -> valor calculado."""
    modelo = formulas.ExcelModel().loads(str(caminho)).finish()
    solucao = modelo.calculate()
    valores = {}
    for chave, valor in solucao.items():
        try:
            valores[chave.upper()] = float(valor.value[0, 0])
        except (AttributeError, TypeError, ValueError, IndexError):
            continue
    return valores


def _buscar(valores: dict[str, float], aba: str, celula: str, caminho) -> float:
    """Localiza uma celula no resultado, que vem chaveado pelo caminho do arquivo."""
    alvo = f"'[{caminho.name.upper()}]{aba.upper()}'!{celula.upper()}"
    if alvo in valores:
        return valores[alvo]
    sufixo = f"]{aba.upper()}'!{celula.upper()}"
    candidatos = [v for k, v in valores.items() if k.endswith(sufixo)]
    if not candidatos:
        raise AssertionError(f"celula {aba}!{celula} nao encontrada no workbook avaliado")
    return candidatos[0]


def _localizar_linha(ws, rotulo: str) -> int:
    for linha in range(1, ws.max_row + 1):
        if ws.cell(row=linha, column=1).value == rotulo:
            return linha
    raise AssertionError(f"linha {rotulo!r} nao encontrada em {ws.title}")


@pytest.mark.parametrize("meio_de_ano", [False, True])
def test_excel_reproduz_o_motor_python(empresa_exemplo, tmp_path, meio_de_ano):
    from openpyxl import load_workbook

    resultado = avaliar(empresa_exemplo, meio_de_ano=meio_de_ano)
    caminho = tmp_path / "modelo.xlsx"
    exportar_excel(resultado, caminho)

    valores = _valores_calculados(caminho)
    wb = load_workbook(caminho)

    linha_wacc = _localizar_linha(wb["Custo de Capital"], "WACC (BRL nominal)")
    wacc_excel = _buscar(valores, "Custo de Capital", f"B{linha_wacc}", caminho)
    assert wacc_excel == pytest.approx(resultado.custo_capital.wacc_brl, rel=1e-9)

    aba_dcf = wb["DCF"]
    for rotulo, esperado in [
        ("VP dos fluxos do periodo explicito", resultado.dcf.valor_presente_explicito),
        ("Valor terminal (fim do ano n)", resultado.dcf.valor_terminal),
        ("VP do valor terminal", resultado.dcf.valor_presente_terminal),
        ("Enterprise Value", resultado.dcf.enterprise_value),
        ("Equity Value", resultado.dcf.equity_value),
    ]:
        linha = _localizar_linha(aba_dcf, rotulo)
        obtido = _buscar(valores, "DCF", f"B{linha}", caminho)
        assert obtido == pytest.approx(esperado, rel=1e-9), rotulo


def test_excel_reproduz_a_projecao(empresa_exemplo, tmp_path):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    resultado = avaliar(empresa_exemplo)
    caminho = tmp_path / "projecao.xlsx"
    exportar_excel(resultado, caminho)

    valores = _valores_calculados(caminho)
    ws = load_workbook(caminho)["Projecao"]
    n = resultado.projecao.horizonte

    for rotulo, esperado in [
        ("Receita liquida", resultado.projecao.receita),
        ("EBITDA", resultado.projecao.ebitda),
        ("NOPAT", resultado.projecao.nopat),
        ("FCFF (fluxo para a firma)", resultado.projecao.fcff),
    ]:
        linha = _localizar_linha(ws, rotulo)
        for i in range(n):
            celula = f"{get_column_letter(3 + i)}{linha}"
            obtido = _buscar(valores, "Projecao", celula, caminho)
            assert obtido == pytest.approx(float(esperado[i]), rel=1e-9), (
                f"{rotulo} ano {i + 1}"
            )


@pytest.mark.parametrize(
    ("base", "multiplo"), [("ebitda", 7.5), ("lucro", 12.0)]
)
def test_excel_reproduz_multiplo_de_saida(empresa_exemplo, tmp_path, base, multiplo):
    """A perpetuidade por multiplo usa um ramo de formula diferente do Gordon.

    E o P/L usa um terceiro: ele incide sobre o lucro liquido -- que a planilha
    monta a partir do NOPAT e do juro -- e devolve valor de equity, entao a
    formula tem de somar a divida liquida de volta. Planilha que calcula
    diferente do motor e pior que planilha nenhuma.
    """
    from openpyxl import load_workbook

    from valuation import substituir_varios

    empresa = substituir_varios(
        empresa_exemplo,
        {
            "perpetuidade.metodo": "multiplo",
            "perpetuidade.multiplo_saida": multiplo,
            "perpetuidade.base_do_multiplo": base,
        },
    )
    resultado = avaliar(empresa)
    caminho = tmp_path / f"multiplo_{base}.xlsx"
    exportar_excel(resultado, caminho)

    valores = _valores_calculados(caminho)
    ws = load_workbook(caminho)["DCF"]
    linha = _localizar_linha(ws, "Valor terminal (fim do ano n)")
    obtido = _buscar(valores, "DCF", f"B{linha}", caminho)
    assert obtido == pytest.approx(resultado.dcf.valor_terminal, rel=1e-9)

    if base == "lucro":
        linha_lucro = _localizar_linha(ws, "Lucro liquido do ano n (NOPAT - juros apos IR)")
        na_planilha = _buscar(valores, "DCF", f"B{linha_lucro}", caminho)
        assert na_planilha == pytest.approx(
            float(resultado.projecao.lucro_liquido[-1]), rel=1e-9
        )


# ---------------------------------------------------------------------------
# Aba de retorno (TSR)
# ---------------------------------------------------------------------------


def _montar_retorno(empresa, meio_de_ano: bool):
    from valuation.retorno import (
        decompor_tsr,
        multiplo_de_saida_do_dcf,
        projetar_acionista,
    )

    resultado = avaliar(empresa, meio_de_ano=meio_de_ano)
    acionista = projetar_acionista(
        resultado.projecao,
        divida_inicial=empresa.ponte.divida_bruta,
        custo_divida=resultado.custo_capital.kd_bruto_brl,
        aliquota_ir=empresa.macro.aliquota_ir,
        payout=0.4,
    )
    multiplo = multiplo_de_saida_do_dcf(
        resultado,
        float(acionista.lucro_liquido[-1]),
        float(acionista.divida_fechamento[-1]),
    )
    decomposicao = decompor_tsr(
        preco_entrada=resultado.equity_value,
        lucro_entrada=float(acionista.lucro_liquido[0]),
        lucro_saida=float(acionista.lucro_liquido[-1]),
        dividendos=acionista.dividendos,
        multiplo_saida=multiplo,
        meio_de_ano=meio_de_ano,
    )
    return resultado, acionista, decomposicao


def test_excel_reproduz_a_decomposicao_do_tsr(empresa_exemplo, tmp_path):
    """As contribuicoes na planilha tem que bater com as calculadas no Python."""
    from openpyxl import load_workbook

    resultado, acionista, decomposicao = _montar_retorno(empresa_exemplo, False)
    caminho = tmp_path / "tsr.xlsx"
    exportar_excel(resultado, caminho, retorno=decomposicao, acionista=acionista)

    valores = _valores_calculados(caminho)
    ws = load_workbook(caminho)["Retorno (TSR)"]

    for rotulo, esperado in [
        ("Crescimento do lucro", decomposicao.contribuicao_crescimento),
        ("Variacao de multiplo", decomposicao.contribuicao_multiplo),
        ("Termo cruzado", decomposicao.contribuicao_cruzada),
        ("Dividendos", decomposicao.contribuicao_dividendos),
        ("TSR esperado (TIR)", decomposicao.tsr),
    ]:
        linha = _localizar_linha(ws, rotulo)
        obtido = _buscar(valores, "Retorno (TSR)", f"B{linha}", caminho)
        assert obtido == pytest.approx(esperado, abs=1e-7), rotulo


def test_as_parcelas_somam_o_tsr_dentro_da_planilha(empresa_exemplo, tmp_path):
    """A conferencia tem que fechar no Excel, nao so no Python."""
    from openpyxl import load_workbook

    resultado, acionista, decomposicao = _montar_retorno(empresa_exemplo, False)
    caminho = tmp_path / "tsr_soma.xlsx"
    exportar_excel(resultado, caminho, retorno=decomposicao, acionista=acionista)

    valores = _valores_calculados(caminho)
    ws = load_workbook(caminho)["Retorno (TSR)"]

    linha_soma = _localizar_linha(ws, "Soma das parcelas (confere com o TSR)")
    linha_tsr = _localizar_linha(ws, "TSR esperado (TIR)")
    soma = _buscar(valores, "Retorno (TSR)", f"B{linha_soma}", caminho)
    tsr = _buscar(valores, "Retorno (TSR)", f"B{linha_tsr}", caminho)
    assert soma == pytest.approx(tsr, abs=1e-9)


def test_aba_de_retorno_so_aparece_quando_pedida(empresa_exemplo, tmp_path):
    from openpyxl import load_workbook

    resultado = avaliar(empresa_exemplo)
    caminho = tmp_path / "sem_tsr.xlsx"
    exportar_excel(resultado, caminho)
    assert "Retorno (TSR)" not in load_workbook(caminho).sheetnames


def test_a_ancora_do_g_viaja_para_a_planilha_como_formula(empresa_exemplo, tmp_path):
    """Exportar o g ancorado como numero fixo quebraria a ancora no Excel.

    Quem recebe a planilha mexe no IPCA da celula azul. Se o g estiver gravado
    como constante, ele nao acompanha -- e a planilha passa a discordar do app
    exatamente na premissa que o usuario esta estressando.
    """
    from openpyxl import load_workbook

    from valuation import substituir

    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    caminho = tmp_path / "ancorada.xlsx"
    exportar_excel(avaliar(ancorada), caminho)

    ws = load_workbook(caminho)["Premissas"]
    linha = _localizar_linha(ws, "Crescimento perpétuo (ancorado em PIB nominal)")
    assert str(ws.cell(row=linha, column=2).value).startswith("="), "saiu como constante"

    valores = _valores_calculados(caminho)
    g = _buscar(valores, "Premissas", f"B{linha}", caminho)
    assert g == pytest.approx(ancorada.perpetuidade.crescimento_perpetuo, abs=1e-9)

    linha_pib = _localizar_linha(ws, "Crescimento nominal da economia")
    nominal = _buscar(valores, "Premissas", f"B{linha_pib}", caminho)
    assert nominal == pytest.approx(ancorada.macro.pib_nominal, abs=1e-9)


@pytest.mark.parametrize("normalizado", [True, False])
def test_excel_reproduz_arrendamento_e_giro_inicial(empresa_exemplo, tmp_path, normalizado):
    """O FCFF do Excel nao tinha linha de arrendamento, e o giro do ano base saia do ano 1.

    Nenhum dos dois aparecia no teste de paridade porque o modelo de exemplo nao
    tem arrendamento nem saldo de giro de partida -- e todo modelo derivado do
    historico tem os dois. Sem normalizar, o valor terminal cresce o FCFF do ultimo
    ano, entao a renovacao tem de estar nele.
    """
    from dataclasses import replace

    from openpyxl import load_workbook

    op = empresa_exemplo.operacionais
    h = len(op.crescimento_receita)
    empresa = replace(
        empresa_exemplo,
        operacionais=replace(
            op,
            capital_giro_inicial=op.receita_base * op.capital_giro_pct_receita[0] * 0.8,
            arrendamento_pct_receita=[0.25] * h,
            arrendamento_inicial=op.receita_base * 0.20,
            arrendamento_renovacao_pct_receita=[0.03] * h,
        ),
    )
    if not normalizado:
        empresa = replace(
            empresa, perpetuidade=replace(empresa.perpetuidade, roic_perpetuidade=None)
        )
    resultado = avaliar(empresa)
    caminho = tmp_path / "modelo_arrendamento.xlsx"
    exportar_excel(resultado, caminho)

    valores = _valores_calculados(caminho)
    wb = load_workbook(caminho)
    aba_dcf = wb["DCF"]
    for rotulo, esperado in [
        ("VP dos fluxos do periodo explicito", resultado.dcf.valor_presente_explicito),
        ("Valor terminal (fim do ano n)", resultado.dcf.valor_terminal),
        ("Enterprise Value", resultado.dcf.enterprise_value),
        ("Equity Value", resultado.dcf.equity_value),
    ]:
        linha = _localizar_linha(aba_dcf, rotulo)
        obtido = _buscar(valores, "DCF", f"B{linha}", caminho)
        assert obtido == pytest.approx(esperado, rel=1e-9), rotulo


# ---------------------------------------------------------------------------
# A sensibilidade viva, o resumo e as abas novas
# ---------------------------------------------------------------------------


def test_a_sensibilidade_viva_reproduz_a_do_motor(empresa_exemplo, tmp_path):
    """Cada celula refaz o desconto na planilha; o motor faz por reavaliacao.

    Sao dois caminhos independentes para o mesmo numero -- e e isso que a
    conferencia vale. A versao antiga colava valores, e a planilha nao
    recalculava nada ao mexer numa premissa.
    """
    from openpyxl import load_workbook

    from valuation.sensibilidade import (
        PASSO_DA_GRADE,
        PONTOS_DA_GRADE,
        grade,
        tabela_sensibilidade,
    )

    resultado = avaliar(empresa_exemplo)
    caminho = tmp_path / "modelo_sensibilidade.xlsx"
    exportar_excel(resultado, caminho)

    esperado = tabela_sensibilidade(
        empresa_exemplo,
        ("wacc", grade(resultado.dcf.taxa_desconto, PASSO_DA_GRADE, PONTOS_DA_GRADE)),
        (
            "perpetuidade.crescimento_perpetuo",
            grade(
                empresa_exemplo.perpetuidade.crescimento_perpetuo,
                PASSO_DA_GRADE,
                PONTOS_DA_GRADE,
            ),
        ),
    )

    valores = _valores_calculados(caminho)
    ws = load_workbook(caminho)["Sensibilidade viva"]
    linha_cabecalho = _localizar_linha(ws, "WACC \\ g")
    for i in range(len(esperado)):
        for j in range(len(esperado.columns)):
            celula = f"{chr(ord('B') + j)}{linha_cabecalho + 1 + i}"
            obtido = _buscar(valores, "Sensibilidade viva", celula, caminho)
            assert obtido == pytest.approx(
                float(esperado.iat[i, j]), rel=1e-6
            ), f"{celula} ({esperado.index[i]} x {esperado.columns[j]})"


def test_o_resumo_e_a_primeira_aba_e_le_as_outras(empresa_exemplo, tmp_path):
    """Quem recebe um caderno de dez abas sem capa comeca pela aba errada."""
    from openpyxl import load_workbook

    resultado = avaliar(empresa_exemplo)
    caminho = tmp_path / "modelo_resumo.xlsx"
    exportar_excel(resultado, caminho)

    wb = load_workbook(caminho)
    assert wb.sheetnames[0] == "Resumo"

    valores = _valores_calculados(caminho)
    aba = wb["Resumo"]
    for rotulo, esperado in (
        ("Enterprise Value", resultado.dcf.enterprise_value),
        ("Equity Value", resultado.dcf.equity_value),
        ("WACC", resultado.custo_capital.wacc_brl),
    ):
        linha = _localizar_linha(aba, rotulo)
        obtido = _buscar(valores, "Resumo", f"B{linha}", caminho)
        assert obtido == pytest.approx(esperado, rel=1e-9), rotulo

    # E os graficos existem: o resumo e visual, nao mais uma tabela.
    assert len(aba._charts) == 2


def test_o_historico_e_o_diagnostico_entram_quando_existem(empresa_exemplo, tmp_path):
    """A planilha saia sem historico: a projecao chegava sem o que a compara."""
    import pandas as pd
    from openpyxl import load_workbook

    from valuation.diagnostico import diagnosticar
    from valuation.historico import analisar
    from valuation.importacao import Demonstracoes

    anos = [2023, 2024, 2025]
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": 1000.0 + 100 * i,
                "custo_produtos_vendidos": 600.0,
                "ebit": 200.0,
                "depreciacao_amortizacao": 50.0,
                "lucro_liquido": 120.0,
                "lucro_antes_impostos": 170.0,
                "impostos": 50.0,
                "ativo_total": 1500.0,
                "patrimonio_liquido": 700.0,
                "capex": 60.0,
            }
            for i, ano in enumerate(anos)
        }
    )
    analise = analisar(Demonstracoes(empresa="T", valores=valores, unidade="R$ mi"))
    # ROIC perpetuo de 40% garante achado: sem isto o modelo de exemplo passa
    # limpo, a aba sai com "nenhum achado" e o teste nao exercita a tabela.
    from valuation.modelo import substituir_varios

    resultado = avaliar(
        substituir_varios(empresa_exemplo, {"perpetuidade.roic_perpetuidade": 0.40})
    )
    caminho = tmp_path / "modelo_completo.xlsx"
    exportar_excel(
        resultado, caminho, analise=analise, diagnostico=diagnosticar(resultado, analise)
    )

    wb = load_workbook(caminho)
    assert "Historico" in wb.sheetnames
    assert "Diagnostico" in wb.sheetnames
    historico = wb["Historico"]
    assert _localizar_linha(historico, "receita_liquida")
    diagnostico = wb["Diagnostico"]
    assert diagnostico.cell(row=_localizar_linha(diagnostico, "Severidade"), column=2).value == "Achado"


def test_sem_historico_a_planilha_nao_inventa_a_aba(empresa_exemplo, tmp_path):
    from openpyxl import load_workbook

    caminho = tmp_path / "modelo_sem_historico.xlsx"
    exportar_excel(avaliar(empresa_exemplo), caminho)
    assert "Historico" not in load_workbook(caminho).sheetnames


def test_perpetuidade_por_multiplo_nao_ganha_grade_de_g(empresa_exemplo, tmp_path):
    """Com multiplo de saida o g nao entra na conta: a grade repetiria a coluna."""
    from dataclasses import replace

    from openpyxl import load_workbook

    empresa = replace(
        empresa_exemplo,
        perpetuidade=replace(
            empresa_exemplo.perpetuidade, metodo="multiplo", multiplo_saida=8.0
        ),
    )
    caminho = tmp_path / "modelo_multiplo.xlsx"
    exportar_excel(avaliar(empresa), caminho)
    assert "Sensibilidade viva" not in load_workbook(caminho).sheetnames

