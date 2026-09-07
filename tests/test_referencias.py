"""A base medida, e o que ela serve para dizer.

O modulo existe por causa de uma pergunta do dono do projeto: os cortes de
leitura sao absolutos ou contra pares? A resposta e os dois, e estes testes
guardam a parte que da para verificar -- que o percentil sai certo nas pontas,
no meio e fora da tabela, e que ele nunca extrapola.
"""

from __future__ import annotations

import numpy as np
import pytest

from valuation import referencias


def test_a_mediana_da_base_cai_no_percentil_50():
    _, valores = referencias.BASE["Conversao de caixa (FCO / EBITDA)"]
    mediana = valores[referencias.QUANTIS.index(0.50)]
    assert referencias.posicao("Conversao de caixa (FCO / EBITDA)", mediana) == pytest.approx(0.50)


def test_o_percentil_cresce_com_o_valor():
    indicador = "Margem EBITDA"
    anterior = -1.0
    for valor in (-0.5, 0.0, 0.10, 0.20, 0.50, 2.0):
        p = referencias.posicao(indicador, valor)
        assert p >= anterior
        anterior = p


def test_fora_da_tabela_nao_extrapola():
    """Cauda de distribuicao com margem de 300% nao se aproxima por reta."""
    assert referencias.posicao("Margem EBITDA", -50.0) == pytest.approx(0.05)
    assert referencias.posicao("Margem EBITDA", 50.0) == pytest.approx(0.95)


def test_indicador_desconhecido_e_valor_invalido_devolvem_ausencia():
    assert np.isnan(referencias.posicao("Indicador Inventado", 0.5))
    assert np.isnan(referencias.posicao("Margem EBITDA", float("nan")))
    assert referencias.descrever("Indicador Inventado", 0.5) == ""


def test_a_descricao_nomeia_as_pontas_em_vez_de_dar_percentil():
    assert "5% menores" in referencias.descrever("Margem EBITDA", -10.0)
    assert "5% maiores" in referencias.descrever("Margem EBITDA", 10.0)
    assert "percentil" in referencias.descrever("Margem EBITDA", 0.143)


def test_a_tabela_traz_o_n_de_cada_indicador():
    tabela = referencias.tabela()
    assert "n" in tabela.columns
    assert (tabela["n"] > 300).all(), "amostra pequena demais para servir de referencia"
    assert set(tabela.index) == set(referencias.BASE)


def test_gerar_referencias_reproduz_o_formato_do_modulo():
    """Refazer a medicao tem que ser um comando, nao trabalho manual."""
    import pandas as pd

    perfis = pd.DataFrame({"Margem EBITDA": np.linspace(0.0, 1.0, 101)})
    codigo = referencias.gerar_referencias(perfis)

    assert codigo.startswith("BASE: dict[str, tuple[int, tuple[float, ...]]] = {")
    assert '"Margem EBITDA": (101, (' in codigo
    # O bloco gerado tem que ser Python valido.
    ambiente: dict = {}
    exec(codigo.replace("BASE: dict[str, tuple[int, tuple[float, ...]]]", "BASE"), ambiente)
    assert ambiente["BASE"]["Margem EBITDA"][0] == 101


def test_a_qualidade_cita_a_posicao_na_base():
    """O sinal de conversao passa a dizer onde o numero cai no mercado."""
    from pathlib import Path

    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm
    from valuation.qualidade import avaliar_qualidade

    dados = Path(__file__).parent / "dados" / "cvm"
    analise = analisar(importar_cvm(5410, [2023, 2024], cache=dados))
    conversao = next(s for s in avaliar_qualidade(analise).sinais if s.codigo == "conversao")

    assert "percentil" in conversao.detalhe or "5%" in conversao.detalhe
    assert "companhias brasileiras" in conversao.detalhe


# ---------------------------------------------------------------------------
# A safra da medicao
# ---------------------------------------------------------------------------


def test_a_safra_acusa_quando_a_base_publicada_avancou():
    """``BASE`` é um instantâneo colado: não se atualiza quando sai DFP nova.

    Sem o aviso, o app cita percentis de uma safra antiga **com a mesma aparência
    de atual** — o pior tipo de número desatualizado é o que não se anuncia.
    """
    from valuation.referencias import SafraDaMedicao

    atrasada = SafraDaMedicao(ano_medido=2024, ano_mais_novo=2025, companhias=447)
    assert atrasada.desatualizada
    assert atrasada.exercicios_atras == 1
    assert "1 exercício atrás" in atrasada.resumo

    dois = SafraDaMedicao(ano_medido=2023, ano_mais_novo=2025, companhias=447)
    assert "2 exercícios atrás" in dois.resumo


def test_safra_em_dia_nao_vira_alarme():
    """Alarme que dispara sem motivo treina o leitor a ignorar."""
    from valuation.referencias import SafraDaMedicao

    em_dia = SafraDaMedicao(ano_medido=2025, ano_mais_novo=2025, companhias=447)
    assert not em_dia.desatualizada
    assert em_dia.exercicios_atras == 0
    assert "mais nova publicada" in em_dia.resumo


def test_sem_dfp_no_cache_nao_ha_o_que_afirmar(tmp_path):
    """Sem base local não dá para dizer que a medição envelheceu.

    Afirmar assim mesmo seria inventar — e quem nunca baixou nada também não tem
    com o que comparar.
    """
    from valuation.referencias import safra

    assert safra(cache=tmp_path) is None


def test_zip_vazio_nao_conta_como_exercicio_publicado(tmp_path):
    """Em janeiro o arquivo do exercício já existe e não tem companhia nenhuma.

    Contá-lo faria a tela anunciar atraso por um exercício que ainda não saiu —
    é a mesma armadilha de ``_itr_vazio``, e o custo de errar é o mesmo.
    """
    import zipfile

    from valuation.pares import _anos_de_dfp_no_cache

    for ano, conteudo in ((2024, "x" * 5000), (2025, "CNPJ_CIA;DT_REFER\n")):
        caminho = tmp_path / f"dfp_cia_aberta_{ano}.zip"
        with zipfile.ZipFile(caminho, "w") as zf:
            zf.writestr(f"dfp_cia_aberta_DRE_con_{ano}.csv", conteudo)

    assert _anos_de_dfp_no_cache(tmp_path) == [2024]


def test_todo_indicador_publicado_declara_a_unidade():
    """`BASE` mistura três unidades, e uma tabela que as junta não se lê.

    "Margem EBITDA 0,208" ao lado de "Ciclo 42,505" e de "Dívida líquida /
    EBITDA 2,024" pede que o leitor saiba de cabeça qual coluna é fração, qual é
    dia e qual é múltiplo — e quem sabe disso não precisa da tabela.

    A unidade é **declarada e não inferida do nome**. Inferir funcionaria hoje e
    quebraria calado no dia em que um indicador novo não seguisse a convenção;
    aqui ele entra sem unidade e este teste reprova.
    """
    from valuation import referencias

    faltando = sorted(i for i in referencias.BASE if i not in referencias.UNIDADES)
    assert not faltando, f"indicadores sem unidade declarada: {faltando}"

    orfas = sorted(i for i in referencias.UNIDADES if i not in referencias.BASE)
    assert not orfas, f"unidade declarada para indicador que BASE não publica: {orfas}"


def test_cada_unidade_se_escreve_do_seu_jeito():
    """Fração vira percentual, dia vira dia, razão vira múltiplo."""
    from valuation import referencias

    assert referencias.formatar("Margem EBITDA", 0.208) == "20,8%"
    assert referencias.formatar("Ciclo de conversao de caixa (dias)", 42.6) == "43 d"
    assert referencias.formatar("Divida liquida / EBITDA", 2.024) == "2,02x"
    # Indicador desconhecido nao inventa unidade: cai no multiplo, que e o
    # formato mais neutro dos tres.
    assert referencias.formatar("Coisa nova", 1.5) == "1,50x"


def test_as_duas_safras_se_chamam_do_mesmo_jeito():
    """`SafraDaMedicao.resumo` era método e `SafraDoUniverso.resumo`, propriedade.

    As duas dizem a mesma coisa sobre a mesma safra, e chamá-las de formas
    diferentes rendeu exatamente o defeito que rendeu: `safra.resumo` sem
    parênteses imprimiu `<bound method ...>` na tela, e não um aviso.
    """
    from valuation.pares import SafraDoUniverso
    from valuation.referencias import SafraDaMedicao

    for classe in (SafraDaMedicao, SafraDoUniverso):
        assert isinstance(
            classe.__dict__.get("resumo"), property
        ), f"{classe.__name__}.resumo precisa ser propriedade, como a irmã"


def test_nem_todo_indicador_atravessa_a_frequencia():
    """A base é medida em exercícios, e comparar um trimestre contra ela
    depende do indicador.

    Um indicador atravessa quando é **fluxo sobre fluxo do mesmo período**
    (margem, conversão) ou **estoque sobre estoque** (liquidez, dívida/PL). Não
    atravessa quando mistura fluxo do período com estoque — o denominador anual
    encolhe a um quarto e a razão quadruplica —, quando é variação de um período
    contra outro, ou quando o numerador é irregular dentro do ano.

    Medido na WEG e em mais duas, o desvio médio do percentil entre a leitura
    anual e a trimestral separa os grupos com um vale no meio: ROIC 44, ROE 36,
    Crescimento 33 · **vale** · Capex/Receita 9, Liquidez 7, Margens 0-1.

    A classificação é **por estrutura e não pelo desvio**: o desvio confirma, e
    usá-lo como critério faria a lista mudar com a amostra.
    """
    from valuation import referencias

    for estrutural in ("ROIC", "ROE", "Crescimento da receita", "Divida liquida / EBITDA"):
        assert not referencias.atravessa_a_frequencia(estrutural), estrutural

    # A conversao de **caixa** ficou fora: o FCO de um trimestre carrega imposto
    # e juro pagos, que sao irregulares dentro do ano -- o mesmo criterio do
    # payout. A **operacional** fica, porque o CGO e antes dos dois. Medido em 79
    # companhias: 18 pontos de desvio contra 11.
    assert not referencias.atravessa_a_frequencia("Conversao de caixa (FCO / EBITDA)")

    for atravessa in (
        "Margem EBITDA",
        "Margem liquida",
        "Liquidez corrente",
        "Capex / Receita",
        "Ciclo de conversao de caixa (dias)",
        "Divida bruta / Patrimonio liquido",
        "Conversao operacional (CGO / EBITDA)",
    ):
        assert referencias.atravessa_a_frequencia(atravessa), atravessa

    orfaos = sorted(i for i in referencias.SO_NO_EXERCICIO if i not in referencias.BASE)
    assert not orfaos, f"indicador listado que BASE não publica: {orfaos}"
