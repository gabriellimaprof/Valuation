"""O relatorio estruturado.

O risco de um documento gerado por maquina nao e errar uma conta -- as contas
vem de modulos que ja tem teste. E **parecer mais completo do que e**: sair
bonito, sem historico importado e sem preco, e o leitor supor que aquilo foi
verificado. Por isso os testes daqui olham tanto para o que o texto afirma
quanto para o que ele confessa nao ter feito.
"""

from __future__ import annotations

import pytest

from valuation import avaliar, substituir, substituir_varios
from valuation.diagnostico import diagnosticar
from valuation.margem import expectativas_implicitas, margem_de_seguranca
from valuation.relatorio import montar, sumario


@pytest.fixture
def resultado(empresa_exemplo):
    return avaliar(empresa_exemplo)


# ---------------------------------------------------------------------------
# O minimo
# ---------------------------------------------------------------------------


def test_o_relatorio_sai_so_com_o_valuation(resultado):
    texto = montar(resultado)
    assert texto.startswith("# Teste S.A.")
    for secao in (
        "## Resumo",
        "## O que a empresa entregou",
        "## O que o modelo assume",
        "## Do Enterprise Value ao Equity Value",
        "## O que o preço embute",
        "## O que pode dar errado",
        "## O que este relatório não faz",
    ):
        assert secao in texto, f"faltou {secao}"


def test_os_numeros_saem_no_padrao_brasileiro(resultado):
    texto = montar(resultado)
    assert "%" in texto
    # Percentual com virgula decimal, nunca com ponto.
    import re

    percentuais = re.findall(r"\d+[.,]\d+%", texto)
    assert percentuais
    assert all("," in p for p in percentuais), f"percentual com ponto: {percentuais}"


def test_a_ponte_do_relatorio_bate_com_a_do_modelo(resultado):
    texto = montar(resultado)
    ponte = resultado.tabela_ponte()
    assert "Enterprise Value" in texto
    # Todos os itens da ponte precisam aparecer: um sumico silencioso aqui
    # esconderia divida ou minoritarios do leitor.
    for item in ponte.index:
        assert str(item) in texto, f"a ponte perdeu {item}"


# ---------------------------------------------------------------------------
# O que ele confessa
# ---------------------------------------------------------------------------


def test_sem_historico_o_relatorio_diz_que_nao_verificou(resultado):
    texto = montar(resultado)
    assert "**Não avaliado.**" in texto
    assert "Sem histórico importado" in texto


def test_sem_preco_o_relatorio_nao_finge_avaliar_oportunidade(resultado):
    texto = montar(resultado)
    assert "calcula valor e não avalia oportunidade" in texto
    assert "nenhum preço de mercado foi informado" in texto.lower()


def test_a_secao_de_limites_esta_sempre_presente(resultado):
    """A secao que impede o documento de parecer mais do que e."""
    texto = montar(resultado)
    assert "Não avalia o negócio" in texto
    assert "Não valida as premissas" in texto
    assert "convenção" in texto


def test_perpetuidade_pesada_aparece_nos_limites(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    if resultado.dcf.peso_perpetuidade > 0.75:
        assert "do valor está na perpetuidade" in montar(resultado)


def test_sem_normalizacao_o_relatorio_avisa(empresa_exemplo):
    sem = substituir(empresa_exemplo, "perpetuidade.roic_perpetuidade", None)
    texto = montar(avaliar(sem))
    assert "não normalizado" in texto
    assert "superestimar o valor terminal" in texto


# ---------------------------------------------------------------------------
# Com as pecas todas
# ---------------------------------------------------------------------------


def test_com_preco_o_relatorio_traz_margem_e_expectativas(empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    preco = resultado.equity_value * 0.8
    margem = margem_de_seguranca(resultado.equity_value, preco)
    texto = montar(
        resultado,
        margem=margem,
        expectativas=expectativas_implicitas(empresa_exemplo, preco),
        diagnostico=diagnosticar(resultado),
    )

    assert "Margem EBITDA" in texto
    assert "Implícita no preço" in texto
    assert "preço máximo para manter" in texto
    assert "premissa com menos folga" in texto


def test_a_ancora_do_g_aparece_explicada(empresa_exemplo):
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    texto = montar(avaliar(ancorada))
    assert "ancorado no PIB nominal" in texto
    assert "composto com PIB real" in texto


def test_o_relatorio_conta_observacoes_junto_dos_alertas(empresa_exemplo):
    """A contagem nao pode dizer "0 e 0" logo acima de dois achados listados."""
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    resultado = avaliar(ancorada)
    diag = diagnosticar(resultado)
    texto = montar(resultado, diagnostico=diag)

    assert "observação(ões)" in texto
    quantos = len(diag.achados) - len(diag.erros) - len(diag.alertas)
    assert f"{quantos} observação(ões)" in texto


def test_diagnostico_limpo_nao_vira_aprovacao(empresa_exemplo):
    """Consistente nao e o mesmo que certo, e o texto precisa dizer isso."""
    from valuation.diagnostico import Diagnostico

    texto = montar(avaliar(empresa_exemplo), diagnostico=Diagnostico(achados=[]))
    assert "não que as premissas estejam" in texto


def test_o_sumario_prioriza_erro_sobre_alerta(empresa_exemplo):
    from valuation.diagnostico import ALERTA, ERRO, Achado, Diagnostico

    erro = Achado(codigo="x", severidade=ERRO, titulo="t", detalhe="d")
    alerta = Achado(codigo="y", severidade=ALERTA, titulo="t", detalhe="d")

    assert "erro" in sumario(Diagnostico(achados=[erro, alerta]))
    assert "alerta" in sumario(Diagnostico(achados=[alerta]))
    assert "consistente" in sumario(Diagnostico(achados=[]))
    assert "não executado" in sumario(None)


# ---------------------------------------------------------------------------
# Com dados reais
# ---------------------------------------------------------------------------


def test_relatorio_completo_de_uma_companhia_de_verdade():
    """Ponta a ponta: CVM -> historico -> premissas -> valuation -> relatorio."""
    from dataclasses import replace
    from pathlib import Path

    from valuation.historico import analisar, sugerir_premissas
    from valuation.importacao.cvm import importar_cvm
    from valuation.premissas import Empresa, PremissasMacro, PremissasPerpetuidade
    from valuation.qualidade import avaliar_qualidade

    dados = Path(__file__).parent / "dados" / "cvm"
    dfs = importar_cvm(5410, [2023, 2024], cache=dados).escalar(1e6, "R$ milhões")
    analise = analisar(dfs)
    sugestao = sugerir_premissas(analise, horizonte=5)

    empresa = Empresa(
        nome="WEG S.A.",
        macro=PremissasMacro(inflacao_brl=0.05, pib_real=0.015),
        operacionais=sugestao.operacionais,
        ponte=sugestao.ponte,
        custo_capital=replace(sugestao.custo_capital, beta_alavancado_setor=1.0),
        perpetuidade=PremissasPerpetuidade(ancora="pib_nominal", roic_perpetuidade=0.15),
        unidade="R$ milhões",
    )
    resultado = avaliar(empresa)
    preco = resultado.equity_value * 0.8

    texto = montar(
        resultado,
        analise=analise,
        qualidade=avaliar_qualidade(analise),
        diagnostico=diagnosticar(resultado, analise=analise),
        margem=margem_de_seguranca(resultado.equity_value, preco),
        expectativas=expectativas_implicitas(empresa, preco),
    )

    assert "WEG S.A." in texto
    assert "Período apurado: 2023 a 2024" in texto
    assert "Veredito:" in texto
    # Nenhuma secao pode ter ficado sem conteudo.
    assert "**Não avaliado" not in texto
    assert len(texto) > 3000


def test_o_relatorio_completo_traz_a_secao_qualitativa():
    """Ponta a ponta com todas as pecas, inclusive as perguntas em branco."""
    from dataclasses import replace
    from pathlib import Path

    from valuation.historico import analisar, sugerir_premissas
    from valuation.importacao.cvm import importar_cvm
    from valuation.premissas import Empresa, PremissasMacro, PremissasPerpetuidade
    from valuation.qualidade import avaliar_qualidade
    from valuation.qualitativo import reunir_evidencias

    dados = Path(__file__).parent / "dados" / "cvm"
    dfs = importar_cvm(5410, [2023, 2024], cache=dados).escalar(1e6, "R$ milhões")
    analise = analisar(dfs)
    sugestao = sugerir_premissas(analise, horizonte=5)

    empresa = Empresa(
        nome="WEG S.A.",
        macro=PremissasMacro(inflacao_brl=0.05, pib_real=0.015),
        operacionais=sugestao.operacionais,
        ponte=sugestao.ponte,
        custo_capital=replace(sugestao.custo_capital, beta_alavancado_setor=1.0),
        perpetuidade=PremissasPerpetuidade(ancora="pib_nominal", roic_perpetuidade=0.15),
        unidade="R$ milhões",
    )
    resultado = avaliar(empresa)
    preco = resultado.equity_value * 0.8

    texto = montar(
        resultado,
        analise=analise,
        qualidade=avaliar_qualidade(analise),
        diagnostico=diagnosticar(resultado, analise=analise),
        margem=margem_de_seguranca(resultado.equity_value, preco),
        expectativas=expectativas_implicitas(empresa, preco),
        evidencias=reunir_evidencias(analise, resultado),
    )

    # As oito secoes, na ordem em que se lem.
    ordem = [
        "# WEG S.A.",
        "## Resumo",
        "## O que a empresa entregou",
        "## Qualidade dos lucros",
        "## O que o modelo assume",
        "## Do Enterprise Value ao Equity Value",
        "## O que o preço embute",
        "## As perguntas que os números não respondem",
        "## O que pode dar errado",
        "## O que este relatório não faz",
    ]
    posicoes = [texto.index(secao) for secao in ordem]
    assert posicoes == sorted(posicoes), "as seções sairam fora de ordem"

    # A secao qualitativa reune evidencia e nao conclui.
    assert texto.count("**Leitura do analista:**") == 6
    assert "Nenhuma evidência quantitativa" in texto


# ---------------------------------------------------------------------------
# A ponte do caixa no relatorio
# ---------------------------------------------------------------------------


def test_a_ponte_do_caixa_entra_no_relatorio(empresa_exemplo, tmp_path):
    """O relatorio e o que sobra depois que a tela fecha.

    Sem a ponte, quem le em tres meses ve "converte 34%" e refaz do zero a
    pergunta que a tela ja tinha respondido: **onde** o caixa se perdeu.
    """
    from pathlib import Path

    from valuation import avaliar
    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm
    from valuation.qualidade import avaliar_qualidade
    from valuation.relatorio import montar

    dados = Path(__file__).parent / "dados" / "cvm"
    weg = importar_cvm(5410, [2023, 2024], cache=dados).escalar(1e6, "R$ milhões")
    analise = analisar(weg)

    texto = montar(
        avaliar(empresa_exemplo),
        analise=analise,
        qualidade=avaliar_qualidade(analise),
    )
    assert "De EBITDA a caixa" in texto
    assert "Caixa gerado pelas operações" in texto
    assert "a ponte fecha com o FCO publicado" in texto


def test_sem_dfc_indireta_a_ponte_fica_de_fora(empresa_exemplo):
    """Tabela que nao reconstroi o FCO descreveria outra companhia.

    Companhia que publica a DFC pelo metodo direto nao tem caixa gerado pelas
    operacoes -- a demonstracao dela nao reconcilia lucro com caixa, ela lista
    recebimentos e pagamentos. Inventar a ponte ali seria pior que a ausencia.
    """
    from valuation import avaliar
    from valuation.relatorio import _ponte_do_caixa

    assert _ponte_do_caixa(None) == []
    # E o relatorio inteiro continua saindo sem ela.
    texto = montar(avaliar(empresa_exemplo))
    assert "De EBITDA a caixa" not in texto


# ---------------------------------------------------------------------------
# O relatorio descreve a construcao que foi usada
# ---------------------------------------------------------------------------


def test_o_relatorio_descreve_o_caminho_local(empresa_exemplo):
    """Ele escrevia sempre a soma em dolar.

    Com o caminho local escolhido, o leitor via uma conta com risco-pais que o
    modelo nao fez -- e cujos numeros nao somavam o Ke mostrado logo abaixo.
    """
    texto = montar(avaliar(empresa_exemplo))
    assert "NTN-B nominalizada" in texto
    assert "prêmio de risco local" in texto
    assert "Não há termo de risco-país" in texto
    assert "Ke em USD" not in texto


def test_o_relatorio_descreve_o_caminho_em_dolar_quando_e_ele(empresa_exemplo):
    em_dolar = substituir(empresa_exemplo, "custo_capital.metodo", "usd")
    texto = montar(avaliar(em_dolar))
    assert "Ke em USD" in texto
    assert "risco-país)" in texto
    assert "NTN-B" not in texto
