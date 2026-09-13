"""Duas dividas liquidas: com e sem o TVM de longo prazo.

A padrao abate so o TVM circulante. Onde o titulo de longo prazo pesa, as
companhias o abatem tambem -- conferido contra o release de 2024 da Ultrapar
(11.163 no app, 7.756 publicados, e a diferenca e exatamente a linha), da
Embraer ("investimentos financeiros de curto e longo prazo") e da Cyrela ("Titulos
e Valores Mobiliarios LP", 2.256, o que o app le).

E nem todo TVM e caixa, em nenhum dos dois prazos. O que decide e o rotulo da
subconta publicada, e os casos abaixo sao os que a base de 2024 tem de fato.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from valuation.importacao import Demonstracoes
from valuation.importacao.aplicacoes import (
    CAIXA,
    NAO_E_CAIXA,
    VINCULADO,
    classificar,
    longo_prazo_que_abate,
    titulos,
)

DADOS = Path(__file__).parent / "dados" / "cvm"


def _arvore(linhas: dict[str, tuple[str, float]], plano: str = "Ativo Realizável a Longo Prazo"):
    """Arvore publicada minima: o grupo que declara o plano e as linhas pedidas."""
    todas = {"1.02.01": (plano, 0.0), **linhas}
    return pd.DataFrame(
        [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "demonstracao": "bp",
                "nivel": codigo.count(".") + 1,
                "ordem": tuple(int(p) for p in codigo.split(".")),
                2024: valor,
            }
            for codigo, (rotulo, valor) in todas.items()
        ]
    )


# ---------------------------------------------------------------------------
# O rotulo decide
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rotulo", "classe"),
    [
        # **A fronteira de palavra.** Sem ela, "aplic-acoes" viraria participacao
        # societaria -- e e o rotulo de quase toda linha desta arvore.
        ("Aplicações Financeiras Avaliadas ao Custo Amortizado", CAIXA),
        ("Títulos Designados a Valor Justo", CAIXA),
        ("Aplicações livres", CAIXA),  # Bradsaude, ao lado da garantidora
        ("Instrumentos financeiros derivativos", NAO_E_CAIXA),  # Simpar, 2.244
        ("Aplicações Garantidoras de Provisões Técnicas", NAO_E_CAIXA),  # Bradsaude
        (
            "Aplicações Financeiras Avaliadas a Valor Justo através do resultado - "
            "Ações Usiminas",
            NAO_E_CAIXA,
        ),  # CSN, 861, no circulante
        ("Operações de crédito", NAO_E_CAIXA),
        ("Debêntures Privadas Partes Relacionadas", NAO_E_CAIXA),
        ("Certificados de depósito bancário vinculados", VINCULADO),  # Localiza
        ("Caixa restrito", VINCULADO),  # Serena, 488
        ("Aplicações Financeiras - Conta Reserva", VINCULADO),  # Motiva, Ecorodovias
        ("Aplicações caucionadas", VINCULADO),
        ("Caixa Margem", VINCULADO),
    ],
)
def test_o_rotulo_publicado_decide_a_classe(rotulo, classe):
    assert classificar(rotulo)[0] == classe


def test_toda_classe_diz_o_porque():
    """Linha classificada sem motivo e decisão que o analista não pode conferir."""
    for rotulo in ("Caixa restrito", "Instrumentos financeiros derivativos", "Títulos"):
        classe, motivo = classificar(rotulo)
        assert motivo and len(motivo) > 20, (rotulo, classe)


# ---------------------------------------------------------------------------
# A arvore, lida ate onde a companhia abriu
# ---------------------------------------------------------------------------


def test_a_weg_de_verdade_com_subconta_zerada():
    """**A subconta não precisa somar o grupo.**

    A WEG publica `1.02.01.01` com R$ 17,1 mi e a única filha com **zero**. Ler
    só as filhas perderia o saldo inteiro -- e é do fixture real, e não de uma
    árvore montada à mão, que este caso sai.
    """
    from valuation.importacao.cvm import importar_cvm

    weg = importar_cvm(5410, [2024, 2025], cache=DADOS).escalar(1e6, "R$ milhões")

    longo = [l for l in weg.titulos_e_valores_mobiliarios(2024) if l.longo_prazo]
    assert [(l.codigo, l.classe) for l in longo] == [("1.02.01.01", CAIXA)]

    lp = weg.aplicacoes_de_longo_prazo()
    assert lp[2024] == pytest.approx(17.134)
    assert lp[2025] == pytest.approx(14.263)
    np.testing.assert_allclose(
        weg.divida_liquida_ampla().to_numpy(),
        (weg.divida_liquida() - lp).to_numpy(),
    )


def test_o_ajuste_negativo_segue_a_conta_que_ele_ajusta():
    """Localiza: CDB vinculado de 1.216 e "(-) Ajuste a Valor Presente" de -242.

    O rótulo do ajuste não tem sinal nenhum e cairia em caixa: a tela mostraria
    caixa **negativo** ao lado de um vinculado inflado.
    """
    arvore = _arvore(
        {
            "1.02.01.03": ("Aplicações Financeiras Avaliadas ao Custo Amortizado", 974.0),
            "1.02.01.03.01": ("Certificados de depósito bancário vinculados", 1216.0),
            "1.02.01.03.02": ("(-) Ajuste a Valor Presente", -242.0),
        }
    )
    linhas = titulos(arvore, 2024)
    assert {l.classe for l in linhas} == {VINCULADO}
    assert longo_prazo_que_abate(arvore, [2024])[2024] == pytest.approx(974.0)


def test_o_derivativo_fica_fora_e_o_resto_do_grupo_entra():
    """Simpar: 2.244 de derivativo e 187 de TVM dentro do mesmo grupo do IFRS 9.

    E a diferença de arredondamento entre o grupo e as filhas não vira linha.
    """
    arvore = _arvore(
        {
            "1.02.01.02": ("Aplicações Financeiras Avaliadas a Valor Justo através "
                           "de Outros Resultados Abrangentes", 2432.0),
            "1.02.01.02.02": ("Instrumentos financeiros derivativos", 2244.0),
            "1.02.01.02.03": ("Títulos, valores mobiliários e aplicações financeiras", 187.5),
        }
    )
    linhas = titulos(arvore, 2024)
    assert len(linhas) == 2
    assert longo_prazo_que_abate(arvore, [2024])[2024] == pytest.approx(187.5)


def test_o_circulante_tambem_e_classificado():
    """O caso clássico de TVM que é investimento mora no **circulante**: CSN."""
    arvore = _arvore(
        {
            "1.01.02.01": ("Aplicações Financeiras Avaliadas a Valor Justo através "
                           "do Resultado", 860.6),
            "1.01.02.01.03": ("Aplicações Financeiras Avaliadas a Valor Justo através "
                              "do resultado - Ações Usiminas", 860.6),
        }
    )
    (linha,) = titulos(arvore, 2024)
    assert not linha.longo_prazo
    assert linha.classe == NAO_E_CAIXA
    # E ele nao mexe na ampla: a diferenca entre as duas e so o longo prazo.
    assert longo_prazo_que_abate(arvore, [2024])[2024] == 0.0


def test_vazio_e_zero_sao_respostas_diferentes():
    """Sem árvore não se sabe; com árvore e sem a linha, é zero.

    Uma ampla igual à padrão por falta de dado teria cara de medida.
    """
    assert np.isnan(longo_prazo_que_abate(None, [2024])[2024])
    assert longo_prazo_que_abate(_arvore({}), [2024])[2024] == 0.0

    valores = pd.DataFrame(
        {2024: {"divida_curto_prazo": 100.0, "divida_longo_prazo": 400.0,
                "caixa_equivalentes": 50.0}}
    )
    sem_arvore = Demonstracoes(empresa="T", valores=valores, unidade="R$ mi")
    assert np.isnan(sem_arvore.divida_liquida_ampla()[2024])
    assert sem_arvore.divida_liquida()[2024] == pytest.approx(450.0)


def test_outro_plano_de_contas_nao_se_le():
    """No plano de banco `1.02.01` é outra conta; o rótulo do grupo decide."""
    arvore = _arvore(
        {"1.02.01.01": ("Aplicações Interfinanceiras de Liquidez", 900.0)},
        plano="Aplicações Interfinanceiras de Liquidez",
    )
    assert titulos(arvore, 2024) == []
    assert np.isnan(longo_prazo_que_abate(arvore, [2024])[2024])


# ---------------------------------------------------------------------------
# Historico, ponte e arquivo
# ---------------------------------------------------------------------------


def test_o_indicador_ampla_so_aparece_onde_difere():
    from valuation.historico import analisar
    from valuation.importacao.cvm import importar_cvm

    weg = importar_cvm(5410, [2024, 2025], cache=DADOS).escalar(1e6, "R$ milhões")
    assert "Divida liquida ampla / EBITDA" in analisar(weg).indicadores.index

    valores = pd.DataFrame(
        {
            ano: {"receita_liquida": 1000.0, "ebit": 200.0,
                  "depreciacao_amortizacao": 50.0, "patrimonio_liquido": 800.0,
                  "divida_curto_prazo": 100.0, "divida_longo_prazo": 400.0}
            for ano in (2023, 2024)
        }
    )
    sem_linha = Demonstracoes(empresa="T", valores=valores, unidade="R$ mi")
    assert "Divida liquida ampla / EBITDA" not in analisar(sem_linha).indicadores.index


def test_a_ponte_abate_o_longo_prazo_quando_pedido():
    from valuation import PonteValor, ponte_ev_equity

    padrao = PonteValor(divida_bruta=1000.0, caixa=100.0)
    ampla = PonteValor(divida_bruta=1000.0, caixa=100.0, aplicacoes_longo_prazo=300.0)
    assert padrao.divida_liquida == pytest.approx(900.0)
    assert ampla.divida_liquida == pytest.approx(600.0)

    equity, detalhe = ponte_ev_equity(5000.0, ampla)
    assert equity == pytest.approx(5000.0 - 600.0)
    assert detalhe.loc["(+) Aplicações de longo prazo", "Valor"] == pytest.approx(300.0)


def test_arquivo_antigo_abre_na_divida_liquida_padrao():
    """Projeto salvo antes do campo existir não pode deixar de abrir."""
    from valuation.entrada import construir_empresa
    from valuation.projeto import Projeto, desserializar, serializar

    antiga = construir_empresa(
        {"nome": "T", "ponte": {"divida_bruta": 500.0, "caixa": 50.0}}
    )
    assert antiga.ponte.aplicacoes_longo_prazo == 0.0

    from dataclasses import replace

    ampla = replace(antiga, ponte=replace(antiga.ponte, aplicacoes_longo_prazo=120.0))
    volta = desserializar(serializar(Projeto(empresa=ampla)))
    assert volta.empresa.ponte.aplicacoes_longo_prazo == pytest.approx(120.0)
    assert volta.empresa.ponte.divida_liquida == pytest.approx(330.0)


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------


def _tela_da_ponte():
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    from valuation.importacao.cvm import importar_cvm

    raiz = Path(__file__).resolve().parent.parent
    script = f"""
import sys
for caminho in ({str(raiz)!r}, {str(raiz / "src")!r}):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
import streamlit as st
from app import estado
from app.paginas import valor

estado.iniciar()
if st.session_state.get("dfs") is not None:
    estado.definir_demonstracoes(st.session_state.pop("dfs"))
valor._duas_dividas_liquidas(estado.empresa().ponte, "R$ milhões")
"""
    teste = AppTest.from_string(script, default_timeout=120)
    teste.session_state["dfs"] = importar_cvm(
        5410, [2024, 2025], cache=DADOS
    ).escalar(1e6, "R$ milhões")
    teste.run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    return teste


def test_a_tela_mostra_as_duas_e_troca_com_um_clique():
    from app.estado import CHAVE_EMPRESA

    teste = _tela_da_ponte()
    texto = " ".join(str(m.value) for m in teste.markdown)
    assert "Duas dívidas líquidas" in texto
    assert "1.02.01.01" in texto

    usar = [b for b in teste.button if "ampla" in b.label]
    assert usar, [b.label for b in teste.button]
    usar[0].click().run()
    assert not teste.exception, [str(e.value) for e in teste.exception]
    ponte = teste.session_state[CHAVE_EMPRESA].ponte
    assert ponte.aplicacoes_longo_prazo == pytest.approx(14.263)

    voltar = [b for b in teste.button if "padrão" in b.label]
    assert voltar, [b.label for b in teste.button]
