"""Premissas macro de longo prazo e a ancora do crescimento perpetuo.

Duas coisas sao testadas aqui, e a segunda e a que justifica o modulo.

A primeira e aritmetica: o crescimento nominal da economia compoe inflacao com
PIB real, nao soma. A segunda e um invariante -- quando o ``g`` esta ancorado,
ele **deixa de ser entrada**. Estressar a macro tem que move-lo junto, e um
lugar so que continuasse lendo o valor guardado poria um numero errado na tela.

Ha ainda o caso que nao pode virar armadilha: mexer no ``g`` na mao, com a
ancora ligada, precisa soltar a ancora. Sem isso, uma tabela de sensibilidade
sobre o ``g`` sairia inteira igual, sem erro nenhum que explicasse por que.
"""

from __future__ import annotations

import pytest

from valuation import avaliar, substituir, substituir_varios, tabela_sensibilidade
from valuation.diagnostico import diagnosticar
from valuation.premissas import Empresa, PremissasMacro, PremissasPerpetuidade
from valuation.projeto import Projeto, desserializar, serializar


# ---------------------------------------------------------------------------
# O crescimento nominal da economia
# ---------------------------------------------------------------------------


def test_pib_nominal_compoe_em_vez_de_somar():
    macro = PremissasMacro(inflacao_brl=0.05, pib_real=0.015)
    # 1,05 x 1,015 - 1 = 6,575%, e nao os 6,5% da soma.
    assert macro.pib_nominal == pytest.approx(0.06575)
    assert macro.pib_nominal > macro.inflacao_brl + macro.pib_real


def test_pib_real_negativo_e_aceito_e_percentual_e_recusado():
    assert PremissasMacro(pib_real=-0.01).pib_nominal < PremissasMacro().inflacao_brl
    with pytest.raises(ValueError, match="pib_real"):
        PremissasMacro(pib_real=1.5)


# ---------------------------------------------------------------------------
# A ancora
# ---------------------------------------------------------------------------


def test_ancora_desconhecida_e_recusada():
    with pytest.raises(ValueError, match="ancora"):
        PremissasPerpetuidade(ancora="pib")


def test_ancorado_o_g_vem_da_macro_e_nao_do_campo(empresa_exemplo):
    """O valor guardado no campo perde para a ancora, sem alarde e sem erro."""
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.ancora": "ipca", "perpetuidade.crescimento_perpetuo": 0.09},
    )
    assert empresa.perpetuidade.crescimento_perpetuo == pytest.approx(
        empresa.macro.inflacao_brl
    )


def test_estressar_a_macro_move_o_g_junto(empresa_exemplo):
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    antes = ancorada.perpetuidade.crescimento_perpetuo
    assert antes == pytest.approx(ancorada.macro.pib_nominal)

    estressada = substituir(ancorada, "macro.inflacao_brl", 0.07)
    assert estressada.perpetuidade.crescimento_perpetuo == pytest.approx(
        estressada.macro.pib_nominal
    )
    assert estressada.perpetuidade.crescimento_perpetuo > antes


def test_pib_real_so_move_o_g_quando_a_ancora_e_o_pib(empresa_exemplo):
    por_ipca = substituir(empresa_exemplo, "perpetuidade.ancora", "ipca")
    depois = substituir(por_ipca, "macro.pib_real", 0.005)
    assert depois.perpetuidade.crescimento_perpetuo == pytest.approx(
        depois.macro.inflacao_brl
    ), "ancorado em IPCA, o PIB real nao tem por que entrar"

    por_pib = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    fraco = substituir(por_pib, "macro.pib_real", 0.005)
    assert fraco.perpetuidade.crescimento_perpetuo < por_pib.perpetuidade.crescimento_perpetuo


def test_g_livre_e_o_padrao_e_nada_o_move(empresa_exemplo):
    """Quem nao ancorou nao pode ter o modelo mudando debaixo dele."""
    assert empresa_exemplo.perpetuidade.ancora == "livre"
    depois = substituir(empresa_exemplo, "macro.inflacao_brl", 0.09)
    assert depois.perpetuidade.crescimento_perpetuo == pytest.approx(
        empresa_exemplo.perpetuidade.crescimento_perpetuo
    )


# ---------------------------------------------------------------------------
# Soltar a ancora, para a sensibilidade nao mentir
# ---------------------------------------------------------------------------


def test_mexer_no_g_na_mao_solta_a_ancora(empresa_exemplo):
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "ipca")
    solta = substituir(ancorada, "perpetuidade.crescimento_perpetuo", 0.02)

    assert solta.perpetuidade.ancora == "livre"
    assert solta.perpetuidade.crescimento_perpetuo == pytest.approx(0.02)


def test_ancora_informada_junto_do_g_continua_mandando(empresa_exemplo):
    """Quem passa a ancora explicitamente esta dizendo o que quer."""
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.crescimento_perpetuo": 0.02, "perpetuidade.ancora": "ipca"},
    )
    assert empresa.perpetuidade.ancora == "ipca"
    assert empresa.perpetuidade.crescimento_perpetuo == pytest.approx(
        empresa.macro.inflacao_brl
    )


def test_sensibilidade_sobre_o_g_ancorado_nao_sai_achatada(empresa_exemplo):
    """A regressao que a regra de soltar a ancora existe para impedir."""
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    tabela = tabela_sensibilidade(
        ancorada,
        ("perpetuidade.crescimento_perpetuo", [0.02, 0.03, 0.04]),
        ("wacc", [0.11, 0.12]),
    )
    assert tabela.iloc[:, 0].nunique() == 3, "cada g tinha que dar um valor diferente"


# ---------------------------------------------------------------------------
# O efeito que engana
# ---------------------------------------------------------------------------


def _efeito_da_inflacao(empresa: Empresa, choque: float = 0.02) -> float:
    base = avaliar(empresa).equity_value
    depois = avaliar(
        substituir(empresa, "macro.inflacao_brl", empresa.macro.inflacao_brl + choque)
    ).equity_value
    return (depois - base) / base


def test_com_o_g_parado_inflacao_maior_e_so_desconto_maior(empresa_exemplo):
    """O unico sinal que da para afirmar em geral.

    Nao ha teste aqui dizendo que ancorar o ``g`` **amortece** o choque, porque
    isso nao e verdade em geral: medido, a empresa alavancada do fixture melhora
    (-56,5% para -47,5%) e a WEG, com caixa liquido, piora (-17,9% para -19,9%).
    O sinal depende da alavancagem e do reinvestimento normalizado. Quem quiser
    saber roda o estresse na tela, que mede em vez de supor.
    """
    assert _efeito_da_inflacao(empresa_exemplo) < 0


def test_sem_normalizar_reinvestimento_a_ancora_quase_cancela_a_inflacao(empresa_exemplo):
    """O caso em que o efeito de fato some -- e e so este caso.

    Sem normalizacao, o fluxo perpetuo apenas cresce a ``g``. Subir a inflacao
    sobe o desconto e o ``g`` quase na mesma proporcao, e o que sobra e residual.
    """
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.ancora": "pib_nominal", "perpetuidade.roic_perpetuidade": None},
    )
    assert abs(_efeito_da_inflacao(empresa)) < 0.05


def test_com_reinvestimento_normalizado_a_inflacao_continua_cara(empresa_exemplo):
    """O achado que desmente a leitura simples de "inflacao e neutra".

    Com ``roic_perpetuidade`` ligado, o fluxo perpetuo e
    ``NOPAT x (1 + g) x (1 - g / ROIC)``. Ancorar o ``g`` na macro sobe o ``g``
    nominal, mas o ROIC fica onde estava -- entao a taxa de reinvestimento
    ``g / ROIC`` sobe junto, e come mais NOPAT do que o spread devolve.

    Nao e defeito da ancora: e o modelo cobrando capital para sustentar
    crescimento nominal maior. Mas quem esperava neutralidade precisa ver isto,
    porque a queda nao e pequena.
    """
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    sem_normalizar = substituir(ancorada, "perpetuidade.roic_perpetuidade", None)

    com = _efeito_da_inflacao(ancorada)
    sem = _efeito_da_inflacao(sem_normalizar)

    assert com < sem, "normalizar o reinvestimento agrava o choque, nao alivia"
    assert com < -0.10, "e a diferenca nao e de segunda ordem"

    roic = ancorada.perpetuidade.roic_perpetuidade
    antes = ancorada.perpetuidade.crescimento_perpetuo / roic
    depois = (
        substituir(ancorada, "macro.inflacao_brl", ancorada.macro.inflacao_brl + 0.02)
        .perpetuidade.crescimento_perpetuo
        / roic
    )
    assert depois > antes, "a taxa de reinvestimento sobe com a inflacao"


@pytest.mark.parametrize("metodo", ["usd", "local"])
def test_risco_pais_aperta_o_desconto_sem_contrapartida_no_crescimento(
    empresa_exemplo, metodo
):
    """O que distingue os dois estresses macro -- e vale para toda empresa.

    A magnitude relativa nao vale: na WEG o choque de IPCA chega a bater mais
    que o de risco-pais. O que e sempre verdade e o mecanismo -- risco-pais so
    entra no desconto, enquanto a inflacao, ancorada, entra tambem no fluxo.
    """
    # **O prêmio de risco que se estressa depende do caminho que monta o Ke.**
    # No caminho em dólar é o risco-país; no local ele já está dentro da NTN-B, e
    # quem sobra é o prêmio de ações local. O mecanismo que este teste afirma é o
    # mesmo nos dois -- prêmio de risco entra só no desconto --, mas a alavanca
    # não é.
    ancorada = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.ancora": "pib_nominal", "custo_capital.metodo": metodo},
    )
    caminho = (
        "custo_capital.risco_pais"
        if metodo == "usd"
        else "custo_capital.erp_local"
    )
    g_base = ancorada.perpetuidade.crescimento_perpetuo
    wacc_base = avaliar(ancorada).dcf.taxa_desconto

    atual = getattr(ancorada.custo_capital, caminho.split(".")[-1])
    por_risco = substituir(ancorada, caminho, atual + 0.02)
    assert avaliar(por_risco).dcf.taxa_desconto > wacc_base
    assert por_risco.perpetuidade.crescimento_perpetuo == pytest.approx(g_base)

    por_inflacao = substituir(
        ancorada, "macro.inflacao_brl", ancorada.macro.inflacao_brl + 0.02
    )
    assert avaliar(por_inflacao).dcf.taxa_desconto > wacc_base
    assert por_inflacao.perpetuidade.crescimento_perpetuo > g_base


# ---------------------------------------------------------------------------
# Quem le a macro
# ---------------------------------------------------------------------------


def test_o_teto_do_diagnostico_segue_a_macro(empresa_exemplo):
    """Antes o teto era inflacao + 2% fixos, e ignorava quem estressou o PIB."""
    empresa = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.crescimento_perpetuo": 0.058, "macro.pib_real": 0.005},
    )
    codigos = {a.codigo for a in diagnosticar(avaliar(empresa)).achados}
    assert "g_acima_da_economia" in codigos

    com_pib_forte = substituir(empresa, "macro.pib_real", 0.03)
    codigos = {a.codigo for a in diagnosticar(avaliar(com_pib_forte)).achados}
    assert "g_acima_da_economia" not in codigos


def test_ancorar_no_pib_nominal_nunca_estoura_o_teto(empresa_exemplo):
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    codigos = {a.codigo for a in diagnosticar(avaliar(ancorada)).achados}
    assert "g_acima_da_economia" not in codigos


def test_ancora_e_pib_real_sobrevivem_ao_arquivo_salvo(empresa_exemplo):
    ancorada = substituir_varios(
        empresa_exemplo,
        {"perpetuidade.ancora": "pib_nominal", "macro.pib_real": 0.012},
    )
    voltou = desserializar(serializar(Projeto(empresa=ancorada))).empresa

    assert voltou.perpetuidade.ancora == "pib_nominal"
    assert voltou.macro.pib_real == pytest.approx(0.012)
    assert voltou.perpetuidade.crescimento_perpetuo == pytest.approx(
        ancorada.perpetuidade.crescimento_perpetuo
    )


# ---------------------------------------------------------------------------
# O ROIC do outro lado da conta
# ---------------------------------------------------------------------------


def test_roic_real_deriva_o_nominal_pela_inflacao(empresa_exemplo):
    real = (1 + 0.15) / (1 + empresa_exemplo.macro.inflacao_brl) - 1
    empresa = substituir(empresa_exemplo, "perpetuidade.roic_real", real)
    assert empresa.perpetuidade.roic_perpetuidade == pytest.approx(0.15)


def test_indexar_o_roic_nao_muda_o_valor_de_hoje(empresa_exemplo):
    """A promessa que a tela faz e que precisa ser verdade.

    Se marcar a caixa reprecificasse a empresa, ninguem marcaria -- e com razao.
    """
    nominal = empresa_exemplo.perpetuidade.roic_perpetuidade
    real = (1 + nominal) / (1 + empresa_exemplo.macro.inflacao_brl) - 1
    indexada = substituir(empresa_exemplo, "perpetuidade.roic_real", real)

    assert avaliar(indexada).equity_value == pytest.approx(
        avaliar(empresa_exemplo).equity_value
    )


def test_roic_indexado_segura_o_reinvestimento_sem_zera_lo(empresa_exemplo):
    """Indexar corrige o exagero, nao o efeito.

    Sustentar o mesmo crescimento real custa mais reais nominais quando os
    precos correm mais rapido. O reinvestimento tem que continuar subindo com a
    inflacao -- so que menos.
    """
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    real = (1 + ancorada.perpetuidade.roic_perpetuidade) / (
        1 + ancorada.macro.inflacao_brl
    ) - 1
    indexada = substituir(ancorada, "perpetuidade.roic_real", real)

    def reinvestimento(empresa, ipca=None):
        if ipca is not None:
            empresa = substituir(empresa, "macro.inflacao_brl", ipca)
        perp = empresa.perpetuidade
        return perp.crescimento_perpetuo / perp.roic_perpetuidade

    ipca_alto = ancorada.macro.inflacao_brl + 0.02
    fixo = reinvestimento(ancorada, ipca_alto)
    indexado = reinvestimento(indexada, ipca_alto)
    base = reinvestimento(ancorada)

    assert base < indexado < fixo
    assert _efeito_da_inflacao(indexada) > _efeito_da_inflacao(ancorada)


def test_mexer_no_roic_nominal_na_mao_solta_a_indexacao(empresa_exemplo):
    indexada = substituir(empresa_exemplo, "perpetuidade.roic_real", 0.10)
    solta = substituir(indexada, "perpetuidade.roic_perpetuidade", 0.18)

    assert solta.perpetuidade.roic_real is None
    assert solta.perpetuidade.roic_perpetuidade == pytest.approx(0.18)


def test_desligar_a_normalizacao_leva_a_indexacao_junto(empresa_exemplo):
    indexada = substituir(empresa_exemplo, "perpetuidade.roic_real", 0.10)
    desligada = substituir(indexada, "perpetuidade.roic_perpetuidade", None)

    assert desligada.perpetuidade.roic_real is None
    assert desligada.perpetuidade.roic_perpetuidade is None


def test_o_diagnostico_avisa_quando_a_combinacao_exagera(empresa_exemplo):
    ancorada = substituir(empresa_exemplo, "perpetuidade.ancora", "pib_nominal")
    codigos = {a.codigo for a in diagnosticar(avaliar(ancorada)).achados}
    assert "reinvestimento_nao_indexado" in codigos

    real = (1 + ancorada.perpetuidade.roic_perpetuidade) / (
        1 + ancorada.macro.inflacao_brl
    ) - 1
    indexada = substituir(ancorada, "perpetuidade.roic_real", real)
    codigos = {a.codigo for a in diagnosticar(avaliar(indexada)).achados}
    assert "reinvestimento_nao_indexado" not in codigos


def test_sem_ancora_o_aviso_de_indexacao_nao_aparece(empresa_exemplo):
    """Quem nao ancorou nao tem o problema, e nao precisa do recado."""
    codigos = {a.codigo for a in diagnosticar(avaliar(empresa_exemplo)).achados}
    assert "reinvestimento_nao_indexado" not in codigos
