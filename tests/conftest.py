"""Fixtures compartilhadas pelos testes."""

from __future__ import annotations

import pytest

from valuation import (
    Alvo,
    Comparavel,
    Empresa,
    PonteValor,
    PremissasCustoCapital,
    PremissasMacro,
    PremissasOperacionais,
    PremissasPerpetuidade,
)


@pytest.fixture
def macro() -> PremissasMacro:
    return PremissasMacro(inflacao_brl=0.04, inflacao_usd=0.023, aliquota_ir=0.34)


@pytest.fixture
def operacionais() -> PremissasOperacionais:
    return PremissasOperacionais(
        receita_base=1000.0,
        crescimento_receita=[0.10, 0.08, 0.06],
        margem_ebitda=[0.20, 0.20, 0.20],
        depreciacao_pct_receita=[0.05, 0.05, 0.05],
        capex_pct_receita=[0.06, 0.055, 0.05],
        capital_giro_pct_receita=[0.10, 0.10, 0.10],
    )


@pytest.fixture
def empresa_exemplo(macro, operacionais) -> Empresa:
    return Empresa(
        nome="Teste S.A.",
        macro=macro,
        custo_capital=PremissasCustoCapital(
            rf_usd=0.045,
            erp_maduro=0.045,
            risco_pais=0.025,
            beta_alavancado_setor=1.05,
            divida_pl_setor=0.45,
            divida_pl_alvo=0.50,
            spread_credito=0.025,
        ),
        operacionais=operacionais,
        perpetuidade=PremissasPerpetuidade(
            metodo="gordon", crescimento_perpetuo=0.045, roic_perpetuidade=0.15
        ),
        ponte=PonteValor(
            divida_bruta=900.0,
            caixa=250.0,
            minoritarios=30.0,
            contingencias=60.0,
            acoes_em_circulacao=150.0,
        ),
        data_base="2025-12-31",
    )


@pytest.fixture
def comparaveis() -> list[Comparavel]:
    return [
        Comparavel(
            nome="Alfa",
            valor_mercado=2400.0,
            divida_liquida=900.0,
            receita=1850.0,
            ebitda=351.0,
            ebit=259.0,
            lucro_liquido=145.0,
            patrimonio_liquido=1100.0,
        ),
        Comparavel(
            nome="Beta",
            valor_mercado=1750.0,
            divida_liquida=420.0,
            receita=1320.0,
            ebitda=224.0,
            ebit=158.0,
            lucro_liquido=96.0,
            patrimonio_liquido=780.0,
        ),
        Comparavel(
            nome="Gama",
            valor_mercado=3900.0,
            divida_liquida=-150.0,
            receita=2600.0,
            ebitda=546.0,
            ebit=425.0,
            lucro_liquido=288.0,
            patrimonio_liquido=1950.0,
        ),
        # Prejuizo: P/L deve sair como NaN e ficar fora das estatisticas.
        Comparavel(
            nome="Delta",
            valor_mercado=1400.0,
            divida_liquida=880.0,
            receita=1600.0,
            ebitda=192.0,
            ebit=96.0,
            lucro_liquido=-35.0,
            patrimonio_liquido=690.0,
        ),
    ]


@pytest.fixture
def alvo() -> Alvo:
    return Alvo(
        nome="Teste S.A.",
        receita=1000.0,
        ebitda=200.0,
        ebit=150.0,
        lucro_liquido=70.0,
        patrimonio_liquido=600.0,
        divida_liquida=650.0,
        acoes_em_circulacao=150.0,
    )
