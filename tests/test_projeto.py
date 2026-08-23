"""Testes de salvar e retomar um valuation.

O que importa aqui e uma coisa so: o que voltou tem que ser identico ao que
saiu. Um arquivo de projeto que perde uma premissa no caminho e pior do que nao
ter arquivo nenhum, porque o usuario so descobre a perda quando o numero muda.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from valuation import Alvo, Comparavel, avaliar
from valuation.importacao import Demonstracoes
from valuation.importacao.importador import RECUO
from valuation.projeto import (
    VERSAO,
    Projeto,
    carregar,
    desserializar,
    salvar,
    serializar,
)


@pytest.fixture
def demonstracoes() -> Demonstracoes:
    valores = pd.DataFrame(
        {
            2023: {"receita_liquida": 1000.0, "ebit": 200.0, "capex": np.nan},
            2024: {"receita_liquida": 1100.0, "ebit": 220.0, "capex": 60.0},
        }
    )
    return Demonstracoes(
        empresa="Teste S.A.",
        valores=valores,
        unidade="R$ milhões",
        origem="cvm.xlsx",
        mapeamento={"receita_liquida": "3.01 Receita (DRE)"},
        derivadas={"ebit": "EBIT = lucro bruto - despesas"},
    )


@pytest.fixture
def projeto(empresa_exemplo, demonstracoes, comparaveis, alvo) -> Projeto:
    return Projeto(
        empresa=empresa_exemplo,
        demonstracoes=demonstracoes,
        comparaveis=comparaveis,
        alvo=alvo,
        config={"meio_de_ano": True, "tipo_fluxo": "fcff", "pais": "Brasil"},
    )


# ---------------------------------------------------------------------------
# Ida e volta
# ---------------------------------------------------------------------------


def test_premissas_voltam_identicas(projeto):
    volta = desserializar(serializar(projeto))
    assert volta.empresa == projeto.empresa


def test_conferencia_sobrevive_a_ida_e_volta(empresa_exemplo, demonstracoes):
    """Retomar tem que devolver o que ainda da para corrigir, nao so os numeros.

    Sem as linhas nao reconhecidas no arquivo, a tela de conferencia voltava
    vazia e o usuario perdia a chance de mapear a mao o que o app nao entendeu.
    """
    from valuation.importacao import LinhaNaoReconhecida

    original = type(demonstracoes)(
        **{
            **demonstracoes.__dict__,
            "nao_reconhecidas": [
                LinhaNaoReconhecida("6.02.02 - Imobilizado", "DFC", None, 0.0),
                LinhaNaoReconhecida("1.01.06 - Tributos", "Balanço", "estoques", 0.42),
            ],
            "avisos": ["Ativo e passivo divergem em 2%."],
        }
    )
    volta = desserializar(serializar(Projeto(empresa=empresa_exemplo, demonstracoes=original)))

    assert [l.rotulo for l in volta.demonstracoes.nao_reconhecidas] == [
        "6.02.02 - Imobilizado",
        "1.01.06 - Tributos",
    ]
    recuperada = volta.demonstracoes.nao_reconhecidas[1]
    assert recuperada.aba == "Balanço"
    assert recuperada.melhor_palpite == "estoques"
    assert recuperada.confianca == pytest.approx(0.42)
    assert volta.demonstracoes.avisos == ["Ativo e passivo divergem em 2%."]


def test_arvore_publicada_sobrevive_a_ida_e_volta(empresa_exemplo, demonstracoes):
    """A quebra e o que explica o total; perde-la ao salvar esvazia o arquivo."""
    detalhe = pd.DataFrame(
        [
            {"codigo": "1", "rotulo": "Ativo Total", "demonstracao": "bp",
             "nivel": 1, "ordem": (1,), 2023: 100.0, 2024: 120.0},
            {"codigo": "1.01", "rotulo": "Ativo Circulante", "demonstracao": "bp",
             "nivel": 2, "ordem": (1, 1), 2023: 60.0, 2024: 70.0},
            {"codigo": "1.01.02", "rotulo": "Aplicações", "demonstracao": "bp",
             "nivel": 3, "ordem": (1, 1, 2), 2023: 10.0, 2024: np.nan},
        ]
    )
    original = type(demonstracoes)(**{**demonstracoes.__dict__, "detalhe": detalhe})
    volta = desserializar(
        serializar(Projeto(empresa=empresa_exemplo, demonstracoes=original))
    )

    reconstruida = volta.demonstracoes.detalhe
    assert list(reconstruida["codigo"]) == ["1", "1.01", "1.01.02"]
    assert list(reconstruida["nivel"]) == [1, 2, 3]
    assert reconstruida.loc[1, 2024] == pytest.approx(70.0)
    assert np.isnan(reconstruida.loc[2, 2024])

    # E a arvore volta a se ler com a hierarquia, nao so os dados crus.
    arvore = volta.demonstracoes.arvore("bp")
    assert list(arvore.index) == [
        "Ativo Total",
        RECUO + "Ativo Circulante",
        RECUO * 2 + "Aplicações",
    ]


def test_fonte_sobrevive_a_ida_e_volta(empresa_exemplo, demonstracoes):
    """É o que permite rebuscar na CVM um valuation salvo meses atrás."""
    fonte = {"tipo": "cvm", "codigo_cvm": 5410, "anos": [2023, 2024]}
    original = type(demonstracoes)(**{**demonstracoes.__dict__, "fonte": fonte})
    volta = desserializar(serializar(Projeto(empresa=empresa_exemplo, demonstracoes=original)))
    assert volta.demonstracoes.fonte == fonte


def test_arquivo_antigo_sem_os_campos_novos_continua_abrindo(projeto):
    """Compatibilidade: quem salvou antes destes campos nao pode ficar preso."""
    volta = desserializar(serializar(projeto))
    assert volta.demonstracoes.nao_reconhecidas == []
    assert volta.demonstracoes.avisos == []
    assert volta.demonstracoes.fonte == {}


def test_valuation_reproduz_o_mesmo_numero(projeto):
    """A prova que importa: o modelo restaurado calcula o mesmo valor."""
    original = avaliar(projeto.empresa, meio_de_ano=True)
    volta = avaliar(desserializar(serializar(projeto)).empresa, meio_de_ano=True)
    assert volta.equity_value == pytest.approx(original.equity_value)
    assert volta.custo_capital.wacc_brl == pytest.approx(original.custo_capital.wacc_brl)


def test_demonstracoes_voltam_identicas(projeto):
    volta = desserializar(serializar(projeto))
    pd.testing.assert_frame_equal(
        volta.demonstracoes.valores.astype(float),
        projeto.demonstracoes.valores.astype(float),
        check_names=False,
    )
    assert volta.demonstracoes.empresa == "Teste S.A."
    assert volta.demonstracoes.unidade == "R$ milhões"


def test_lacuna_no_historico_continua_lacuna(projeto):
    """NaN precisa voltar NaN, e nao virar zero -- zero e um dado, ausencia nao."""
    volta = desserializar(serializar(projeto))
    assert np.isnan(volta.demonstracoes.valores.loc["capex", 2023])
    assert volta.demonstracoes.valores.loc["capex", 2024] == pytest.approx(60.0)


def test_comparaveis_voltam_identicos(projeto):
    volta = desserializar(serializar(projeto))
    assert volta.comparaveis == projeto.comparaveis
    assert volta.alvo == projeto.alvo


def test_config_volta(projeto):
    volta = desserializar(serializar(projeto))
    assert volta.config["meio_de_ano"] is True
    assert volta.config["tipo_fluxo"] == "fcff"


def test_mapeamento_da_importacao_volta(projeto):
    """Sem isso o usuario perde a auditoria de onde cada conta veio."""
    volta = desserializar(serializar(projeto))
    assert volta.demonstracoes.mapeamento["receita_liquida"] == "3.01 Receita (DRE)"
    assert "ebit" in volta.demonstracoes.derivadas


def test_ida_e_volta_e_estavel(projeto):
    """Salvar o que foi carregado produz exatamente o mesmo texto."""
    primeiro = serializar(projeto)
    segundo = serializar(desserializar(primeiro))
    assert primeiro == segundo


# ---------------------------------------------------------------------------
# Projeto minimo e blocos opcionais
# ---------------------------------------------------------------------------


def test_projeto_so_com_premissas(empresa_exemplo):
    texto = serializar(Projeto(empresa=empresa_exemplo))
    volta = desserializar(texto)
    assert volta.empresa == empresa_exemplo
    assert volta.demonstracoes is None
    assert volta.comparaveis == []
    assert volta.alvo is None


def test_blocos_vazios_nao_sao_gravados(empresa_exemplo):
    texto = serializar(Projeto(empresa=empresa_exemplo))
    assert "demonstracoes:" not in texto
    assert "comparaveis:" not in texto


def test_arquivo_e_yaml_legivel(projeto):
    """O formato existe para ser lido e revisado por gente."""
    texto = serializar(projeto)
    assert "versao:" in texto
    assert "empresa:" in texto
    assert "!!python" not in texto  # nada de objetos serializados


# ---------------------------------------------------------------------------
# Versionamento e erros
# ---------------------------------------------------------------------------


def test_versao_e_gravada(projeto):
    import yaml

    assert yaml.safe_load(serializar(projeto))["versao"] == VERSAO


def test_versao_futura_e_recusada(projeto):
    import yaml

    dados = yaml.safe_load(serializar(projeto))
    dados["versao"] = VERSAO + 5
    with pytest.raises(ValueError, match="Atualize o app"):
        desserializar(yaml.safe_dump(dados))


def test_arquivo_sem_versao_e_recusado(empresa_exemplo):
    with pytest.raises(ValueError, match="versao"):
        desserializar("empresa:\n  nome: X\n")


def test_arquivo_sem_empresa_e_recusado():
    with pytest.raises(ValueError, match="empresa"):
        desserializar("versao: 1\n")


def test_yaml_invalido_da_mensagem_clara():
    with pytest.raises(ValueError, match="nao e um YAML valido"):
        desserializar("versao: 1\n  empresa: [ isto: nao fecha\n")


def test_texto_que_nao_e_mapeamento():
    with pytest.raises(ValueError, match="mapeamento"):
        desserializar("- uma\n- lista\n")


def test_premissa_com_nome_errado_e_recusada(projeto):
    """A validacao do arquivo de premissas vale tambem para o projeto salvo."""
    import yaml

    dados = yaml.safe_load(serializar(projeto))
    dados["empresa"]["macro"]["inflacao_bl"] = 0.04
    with pytest.raises(ValueError, match="inflacao_bl"):
        desserializar(yaml.safe_dump(dados))


def test_demonstracoes_sem_anos_e_recusada(projeto):
    import yaml

    dados = yaml.safe_load(serializar(projeto))
    dados["demonstracoes"]["anos"] = []
    with pytest.raises(ValueError, match="sem anos"):
        desserializar(yaml.safe_dump(dados))


# ---------------------------------------------------------------------------
# Disco
# ---------------------------------------------------------------------------


def test_salvar_e_carregar_do_disco(projeto, tmp_path):
    caminho = salvar(projeto, tmp_path / "sub" / "analise.yaml")
    assert caminho.exists()
    volta = carregar(caminho)
    assert volta.empresa == projeto.empresa
    assert volta.demonstracoes is not None


def test_carregar_arquivo_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        carregar(tmp_path / "nao_existe.yaml")


def test_projeto_salvo_roda_a_analise_historica(projeto):
    """O historico restaurado precisa alimentar a analise como o original."""
    from valuation.historico import analisar

    volta = desserializar(serializar(projeto))
    original = analisar(projeto.demonstracoes)
    restaurada = analisar(volta.demonstracoes)
    pd.testing.assert_frame_equal(
        restaurada.indicadores, original.indicadores, check_names=False
    )


def test_o_ticker_escolhido_volta_com_o_projeto(empresa_exemplo, tmp_path):
    """Escolher o papel uma vez tem de bastar.

    O cadastro da CVM nao traz ticker e a busca por nome acha so 40% das
    companhias -- perder a escolha ao salvar e reabrir custaria a digitacao
    inteira de novo, justamente nas 60% em que a busca nao ajuda.
    """
    projeto = Projeto(
        empresa=empresa_exemplo,
        config={"tipo_fluxo": "fcff", "ticker": "WEGE3.SA"},
    )
    caminho = tmp_path / "com_ticker.yaml"
    salvar(projeto, caminho)

    assert carregar(caminho).config["ticker"] == "WEGE3.SA"


def test_o_preco_pedido_volta_com_o_projeto(empresa_exemplo, tmp_path):
    """Sem ele, reabrir um valuation deixava tres telas em branco.

    Margem de seguranca, retorno esperado naquele preco e multiplos de mercado
    fazem a mesma pergunta a partir do mesmo numero -- e ele nao era salvo.
    """
    projeto = Projeto(
        empresa=empresa_exemplo,
        config={
            "preco_pedido": {
                "valor": 49.27,
                "por_acao": True,
                "ticker": "WEGE3.SA",
                "em": "2026-08-21",
            }
        },
    )
    caminho = tmp_path / "com_preco.yaml"
    salvar(projeto, caminho)

    volta = carregar(caminho).config["preco_pedido"]
    assert volta["valor"] == pytest.approx(49.27)
    assert volta["ticker"] == "WEGE3.SA"
    assert volta["em"] == "2026-08-21"
