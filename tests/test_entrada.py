"""Testes da leitura de arquivos de premissas."""

from __future__ import annotations

import json

import pytest

from valuation import avaliar, carregar_comparaveis, carregar_empresa, carregar_modelo
from valuation.exemplos import escrever_exemplos

MINIMO = """
nome: Minima S.A.
operacionais:
  receita_base: 1000.0
  horizonte: 3
  crescimento_receita: 0.05
  margem_ebitda: 0.20
  depreciacao_pct_receita: 0.05
  capex_pct_receita: 0.05
  capital_giro_pct_receita: 0.10
"""


def _escrever(tmp_path, conteudo: str, nome: str = "premissas.yaml"):
    caminho = tmp_path / nome
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def test_horizonte_replica_premissas_escalares(tmp_path):
    """Escrever um numero unico e o atalho para 'esse valor em todos os anos'."""
    empresa = carregar_empresa(_escrever(tmp_path, MINIMO))
    assert empresa.operacionais.crescimento_receita == [0.05, 0.05, 0.05]
    assert empresa.operacionais.margem_ebitda == [0.20, 0.20, 0.20]
    assert empresa.operacionais.horizonte == 3


def test_valores_padrao_sao_aplicados(tmp_path):
    empresa = carregar_empresa(_escrever(tmp_path, MINIMO))
    assert empresa.macro.aliquota_ir == pytest.approx(0.34)
    assert empresa.perpetuidade.metodo == "gordon"
    assert empresa.moeda == "BRL"


def test_lista_completa_tambem_funciona(tmp_path):
    conteudo = MINIMO.replace("crescimento_receita: 0.05", "crescimento_receita: [0.1, 0.08, 0.06]")
    empresa = carregar_empresa(_escrever(tmp_path, conteudo))
    assert empresa.operacionais.crescimento_receita == [0.1, 0.08, 0.06]


def test_lista_com_tamanho_errado_e_rejeitada(tmp_path):
    conteudo = MINIMO.replace("crescimento_receita: 0.05", "crescimento_receita: [0.1, 0.08]")
    with pytest.raises(ValueError, match="horizonte=3"):
        carregar_empresa(_escrever(tmp_path, conteudo))


def test_escalar_sem_horizonte_e_rejeitado(tmp_path):
    conteudo = MINIMO.replace("  horizonte: 3\n", "")
    with pytest.raises(ValueError, match="horizonte"):
        carregar_empresa(_escrever(tmp_path, conteudo))


def test_campo_com_nome_errado_e_rejeitado(tmp_path):
    """Um campo digitado errado precisa falhar, nunca ser ignorado em silencio."""
    conteudo = MINIMO + "\nmacro:\n  inflacao_bl: 0.04\n"
    with pytest.raises(ValueError, match="inflacao_bl"):
        carregar_empresa(_escrever(tmp_path, conteudo))


def test_bloco_com_nome_errado_e_rejeitado(tmp_path):
    conteudo = MINIMO + "\nperpetuidad:\n  crescimento_perpetuo: 0.04\n"
    with pytest.raises(ValueError, match="perpetuidad"):
        carregar_empresa(_escrever(tmp_path, conteudo))


def test_nome_e_obrigatorio(tmp_path):
    conteudo = MINIMO.replace("nome: Minima S.A.\n", "")
    with pytest.raises(ValueError, match="nome"):
        carregar_empresa(_escrever(tmp_path, conteudo))


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        carregar_empresa(tmp_path / "nao_existe.yaml")


def test_json_tambem_e_aceito(tmp_path):
    dados = {
        "nome": "JSON S.A.",
        "operacionais": {
            "receita_base": 1000.0,
            "horizonte": 2,
            "crescimento_receita": 0.05,
            "margem_ebitda": 0.20,
            "depreciacao_pct_receita": 0.05,
            "capex_pct_receita": 0.05,
            "capital_giro_pct_receita": 0.10,
        },
    }
    caminho = tmp_path / "premissas.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    assert carregar_empresa(caminho).nome == "JSON S.A."


def test_blocos_de_analise_sao_lidos(tmp_path):
    conteudo = MINIMO + """
sensibilidade:
  linhas: {caminho: wacc, valores: [0.10, 0.12]}
  colunas: {caminho: perpetuidade.crescimento_perpetuo, valores: [0.03, 0.04]}
cenarios:
  Pessimista: {operacionais.margem_ebitda: 0.15}
simulacao:
  simulacoes: 100
  metrica: equity_value
  distribuicoes:
    - caminho: wacc
      tipo: triangular
      parametros: {minimo: 0.10, moda: 0.12, maximo: 0.14}
"""
    modelo = carregar_modelo(_escrever(tmp_path, conteudo))
    assert modelo.sensibilidade["linhas"]["caminho"] == "wacc"
    assert modelo.cenarios["Pessimista"] == {"operacionais.margem_ebitda": 0.15}
    assert modelo.simulacoes == 100
    assert len(modelo.distribuicoes) == 1
    assert modelo.distribuicoes[0].tipo == "triangular"


def test_sensibilidade_sem_eixo_e_rejeitada(tmp_path):
    conteudo = MINIMO + """
sensibilidade:
  linhas: {caminho: wacc, valores: [0.10]}
"""
    with pytest.raises(ValueError, match="colunas"):
        carregar_modelo(_escrever(tmp_path, conteudo))


def test_distribuicao_com_campo_errado_e_rejeitada(tmp_path):
    conteudo = MINIMO + """
simulacao:
  distribuicoes:
    - caminho: wacc
      tipo: normal
      parametro: {media: 0.12}
"""
    with pytest.raises(ValueError, match="parametro"):
        carregar_modelo(_escrever(tmp_path, conteudo))


def test_exemplos_gerados_sao_validos_e_avaliaveis(tmp_path):
    """O exemplo distribuido precisa rodar: e a primeira coisa que o usuario tenta."""
    empresa_yaml, comparaveis_yaml = escrever_exemplos(tmp_path)

    modelo = carregar_modelo(empresa_yaml)
    resultado = avaliar(modelo.empresa)
    assert resultado.equity_value > 0
    assert modelo.cenarios and modelo.distribuicoes and modelo.sensibilidade

    alvo, comparaveis = carregar_comparaveis(comparaveis_yaml)
    assert alvo.nome == modelo.empresa.nome
    assert len(comparaveis) == 5


def test_comparaveis_exigem_os_dois_blocos(tmp_path):
    caminho = _escrever(tmp_path, "alvo:\n  nome: X\n", "comp.yaml")
    with pytest.raises(ValueError, match="comparaveis"):
        carregar_comparaveis(caminho)
