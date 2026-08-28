"""Testes da biblioteca local de valuations.

A regra que estrutura tudo aqui: a biblioteca nasce desligada. O app so grava
em disco quando alguem definiu ``VALUATION_BIBLIOTECA`` de proposito, para que
um deploy em servidor continue sem estado sem depender de ninguem lembrar disso.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from valuation.biblioteca import (
    VARIAVEL,
    BibliotecaDesligada,
    abrir,
    diretorio,
    esta_ligada,
    excluir,
    guardar,
    listar,
    nome_de_arquivo,
)
from valuation.projeto import Projeto


@pytest.fixture
def ligada(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(VARIAVEL, str(tmp_path / "valuations"))
    return tmp_path / "valuations"


@pytest.fixture
def desligada(monkeypatch) -> None:
    monkeypatch.delenv(VARIAVEL, raising=False)


@pytest.fixture
def projeto(empresa_exemplo) -> Projeto:
    return Projeto(empresa=empresa_exemplo)


# ---------------------------------------------------------------------------
# Ligada e desligada
# ---------------------------------------------------------------------------


def test_nasce_desligada(desligada):
    assert diretorio() is None
    assert esta_ligada() is False
    assert listar() == []


def test_desligada_recusa_gravar(desligada, projeto):
    with pytest.raises(BibliotecaDesligada, match=VARIAVEL):
        guardar(projeto)


def test_variavel_vazia_conta_como_desligada(monkeypatch, projeto):
    monkeypatch.setenv(VARIAVEL, "   ")
    assert esta_ligada() is False
    with pytest.raises(BibliotecaDesligada):
        guardar(projeto)


def test_til_e_expandido(monkeypatch):
    monkeypatch.setenv(VARIAVEL, "~/valuations")
    caminho = diretorio()
    assert caminho is not None
    assert "~" not in str(caminho)
    assert caminho.is_absolute()


# ---------------------------------------------------------------------------
# Guardar, listar, abrir, excluir
# ---------------------------------------------------------------------------


def test_guardar_cria_a_pasta_e_devolve_o_caminho(ligada, projeto):
    caminho = guardar(projeto)
    assert caminho.exists()
    assert caminho.parent == ligada
    assert caminho.suffix == ".yaml"


def test_ida_e_volta_pela_biblioteca(ligada, projeto):
    caminho = guardar(projeto)
    volta = abrir(caminho)
    assert volta.empresa == projeto.empresa


def test_listagem_descreve_sem_carregar_o_modelo(ligada, empresa_exemplo, demonstracoes):
    guardar(Projeto(empresa=empresa_exemplo, demonstracoes=demonstracoes))
    entradas = listar()

    assert len(entradas) == 1
    entrada = entradas[0]
    assert entrada.empresa == empresa_exemplo.nome
    assert entrada.anos == (2023, 2024)
    assert entrada.periodo == "2023–2024"
    assert entrada.legivel
    assert isinstance(entrada.atualizado_em, datetime)


def test_listagem_vem_do_mais_recente(ligada, empresa_exemplo):
    import os
    import time

    from dataclasses import replace

    guardar(Projeto(empresa=replace(empresa_exemplo, nome="Antiga")))
    time.sleep(0.01)
    caminho = guardar(Projeto(empresa=replace(empresa_exemplo, nome="Nova")))
    # mtime tem granularidade grossa em alguns sistemas; forca a ordem.
    os.utime(caminho, (time.time() + 10, time.time() + 10))

    assert [e.empresa for e in listar()] == ["Nova", "Antiga"]


def test_arquivo_quebrado_aparece_na_lista_com_o_erro(ligada, projeto):
    guardar(projeto)
    ligada.joinpath("quebrado.yaml").write_text("[isto: nao e", encoding="utf-8")

    entradas = {e.nome_do_arquivo: e for e in listar()}
    assert "quebrado.yaml" in entradas, "arquivo ilegivel nao pode sumir da lista"
    assert not entradas["quebrado.yaml"].legivel
    assert entradas["quebrado.yaml"].erro


def test_excluir_remove(ligada, projeto):
    caminho = guardar(projeto)
    excluir(caminho)
    assert not caminho.exists()
    assert listar() == []


def test_guardar_duas_vezes_sobrescreve(ligada, empresa_exemplo):
    from dataclasses import replace

    guardar(Projeto(empresa=empresa_exemplo))
    guardar(Projeto(empresa=replace(empresa_exemplo, unidade="R$ mil")))
    assert len(listar()) == 1, "mesmo nome deveria substituir, nao acumular"


# ---------------------------------------------------------------------------
# O nome do arquivo vem de campo livre
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "empresa,esperado",
    [
        ("WEG S.A.", "weg_s_a.yaml"),
        ("VIVARA PARTICIPAÇÕES S.A.", "vivara_participacoes_s_a.yaml"),
        ("São Martinho", "sao_martinho.yaml"),
        ("", "valuation.yaml"),
        ("///", "valuation.yaml"),
    ],
)
def test_nome_de_arquivo_e_seguro(empresa, esperado):
    assert nome_de_arquivo(empresa) == esperado


def test_nome_de_empresa_nao_escapa_da_pasta(ligada, empresa_exemplo):
    """O nome vem de campo livre: sem sanitizar, escreveria fora da biblioteca."""
    from dataclasses import replace

    caminho = guardar(Projeto(empresa=replace(empresa_exemplo, nome="../../fora")))
    assert caminho.parent == ligada
    assert ".." not in caminho.name


def test_nome_de_arquivo_explicito_nao_escapa(ligada, projeto):
    caminho = guardar(projeto, nome_arquivo="../../fora.yaml")
    assert caminho.parent == ligada
    assert caminho.name == "fora.yaml"


def test_abrir_fora_da_biblioteca_e_recusado(ligada, tmp_path, projeto):
    from valuation.projeto import salvar

    intruso = salvar(projeto, tmp_path / "fora" / "outro.yaml")
    with pytest.raises(ValueError, match="nao esta na biblioteca"):
        abrir(intruso)


def test_excluir_fora_da_biblioteca_e_recusado(ligada, tmp_path, projeto):
    from valuation.projeto import salvar

    intruso = salvar(projeto, tmp_path / "fora" / "outro.yaml")
    with pytest.raises(ValueError, match="nao esta na biblioteca"):
        excluir(intruso)
    assert intruso.exists(), "o arquivo de fora nao pode ter sido apagado"


def test_valuation_trimestral_nao_derruba_a_listagem(ligada, empresa_exemplo, demonstracoes):
    """Sétimo sítio de `int(ano)`, e este levava a lista inteira junto.

    Uma série trimestral salva grava `anos: ["1T25", ...]` — o rótulo, e não o
    exercício, porque converter faria 1T24, 2T24 e 3T24 colapsarem na mesma
    chave. `int(a)` na descrição estourava, o `ValueError` subia por `listar` e
    **nenhuma** entrada aparecia: o valuation anual guardado ao lado sumia da
    tela por causa do vizinho.

    É o oposto exato do que `_descrever` promete — arquivo que o app não entende
    aparece na lista com o problema visível, e não leva a lista consigo.
    """
    from dataclasses import replace

    guardar(Projeto(empresa=replace(empresa_exemplo, nome="Anual"), demonstracoes=demonstracoes))

    trimestral = demonstracoes.valores.rename(columns={2023: "1T25", 2024: "2T25"})
    guardar(
        Projeto(
            empresa=replace(empresa_exemplo, nome="Trimestral"),
            demonstracoes=replace(demonstracoes, valores=trimestral),
        )
    )

    entradas = {e.empresa: e for e in listar()}
    assert set(entradas) == {"Anual", "Trimestral"}, "uma entrada não pode derrubar a outra"
    assert entradas["Trimestral"].anos == ("1T25", "2T25")
    assert entradas["Trimestral"].periodo == "1T25–2T25"
    assert entradas["Anual"].anos == (2023, 2024), "o ano continua inteiro"
