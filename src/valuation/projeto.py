"""Salvar e retomar um valuation inteiro em um unico arquivo de texto.

Um valuation nao se faz em uma sentada. Sem isto, fechar a aba do navegador
significa refazer a importacao das demonstracoes, reescrever as premissas e
redigitar os comparaveis -- e o app deixa de servir para trabalho de verdade.

O arquivo guarda **tudo que descreve a analise**: premissas, demonstracoes
importadas, comparaveis e as convencoes de calculo. Em YAML, de proposito: da
para abrir num editor, revisar em pull request, comparar duas versoes de um
mesmo valuation com um diff e reproduzir o numero meses depois. Um formato
binario seria menor e inutil para tudo isso.

O campo ``versao`` existe para que um arquivo salvo hoje continue legivel quando
o formato mudar. Arquivo de versao desconhecida e recusado com mensagem clara,
em vez de ser lido pela metade.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .entrada import construir_empresa
from .importacao import Demonstracoes, LinhaNaoReconhecida
from .multiplos import Alvo, Comparavel
from .premissas import Empresa

VERSAO = 1
# Lista branca de proposito: o `config` da sessao acumula estado de interface, e
# serializar tudo gravaria lixo no arquivo do usuario. Cada chave aqui e uma
# decisao que o valuation carrega.
#
# `ticker` entrou porque o cadastro da CVM **nao traz o papel** e a busca por
# nome acha so 40% das companhias: perder a escolha ao salvar custaria a
# digitacao inteira de novo, justamente nas 60% em que a busca nao ajuda.
CHAVES_CONFIG = (
    "meio_de_ano",
    "tipo_fluxo",
    "setor",
    "pais",
    "ticker",
    # O preco pedido, com data e origem. Sem ele, reabrir um valuation perdia a
    # margem de seguranca, o retorno esperado e os multiplos de mercado -- tres
    # telas em branco por um numero de uma linha.
    "preco_pedido",
)


@dataclass(frozen=True)
class Projeto:
    """Uma analise completa: premissas, dados, comparaveis e convencoes."""

    empresa: Empresa
    demonstracoes: Demonstracoes | None = None
    comparaveis: list[Comparavel] = field(default_factory=list)
    alvo: Alvo | None = None
    config: dict[str, Any] = field(default_factory=dict)


def _limpar(valor: Any) -> Any:
    """Converte tipos do numpy/pandas para tipos nativos que o YAML entende.

    Sem isto, um ``numpy.float64`` vindo de uma planilha importada seria
    serializado como um objeto Python arbitrario, e o arquivo salvo so poderia
    ser lido de volta com ``yaml.unsafe_load`` -- que nao e algo para se apontar
    a um arquivo que veio de outra pessoa.
    """
    if isinstance(valor, dict):
        return {_limpar(chave): _limpar(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpar(item) for item in valor]
    if isinstance(valor, (np.integer,)):
        return int(valor)
    if isinstance(valor, (np.floating,)):
        return float(valor)
    if isinstance(valor, np.ndarray):
        return [_limpar(item) for item in valor.tolist()]
    return valor


def _demonstracoes_para_dados(dfs: Demonstracoes) -> dict[str, Any]:
    dados: dict[str, Any] = {
        "empresa": dfs.empresa,
        "unidade": dfs.unidade,
        "moeda": dfs.moeda,
        "origem": dfs.origem,
        "anos": [int(ano) for ano in dfs.anos],
        "valores": {
            str(conta): {
                int(ano): (None if pd.isna(valor) else float(valor))
                for ano, valor in linha.items()
            }
            for conta, linha in dfs.valores.iterrows()
        },
        "mapeamento": dict(dfs.mapeamento),
        "derivadas": dict(dfs.derivadas),
    }
    if dfs.fonte:
        dados["fonte"] = dict(dfs.fonte)
    # A arvore publicada e a parte que explica de onde vem cada total. Sem ela
    # no arquivo, retomar um valuation devolveria as contas do modelo e perderia
    # a quebra -- que e justamente o que o analista abre para entender o numero.
    if dfs.detalhe is not None and not dfs.detalhe.empty:
        dados["detalhe"] = [
            {
                "codigo": str(linha["codigo"]),
                "rotulo": str(linha["rotulo"]),
                "demonstracao": str(linha["demonstracao"]),
                "valores": {
                    int(ano): (None if pd.isna(linha[ano]) else float(linha[ano]))
                    for ano in dfs.detalhe.columns
                    if isinstance(ano, int)
                },
            }
            for _, linha in dfs.detalhe.iterrows()
        ]
    # As linhas nao reconhecidas sao o que a tela de conferencia oferece para o
    # usuario corrigir a mao. Sem elas no arquivo, retomar um valuation salvo
    # devolvia os numeros mas nao a possibilidade de mexer neles -- e uma
    # importacao da CVM chega a ter mais de 250.
    if dfs.nao_reconhecidas:
        dados["nao_reconhecidas"] = [
            {
                "rotulo": linha.rotulo,
                "aba": linha.aba,
                "melhor_palpite": linha.melhor_palpite,
                "confianca": float(linha.confianca),
            }
            for linha in dfs.nao_reconhecidas
        ]
    if dfs.avisos:
        dados["avisos"] = list(dfs.avisos)
    return dados


def _dados_para_demonstracoes(dados: dict[str, Any]) -> Demonstracoes:
    anos = [int(ano) for ano in dados.get("anos", [])]
    valores = dados.get("valores") or {}
    if not anos or not valores:
        raise ValueError(
            "O bloco 'demonstracoes' esta sem anos ou sem contas. "
            "Remova-o do arquivo se nao houver historico."
        )

    tabela = pd.DataFrame(
        {
            ano: {
                conta: (
                    np.nan
                    if linha.get(ano) is None
                    else float(linha.get(ano, np.nan))
                )
                for conta, linha in valores.items()
            }
            for ano in anos
        },
        columns=anos,
    )
    return Demonstracoes(
        empresa=dados.get("empresa", ""),
        valores=tabela,
        origem=dados.get("origem", ""),
        unidade=dados.get("unidade", "unidades monetarias"),
        moeda=dados.get("moeda", "BRL"),
        mapeamento=dict(dados.get("mapeamento") or {}),
        derivadas=dict(dados.get("derivadas") or {}),
        nao_reconhecidas=[
            LinhaNaoReconhecida(
                rotulo=str(linha.get("rotulo", "")),
                aba=str(linha.get("aba", "")),
                melhor_palpite=linha.get("melhor_palpite"),
                confianca=float(linha.get("confianca", 0.0)),
            )
            for linha in (dados.get("nao_reconhecidas") or [])
        ],
        avisos=[str(a) for a in (dados.get("avisos") or [])],
        fonte=dict(dados.get("fonte") or {}),
        detalhe=_dados_para_detalhe(dados.get("detalhe")),
    )


def _dados_para_detalhe(linhas: Any) -> pd.DataFrame | None:
    """Reconstroi a arvore publicada, com nivel e ordem derivados do codigo."""
    if not linhas:
        return None

    from .importacao.cvm import _ordem_do_codigo

    registros = []
    for linha in linhas:
        codigo = str(linha.get("codigo", ""))
        registro: dict[str, Any] = {
            "codigo": codigo,
            "rotulo": str(linha.get("rotulo", "")),
            "demonstracao": str(linha.get("demonstracao", "")),
            "nivel": codigo.count(".") + 1,
            "ordem": _ordem_do_codigo(codigo),
        }
        for ano, valor in (linha.get("valores") or {}).items():
            registro[int(ano)] = np.nan if valor is None else float(valor)
        registros.append(registro)
    return pd.DataFrame(registros)


def serializar(projeto: Projeto) -> str:
    """Converte o projeto em texto YAML."""
    dados: dict[str, Any] = {
        "versao": VERSAO,
        "empresa": _limpar(dataclasses.asdict(projeto.empresa)),
    }
    if projeto.config:
        dados["config"] = _limpar(
            {c: projeto.config[c] for c in CHAVES_CONFIG if c in projeto.config}
        )
    if projeto.demonstracoes is not None and projeto.demonstracoes.anos:
        dados["demonstracoes"] = _limpar(
            _demonstracoes_para_dados(projeto.demonstracoes)
        )
    if projeto.comparaveis:
        dados["comparaveis"] = [
            _limpar(dataclasses.asdict(c)) for c in projeto.comparaveis
        ]
    if projeto.alvo is not None:
        dados["alvo"] = _limpar(dataclasses.asdict(projeto.alvo))

    return yaml.safe_dump(
        dados, allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def desserializar(texto: str, origem: str = "<arquivo>") -> Projeto:
    """Reconstroi o projeto a partir do texto YAML."""
    try:
        dados = yaml.safe_load(texto)
    except yaml.YAMLError as erro:
        raise ValueError(f"'{origem}' nao e um YAML valido: {erro}") from erro

    if not isinstance(dados, dict):
        raise ValueError(f"'{origem}' deveria conter um mapeamento no nivel raiz.")

    versao = dados.get("versao")
    if versao is None:
        raise ValueError(
            f"'{origem}' nao declara 'versao'. Ele foi salvo por este app?"
        )
    if int(versao) > VERSAO:
        raise ValueError(
            f"'{origem}' foi salvo na versao {versao}, e este app entende ate a "
            f"versao {VERSAO}. Atualize o app para abrir este arquivo."
        )

    if "empresa" not in dados:
        raise ValueError(f"'{origem}' nao tem o bloco 'empresa'.")
    empresa = construir_empresa(dict(dados["empresa"]), origem=f"{origem}:empresa")

    demonstracoes = None
    if dados.get("demonstracoes"):
        demonstracoes = _dados_para_demonstracoes(dados["demonstracoes"])

    comparaveis = [
        Comparavel(**item) for item in (dados.get("comparaveis") or [])
    ]
    alvo = Alvo(**dados["alvo"]) if dados.get("alvo") else None

    config = {
        chave: valor
        for chave, valor in (dados.get("config") or {}).items()
        if chave in CHAVES_CONFIG
    }

    return Projeto(
        empresa=empresa,
        demonstracoes=demonstracoes,
        comparaveis=comparaveis,
        alvo=alvo,
        config=config,
    )


def salvar(projeto: Projeto, caminho: str | Path) -> Path:
    """Grava o projeto em disco."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(serializar(projeto), encoding="utf-8")
    return caminho


def carregar(caminho: str | Path) -> Projeto:
    """Le um projeto salvo em disco."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Projeto nao encontrado: {caminho}")
    return desserializar(caminho.read_text(encoding="utf-8"), origem=str(caminho))
