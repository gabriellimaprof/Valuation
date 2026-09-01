"""Varios valuations lado a lado.

A regra que estrutura este arquivo: **o que se compara entre negocios diferentes
e a distancia entre a premissa e o que aquela companhia entregou**, e nao o nivel
da premissa. Margem de 22% numa varejista e de 31% numa geradora nao se comparam;
"projetou 3 pontos acima do que entregou" e "projetou 1 ponto abaixo" se comparam.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from valuation.carteira import Carteira, ModeloNaMesa, montar, por_na_mesa
from valuation.importacao import Demonstracoes
from valuation.projeto import Projeto


def _historico(receitas, margem=0.20, capex=0.05):
    """Companhia com historico legivel, para a mediana existir."""
    anos = [2022, 2023, 2024, 2025]
    valores = pd.DataFrame(
        {
            ano: {
                "receita_liquida": receitas[i],
                "custo_produtos_vendidos": receitas[i] * 0.6,
                "ebit": receitas[i] * margem * 0.7,
                "depreciacao_amortizacao": receitas[i] * margem * 0.3,
                "capex": receitas[i] * capex,
                "contas_receber": receitas[i] * 0.2,
                "estoques": receitas[i] * 0.15,
                "fornecedores": receitas[i] * 0.1,
                "ativo_total": receitas[i] * 1.2,
                "patrimonio_liquido": receitas[i] * 0.5,
                "lucro_liquido": receitas[i] * 0.1,
                "lucro_antes_impostos": receitas[i] * 0.14,
                "impostos": receitas[i] * 0.04,
            }
            for i, ano in enumerate(anos)
        }
    )
    return Demonstracoes(empresa="T", valores=valores, unidade="R$ milhões")


def _projeto(empresa_exemplo, nome, receitas, **premissas):
    from valuation.modelo import substituir_varios

    empresa = replace(empresa_exemplo, nome=nome, unidade="R$ milhões")
    if premissas:
        empresa = substituir_varios(empresa, premissas)
    return Projeto(empresa=empresa, demonstracoes=_historico(receitas))


def test_a_distancia_e_o_que_atravessa_companhias(empresa_exemplo):
    """Projetado e entregue so se comparam dentro da mesma companhia.

    A tabela publica os tres numeros — projetado, entregue e a distancia — e a
    terceira e a unica que se le na horizontal. Mostrar as outras duas e o que
    permite conferi-la.
    """
    carteira = montar(
        [
            _projeto(empresa_exemplo, "Cresce muito", [100.0, 130.0, 170.0, 220.0]),
            _projeto(empresa_exemplo, "Cresce pouco", [100.0, 102.0, 104.0, 106.0]),
        ]
    )

    premissas = carteira.premissas()
    assert "Cresce muito - projetado" in premissas.columns
    assert "Cresce muito - entregue" in premissas.columns
    assert "Cresce muito - distancia" in premissas.columns

    distancias = carteira.distancias()
    assert list(distancias.columns) == ["Cresce muito", "Cresce pouco"]

    # A mesma premissa projetada nas duas: quem entregou menos tem a maior
    # distancia. E isso que a tabela existe para mostrar.
    linha = distancias.loc["Crescimento da receita"]
    assert linha["Cresce pouco"] > linha["Cresce muito"]


def test_a_leitura_aponta_onde_olhar_e_nao_o_que_concluir(empresa_exemplo):
    """Sem ranking e sem veredito: o modelo que mais pede melhora, e a perna."""
    carteira = montar(
        [
            _projeto(empresa_exemplo, "Conservador", [100.0, 130.0, 170.0, 220.0]),
            _projeto(empresa_exemplo, "Otimista", [100.0, 95.0, 92.0, 90.0]),
        ]
    )

    frases = " ".join(carteira.leitura())
    assert "Otimista" in frases
    # Nomeia a premissa que mais se afasta, com os dois numeros que a sustentam.
    assert "projetado contra" in frases
    # E nao ordena nem recomenda. ("melhora" e legitimo e contem "melhor",
    # entao o que se procura e a linguagem de ranking, e nao a substring.)
    for veredito in ("mais barat", "mais atrativ", "recomend", "compre", "prefira"):
        assert veredito not in frases.lower(), f"a mesa nao conclui: {veredito!r}"


def test_modelo_derivado_do_historico_tem_distancia_zero_e_isso_e_um_achado(
    empresa_exemplo,
):
    """Distância zero é informação, e não a ausência dela.

    Modelo derivado do histórico pelo botão tem premissa igual à mediana
    entregue **por construção**. Dizer isso é útil: significa que ninguém
    afirmou nada sobre mudança ainda, e que o valor na tela é extrapolação e não
    tese.
    """
    from valuation.historico import analisar, sugerir_premissas
    from valuation.modelo import Empresa
    from valuation.premissas import PremissasMacro, PremissasPerpetuidade

    projetos = []
    for nome, receitas in (("A", [100.0, 110.0, 121.0, 133.0]), ("B", [200.0, 210.0, 220.0, 231.0])):
        dfs = _historico(receitas)
        s = sugerir_premissas(analisar(dfs))
        empresa = Empresa(
            nome=nome,
            operacionais=s.operacionais,
            ponte=s.ponte,
            custo_capital=s.custo_capital,
            macro=PremissasMacro(),
            perpetuidade=PremissasPerpetuidade(),
            unidade=dfs.unidade,
        )
        projetos.append(Projeto(empresa=empresa, demonstracoes=dfs))

    carteira = montar(projetos)
    frases = " ".join(carteira.leitura())
    assert "extrapolação" in frases


def test_a_mesa_avisa_quando_as_unidades_nao_batem(empresa_exemplo):
    """Um modelo em R$ mil ao lado de um em R$ milhões se lê errado por mil vezes.

    E aviso e não recusa: as colunas em percentual continuam comparáveis, e
    sumir com a tabela inteira por causa das colunas de valor tiraria a
    comparação que funciona junto com a que não funciona.
    """
    a = _projeto(empresa_exemplo, "Em milhões", [100.0, 110.0, 121.0, 133.0])
    b = _projeto(empresa_exemplo, "Em mil", [100.0, 110.0, 121.0, 133.0])
    b = Projeto(
        empresa=replace(b.empresa, unidade="R$ mil"), demonstracoes=b.demonstracoes
    )

    carteira = montar([a, b])
    assert carteira.mistura_unidades
    assert "unidades diferentes" in " ".join(carteira.leitura())
    # A tabela continua existindo.
    assert not carteira.distancias().empty


def test_projeto_quebrado_nao_derruba_a_mesa(empresa_exemplo):
    """A mesma regra de `biblioteca.listar`: o problema aparece, a lista fica.

    Um valuation com premissa impossível no meio da comparação não pode levar os
    outros junto — quem olha precisa ver os que funcionam e o que quebrou.
    """
    from valuation.modelo import substituir_varios

    bom = _projeto(empresa_exemplo, "Bom", [100.0, 110.0, 121.0, 133.0])
    # g acima do WACC: combinacao economicamente impossivel.
    quebrado = Projeto(
        empresa=substituir_varios(
            replace(empresa_exemplo, nome="Quebrado"),
            {"perpetuidade.crescimento_perpetuo": 0.90},
        )
    )

    carteira = montar([bom, quebrado])
    assert len(carteira) == 2
    assert len(carteira.legiveis) == 1
    ruim = next(m for m in carteira.modelos if not m.legivel)
    assert ruim.nome == "Quebrado"
    assert ruim.erro


def test_a_margem_de_seguranca_fica_vazia_sem_preco(empresa_exemplo):
    """Zero significaria "está no preço justo", que é uma afirmação.

    O app não busca cotação sozinho, então sem preço informado a coluna tem de
    ficar vazia — e não zerada.
    """
    modelo = por_na_mesa(_projeto(empresa_exemplo, "Sem preço", [100.0, 110.0, 121.0, 133.0]))
    assert modelo.legivel
    assert pd.isna(modelo.margem_de_seguranca)


def test_o_otimismo_nao_e_nota():
    """Contagem acompanhada das distâncias, e nunca sozinha.

    Pontuar de 1 a 5 converteria julgamento em número — a mesma decisão já
    tomada em `qualitativo.py`. Este teste reprova quem acrescentar `nota` ou
    `ranking` à mesa, como o de lá faz.
    """
    campos = set(ModeloNaMesa.__dataclass_fields__) | set(dir(ModeloNaMesa))
    assert not {"nota", "score", "ranking", "posicao"} & campos

    campos_carteira = set(Carteira.__dataclass_fields__) | set(dir(Carteira))
    assert not {"nota", "score", "ranking", "ordenar_por_atratividade"} & campos_carteira


def test_uma_mesa_com_um_modelo_so_nao_tem_leitura(empresa_exemplo):
    """Comparação precisa de dois. Com um, a frase seria sobre nada."""
    carteira = montar([_projeto(empresa_exemplo, "Único", [100.0, 110.0, 121.0, 133.0])])
    assert carteira.leitura() == []
    assert not carteira.resumo().empty


def test_a_tela_de_comparar_diz_quando_a_biblioteca_esta_desligada(monkeypatch):
    """A biblioteca nasce desligada, e a tela não pode prometer o que não entrega.

    É a mesma propriedade que o botão de salvar já tem: quando desligada, ela
    diz o que falta em vez de existir vazia ou estourar.
    """
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("VALUATION_BIBLIOTECA", raising=False)

    def rodar():
        from app.paginas import comparar

        comparar.render()

    teste = AppTest.from_function(rodar, default_timeout=30)
    teste.run()

    assert not teste.exception
    texto = " ".join(i.value for i in teste.info)
    assert "desligada" in texto
    assert "VALUATION_BIBLIOTECA" in texto


def test_a_mesa_avisa_quando_os_perfis_nao_se_comparam(empresa_exemplo, monkeypatch):
    """Pôr uma varejista ao lado de um banco sugere uma comparação que os
    números não sustentam.

    A mesa usa o critério de `pares.py` — risco, crescimento e fluxo de caixa
    parecidos — para qualificar a si mesma. Medida a distância entre 6.780 pares
    quaisquer do universo: mediana 1,26 e **P90 em 5,01**, que é o corte. Os
    pares mais próximos da WEG ficam entre 0,28 e 0,41, uma ordem de grandeza
    abaixo.
    """
    import numpy as np

    from valuation import carteira as mod

    a = _projeto(empresa_exemplo, "Indústria", [100.0, 110.0, 121.0, 133.0])
    b = _projeto(empresa_exemplo, "Outra coisa", [100.0, 110.0, 121.0, 133.0])
    mesa = montar([a, b])

    longe = pd.DataFrame(
        [[np.nan, 9.0], [9.0, np.nan]],
        index=["Indústria", "Outra coisa"],
        columns=["Indústria", "Outra coisa"],
    )
    monkeypatch.setattr(mod.Carteira, "proximidade", lambda self: longe)

    frases = " ".join(mesa.leitura())
    assert "perfis econômicos distantes" in frases
    # Traz o numero, porque "distantes" sem tamanho nao ajuda a decidir.
    assert "9.0" in frases or "9,0" in frases
    # E nao manda descartar a mesa: a distancia para o proprio historico continua.
    assert "continua valendo" in frases


def test_sem_universo_a_proximidade_fica_vazia_em_vez_de_inventar(
    empresa_exemplo, monkeypatch
):
    """Distância sem escala não quer dizer nada.

    O z-score precisa da mediana e do IQR da base; sem o universo construído,
    somar dimensões de unidades diferentes produziria um número com aparência de
    medida.
    """
    from valuation import pares

    monkeypatch.setattr(pares, "universo_mais_proximo", lambda anos: None)
    mesa = montar(
        [
            _projeto(empresa_exemplo, "A", [100.0, 110.0, 121.0, 133.0]),
            _projeto(empresa_exemplo, "B", [200.0, 210.0, 220.0, 231.0]),
        ]
    )
    assert mesa.proximidade().empty
    # E a leitura continua funcionando, sem a frase de proximidade.
    assert "perfis econômicos distantes" not in " ".join(mesa.leitura())
