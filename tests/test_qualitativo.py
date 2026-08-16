"""Evidencia para as perguntas de framework -- e o cuidado de nao responder.

O risco deste modulo nao e errar uma conta: e escrever "vantagem competitiva
solida" a partir de um ROIC alto e mandar para o cliente. Os testes daqui
guardam a fronteira: cada bloco traz numero medido, declara o que os dados nao
alcancam, e nenhum deles conclui.
"""

from __future__ import annotations

import pandas as pd
import pytest

from valuation import avaliar
from valuation.historico import analisar
from valuation.importacao import Demonstracoes
from valuation.qualitativo import reunir_evidencias


@pytest.fixture
def analise_rica():
    anos = {}
    for i, ano in enumerate((2020, 2021, 2022, 2023, 2024)):
        anos[ano] = {
            "receita_liquida": 1000.0 * (1.12**i),
            "custo_produtos_vendidos": 620.0 * (1.12**i),
            "ebit": 200.0 * (1.12**i),
            "depreciacao_amortizacao": 50.0 * (1.12**i),
            "lucro_liquido": 130.0 * (1.12**i),
            "ativo_total": 1200.0 * (1.12**i),
            "patrimonio_liquido": 700.0 * (1.12**i),
            "contas_receber": 190.0 * (1.12**i),
            "estoques": 150.0 * (1.12**i),
            "fornecedores": 110.0 * (1.12**i),
            "divida_curto_prazo": 100.0,
            "divida_longo_prazo": 300.0,
            "caixa_equivalentes": 80.0,
            "capex": 60.0 * (1.12**i),
        }
    return analisar(Demonstracoes(empresa="Exemplo", valores=pd.DataFrame(anos)))


def test_as_seis_perguntas_aparecem(analise_rica):
    temas = [e.tema for e in reunir_evidencias(analise_rica)]
    assert len(temas) == 6
    assert "Fosso (vantagem competitiva)" in temas
    assert "Ameaça de substitutos" in temas


def test_toda_evidencia_declara_o_que_os_dados_nao_dizem(analise_rica):
    """Sem isso o leitor toma o medido pelo respondido."""
    for evidencia in reunir_evidencias(analise_rica):
        assert evidencia.limite, f"{evidencia.tema} nao declarou limite"
        assert evidencia.pergunta.endswith("?")


def test_substitutos_aparece_mesmo_sem_dado_nenhum(analise_rica):
    """Omitir a secao faria parecer que a pergunta nao existe."""
    substitutos = next(
        e for e in reunir_evidencias(analise_rica) if e.tema == "Ameaça de substitutos"
    )
    assert not substitutos.tem_dado
    assert "Nenhuma evidência quantitativa" in substitutos.limite


def test_o_fosso_compara_roic_com_wacc_quando_ha_valuation(analise_rica, empresa_exemplo):
    resultado = avaliar(empresa_exemplo)
    fosso = next(
        e for e in reunir_evidencias(analise_rica, resultado)
        if e.tema.startswith("Fosso")
    )
    texto = " ".join(fosso.medido)
    assert "ROIC mediano" in texto
    assert "acima do WACC" in texto


def test_sem_valuation_o_fosso_nao_inventa_comparacao(analise_rica):
    fosso = next(e for e in reunir_evidencias(analise_rica) if e.tema.startswith("Fosso"))
    assert "acima do WACC" not in " ".join(fosso.medido)


def test_poucos_anos_impedem_a_afirmacao_de_vantagem(empresa_exemplo):
    """Um ano bom nao e fosso, e o texto tem que dizer isso em vez de concluir."""
    valores = pd.DataFrame(
        {
            2023: {"receita_liquida": 1000.0, "ebit": 300.0, "ativo_total": 800.0,
                   "patrimonio_liquido": 500.0},
            2024: {"receita_liquida": 1100.0, "ebit": 330.0, "ativo_total": 850.0,
                   "patrimonio_liquido": 550.0},
        }
    )
    analise = analisar(Demonstracoes(empresa="Curta", valores=valores))
    fosso = next(
        e for e in reunir_evidencias(analise, avaliar(empresa_exemplo))
        if e.tema.startswith("Fosso")
    )
    texto = " ".join(fosso.medido)
    assert "não dá para dizer" in texto
    assert "assinatura contábil" not in texto


def test_sem_historico_nao_ha_evidencia():
    assert reunir_evidencias(None) == []


def test_o_relatorio_deixa_a_resposta_em_branco(analise_rica, empresa_exemplo):
    from valuation.relatorio import montar

    texto = montar(
        avaliar(empresa_exemplo),
        analise=analise_rica,
        evidencias=reunir_evidencias(analise_rica, avaliar(empresa_exemplo)),
    )
    assert "## As perguntas que os números não respondem" in texto
    assert "**Leitura do analista:**" in texto
    assert texto.count("**Leitura do analista:**") == 6


def test_sem_evidencias_o_relatorio_diz_que_faltou(empresa_exemplo):
    from valuation.relatorio import montar

    texto = montar(avaliar(empresa_exemplo))
    assert "Sem histórico importado" in texto
    assert "nenhuma das perguntas de framework" in texto
