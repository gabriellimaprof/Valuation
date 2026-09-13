"""Reconhecer um banco, e derivar do histórico dele o que o modelo pede.

O app precisa saber que a companhia é instituição financeira **antes** de
mostrar um número, porque o caminho de FCFF/WACC não se aplica a ela. E as
premissas que ela pede são outras: não há margem EBITDA nem capex sobre receita
num banco, há retorno sobre patrimônio e quanto dele fica retido.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation.bancos import (
    e_instituicao_financeira,
    ler_historico,
    sugerir_premissas_do_banco,
)
from valuation.importacao import Demonstracoes
from valuation.importacao.cvm import importar_cvm
from valuation.lucro_residual import avaliar_lucro_residual

DADOS = Path(__file__).parent / "dados" / "cvm"


def _banco(**contas) -> Demonstracoes:
    """Um banco de brinquedo, com clean surplus fechando por construção."""
    anos = [2022, 2023, 2024]
    base = {
        "patrimonio_liquido": [1000.0, 1100.0, 1210.0],
        "lucro_liquido": [180.0, 198.0, 217.8],
        "dividendos_pagos": [-80.0, -88.0, -96.8],
    }
    base.update(contas)
    return Demonstracoes(
        empresa="Banco Teste",
        valores=pd.DataFrame(base, index=anos).T,
        avisos=["Esta companhia publica no plano de contas de instituicao financeira."],
    )


# ---------------------------------------------------------------------------
# Reconhecer
# ---------------------------------------------------------------------------


def test_o_aviso_do_importador_e_o_que_identifica_o_banco():
    """A informação é sobre a **origem**, e não sobre uma conta.

    Ela não sobrevive no vocabulário canônico — não há conta "é banco" —, então
    viaja no aviso que o leitor da CVM emite ao detectar o plano de contas.
    """
    assert e_instituicao_financeira(_banco())


def test_industria_nao_e_confundida_com_banco(catalogo=None):
    weg = importar_cvm(5410, [2024], cache=DADOS)
    assert not e_instituicao_financeira(weg)


# ---------------------------------------------------------------------------
# O que se le do passado
# ---------------------------------------------------------------------------


def test_o_roe_sai_sobre_o_patrimonio_medio():
    """Como o CFA manda, e como o resto do app já calcula ROIC.

    Sobre o patrimônio final, um banco que capitalizou no meio do ano apareceria
    menos rentável do que foi.
    """
    historico = ler_historico(_banco())
    # 2023: 198 / ((1000 + 1100) / 2) = 18,86%
    assert float(historico.roe[2023]) == pytest.approx(198.0 / 1050.0)
    # O primeiro ano não tem abertura, então não tem ROE.
    assert not np.isfinite(historico.roe[2022])


def test_o_payout_sai_dos_dividendos_pagos_da_dfc():
    historico = ler_historico(_banco())
    assert float(historico.payout[2023]) == pytest.approx(88.0 / 198.0)


def test_payout_nao_passa_de_cem_por_cento():
    """Distribuir reserva de anos anteriores é possível, e não é payout do ano.

    Deixar passar de 100% faria o patrimônio projetado encolher por uma conta que
    descreve o passado, e não a política.
    """
    historico = ler_historico(_banco(dividendos_pagos=[-80.0, -400.0, -96.8]))
    assert float(historico.payout[2023]) == pytest.approx(1.0)


def test_prejuizo_nao_vira_payout_negativo():
    """Dividendo sobre lucro negativo não quer dizer nada."""
    historico = ler_historico(_banco(lucro_liquido=[180.0, -50.0, 217.8]))
    assert not np.isfinite(historico.payout[2023])


# ---------------------------------------------------------------------------
# A sugestao
# ---------------------------------------------------------------------------


def test_a_sugestao_parte_do_patrimonio_do_ultimo_ano():
    sugestao = sugerir_premissas_do_banco(_banco())
    assert sugestao.premissas.patrimonio_inicial == pytest.approx(1210.0)


def test_o_roe_sugerido_e_a_mediana_historica():
    sugestao = sugerir_premissas_do_banco(_banco())
    historico = ler_historico(_banco())
    assert sugestao.premissas.roe[0] == pytest.approx(historico.roe_mediano)
    assert "roe" in sugestao.justificativas


def test_o_roe_perpetuo_nasce_igual_ao_ke():
    """Não é omissão: é afirmar que a vantagem não sobrevive para sempre.

    É o parâmetro que mais move o valor terminal, e a hipótese conservadora é o
    padrão da literatura para instituição madura. Quem quiser afirmar vantagem
    perpétua digita.
    """
    sugestao = sugerir_premissas_do_banco(_banco())
    assert sugestao.premissas.roe_perpetuo is None
    assert "roe_perpetuo" in sugestao.justificativas

    resultado = avaliar_lucro_residual(sugestao.premissas, ke=0.145)
    assert resultado.valor_presente_terminal == pytest.approx(0.0, abs=1e-9)


def test_o_capital_regulatorio_e_declarado_como_ausente():
    """O que o modelo não faz precisa estar escrito onde ele é usado.

    Crescimento alto com payout alto pode ser inviável por Basileia sem que a
    aritmética reclame.
    """
    sugestao = sugerir_premissas_do_banco(_banco())
    assert any("capital regulatorio" in a for a in sugestao.alertas)


def test_historico_curto_vira_alerta():
    """Mediana de dois números é a média deles, e não descreve a instituição."""
    curto = Demonstracoes(
        empresa="Banco Novo",
        valores=pd.DataFrame(
            {
                "patrimonio_liquido": [1000.0, 1100.0],
                "lucro_liquido": [180.0, 198.0],
                "dividendos_pagos": [-80.0, -88.0],
            },
            index=[2023, 2024],
        ).T,
        avisos=["plano de contas de instituicao financeira"],
    )
    sugestao = sugerir_premissas_do_banco(curto)
    assert any("exercicios" in a for a in sugestao.alertas)


def test_sem_patrimonio_o_modelo_recusa():
    """Sem âncora não há modelo: ele **é** o patrimônio mais o excesso."""
    sem_pl = Demonstracoes(
        empresa="Banco Vazio",
        valores=pd.DataFrame(
            {"lucro_liquido": [10.0, 12.0]}, index=[2023, 2024]
        ).T,
        avisos=["instituicao financeira"],
    )
    with pytest.raises(ValueError, match="patrimonio liquido"):
        sugerir_premissas_do_banco(sem_pl)


# ---------------------------------------------------------------------------
# Contra os bancos de verdade
# ---------------------------------------------------------------------------


def test_banco_que_nao_ganha_o_custo_de_capital_vale_menos_que_o_livro():
    """A afirmação que dá sentido ao modelo, num caso concreto.

    Medido com Ke de 14,5% sobre a mediana 2020-2024: Itaú e BB, com ROE perto de
    18%, saem acima de 1,1x o valor de livro; o Bradesco, com ROE de 12,1% —
    abaixo do Ke —, sai a **0,91x**. Um banco que não entrega o custo de capital
    destrói valor sobre o patrimônio que tem, e o modelo diz isso sem que
    ninguém precise afirmar.
    """
    ke = 0.145
    acima = sugerir_premissas_do_banco(_banco())  # ROE ~18%
    assert avaliar_lucro_residual(acima.premissas, ke=ke).equity_value > 1210.0

    abaixo = sugerir_premissas_do_banco(
        _banco(lucro_liquido=[100.0, 110.0, 121.0])  # ROE ~10,5%
    )
    resultado = avaliar_lucro_residual(abaixo.premissas, ke=ke)
    assert resultado.equity_value < abaixo.premissas.patrimonio_inicial


# ---------------------------------------------------------------------------
# O beta que decide o veredito
# ---------------------------------------------------------------------------


def test_o_beta_de_indiferenca_iguala_o_ke_ao_roe():
    """Com o realavancamento desligado, o beta carrega o Ke sozinho.

    E num banco o Ke decide o **sinal** do lucro residual: abaixo deste beta a
    instituição cria valor sobre o livro, acima destrói. O veredito inteiro gira
    em torno de um número que é valor de referência embarcado, e não medido.
    """
    from valuation.bancos import beta_de_indiferenca
    from valuation.custo_capital import calcular_custo_capital
    from valuation.premissas import PremissasCustoCapital, PremissasMacro

    cc = PremissasCustoCapital(
        beta_desalavancado=0.95, divida_pl_alvo=0.0, instituicao_financeira=True
    )
    macro = PremissasMacro()

    for roe in (0.09, 0.126, 0.18, 0.25):
        beta = beta_de_indiferenca(cc, macro, roe)
        ke = calcular_custo_capital(
            PremissasCustoCapital(
                beta_desalavancado=beta,
                divida_pl_alvo=0.0,
                instituicao_financeira=True,
            ),
            macro,
        ).ke_brl
        assert ke == pytest.approx(roe), f"ROE de {roe:.1%} nao fechou"


def test_o_beta_de_indiferenca_cresce_com_o_roe():
    """Quem ganha mais suporta mais risco antes de deixar de criar valor."""
    from valuation.bancos import beta_de_indiferenca
    from valuation.premissas import PremissasCustoCapital, PremissasMacro

    cc = PremissasCustoCapital(
        beta_desalavancado=0.95, divida_pl_alvo=0.0, instituicao_financeira=True
    )
    macro = PremissasMacro()
    betas = [beta_de_indiferenca(cc, macro, roe) for roe in (0.10, 0.15, 0.20)]
    assert betas == sorted(betas)


def test_sem_roe_nao_ha_beta_de_indiferenca():
    """Número inventado num lugar em que não há resposta é pior que ausência."""
    from valuation.bancos import beta_de_indiferenca
    from valuation.premissas import PremissasCustoCapital, PremissasMacro

    cc = PremissasCustoCapital(beta_desalavancado=0.95, instituicao_financeira=True)
    assert not np.isfinite(
        beta_de_indiferenca(cc, PremissasMacro(), float("nan"))
    )


def _banco_com_minoritario(pl, minoritario, lucro_c, lucro_k):
    import pandas as pd

    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "patrimonio_liquido": pl,
                "minoritarios": minoritario,
                "lucro_liquido": lucro_c,
                "lucro_controladores": lucro_k,
                "dividendos_pagos": -lucro_k * 0.4,
            }
            for ano in (2022, 2023, 2024)
        }
    )
    return Demonstracoes(empresa="Banco T", valores=valores, unidade="R$ milhões")


def test_o_lucro_residual_parte_do_patrimonio_do_controlador():
    """Aqui o número **decide**, e não só descreve.

    `equity = PL contábil + VP do lucro residual`. Partir do patrimônio
    **consolidado** produz o equity do **grupo**, enquanto o preço e a contagem
    de ações são da controladora — P/VP e valor por ação saem inflados, e nada
    denuncia porque o modelo fecha.

    Medido nas instituições de 2024: **11 das 32** têm minoritário acima de 0,5%
    do patrimônio, e a correção tira de 0,7% a **52,8%** do valor de partida —
    Wiz −52,8%, Cielo −22,7%, BTG −9,4%, Itaú −4,6%.

    Isto é diferente do `ROE` do histórico, que fica consolidado de propósito:
    lá o número descreve, aqui ele decide.
    """
    from valuation.bancos import ler_historico

    historico = ler_historico(
        _banco_com_minoritario(pl=1000.0, minoritario=200.0, lucro_c=150.0, lucro_k=120.0)
    )
    # O patrimonio de partida e o do controlador: 1.000 - 200.
    assert float(historico.patrimonio.iloc[-1]) == pytest.approx(800.0)
    # E o lucro acompanha, senao o ROE misturaria as duas bases.
    assert float(historico.lucro.iloc[-1]) == pytest.approx(120.0)


def test_sem_atribuicao_publicada_o_consolidado_e_o_que_ha():
    """A queda só alcança quem não abriu a atribuição — e ali os dois coincidem."""
    import numpy as np
    import pandas as pd

    from valuation.bancos import ler_historico
    from valuation.importacao import Demonstracoes

    valores = pd.DataFrame(
        {
            ano: {
                "patrimonio_liquido": 1000.0,
                "lucro_liquido": 150.0,
                "dividendos_pagos": -60.0,
            }
            for ano in (2023, 2024)
        }
    )
    historico = ler_historico(
        Demonstracoes(empresa="B", valores=valores, unidade="R$ milhões")
    )
    assert float(historico.patrimonio.iloc[-1]) == pytest.approx(1000.0)
    assert float(historico.lucro.iloc[-1]) == pytest.approx(150.0)


def test_o_patrimonio_dos_minoritarios_e_lido_no_plano_financeiro():
    """No banco a conta é `2.07.02`, e o rótulo é que a encontra.

    `2.03.09` não existe no plano financeiro, e `2.07` já é um código que muda
    de conta entre planos — adotá-lo arriscaria ler outra coisa numa industrial.
    O rótulo "Patrimônio Líquido Atribuído aos Não Controladores" não tem essa
    ambiguidade, e neste projeto ele tem prioridade sobre o código.

    Medido em 2024, antes da correção: **8 das 36 instituições** tinham lucro de
    minoritário e nenhum patrimônio deles — o Banco do Brasil com R$ 2,8 bi de
    lucro atribuído a não controladores e patrimônio ausente. Depois: **zero**.
    """
    from valuation.importacao.esquema import POR_CHAVE, reconhecer

    conta = POR_CHAVE["minoritarios"]
    assert "patrimonio liquido atribuido aos nao controladores" in conta.sinonimos

    achada = reconhecer("Patrimônio Líquido Atribuído aos Não Controladores")
    assert achada.chave == "minoritarios", achada
