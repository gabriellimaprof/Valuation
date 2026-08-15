"""Leitura de premissas a partir de arquivos YAML ou JSON.

O objetivo e que o modelo de cada empresa seja um arquivo de texto versionavel:
da para revisar em pull request, comparar duas versoes e reproduzir um valuation
meses depois. Chaves desconhecidas geram erro em vez de serem ignoradas -- em um
arquivo de premissas, um campo com nome errado e silenciosamente descartado e um
erro caro.

Comodidade de escrita: premissas anuais podem ser informadas como um unico
numero quando ``horizonte`` esta declarado no bloco ``operacionais``, e o valor
e replicado para todos os anos.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import yaml

from .multiplos import Alvo, Comparavel
from .sensibilidade import Distribuicao
from .premissas import (
    Empresa,
    PonteValor,
    PremissasCustoCapital,
    PremissasMacro,
    PremissasOperacionais,
    PremissasPerpetuidade,
)

_LISTAS_OPERACIONAIS = (
    "crescimento_receita",
    "margem_ebitda",
    "depreciacao_pct_receita",
    "capex_pct_receita",
    "capital_giro_pct_receita",
)


def carregar_dados(caminho: str | Path) -> dict[str, Any]:
    """Le um arquivo YAML ou JSON e devolve o dicionario cru."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de premissas nao encontrado: {caminho}")
    texto = caminho.read_text(encoding="utf-8")
    if caminho.suffix.lower() == ".json":
        dados = json.loads(texto)
    else:
        dados = yaml.safe_load(texto)
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho} deveria conter um mapeamento no nivel raiz.")
    return dados


def _construir(cls: type, dados: dict[str, Any], contexto: str) -> Any:
    """Instancia uma dataclass validando as chaves recebidas."""
    validos = {f.name for f in dataclasses.fields(cls)}
    desconhecidos = set(dados) - validos
    if desconhecidos:
        raise ValueError(
            f"Campos desconhecidos em '{contexto}': {sorted(desconhecidos)}. "
            f"Campos aceitos: {sorted(validos)}"
        )
    return cls(**dados)


def _expandir_operacionais(dados: dict[str, Any]) -> dict[str, Any]:
    """Replica premissas anuais escalares pelo ``horizonte`` declarado."""
    dados = dict(dados)
    horizonte = dados.pop("horizonte", None)
    for chave in _LISTAS_OPERACIONAIS:
        valor = dados.get(chave)
        if valor is None or isinstance(valor, list):
            continue
        if horizonte is None:
            raise ValueError(
                f"'{chave}' foi informado como numero unico; declare 'horizonte' "
                "em operacionais para replicar o valor por todos os anos, ou "
                "escreva a lista completa."
            )
        dados[chave] = [float(valor)] * int(horizonte)

    if horizonte is not None:
        for chave in _LISTAS_OPERACIONAIS:
            valor = dados.get(chave)
            if isinstance(valor, list) and len(valor) != int(horizonte):
                raise ValueError(
                    f"'{chave}' tem {len(valor)} anos, mas horizonte={horizonte}."
                )
    return dados


@dataclasses.dataclass(frozen=True)
class ArquivoModelo:
    """Tudo que um arquivo de premissas pode declarar.

    Alem da empresa, o arquivo pode trazer a configuracao das analises que
    acompanham o valuation -- sensibilidade, cenarios e Monte Carlo -- de modo
    que a analise inteira fique versionada junto com as premissas.
    """

    empresa: Empresa
    sensibilidade: dict[str, Any] | None = None
    cenarios: dict[str, dict[str, float]] | None = None
    distribuicoes: list[Distribuicao] = dataclasses.field(default_factory=list)
    simulacoes: int = 10_000
    metrica_simulacao: str = "equity_value"


def carregar_empresa(caminho: str | Path) -> Empresa:
    """Monta um objeto ``Empresa`` a partir do arquivo de premissas."""
    return carregar_modelo(caminho).empresa


def carregar_modelo(caminho: str | Path) -> ArquivoModelo:
    """Le o arquivo completo: empresa e configuracao das analises."""
    dados = carregar_dados(caminho)
    origem = str(caminho)

    bloco_sens = dados.pop("sensibilidade", None)
    bloco_cen = dados.pop("cenarios", None)
    bloco_sim = dados.pop("simulacao", None) or {}

    if bloco_sens is not None:
        for eixo in ("linhas", "colunas"):
            if eixo not in bloco_sens:
                raise ValueError(
                    f"'{origem}:sensibilidade' precisa dos eixos 'linhas' e 'colunas'."
                )
            if "caminho" not in bloco_sens[eixo] or "valores" not in bloco_sens[eixo]:
                raise ValueError(
                    f"'{origem}:sensibilidade:{eixo}' precisa de 'caminho' e 'valores'."
                )

    desconhecidos_sim = set(bloco_sim) - {"simulacoes", "metrica", "distribuicoes"}
    if desconhecidos_sim:
        raise ValueError(
            f"Campos desconhecidos em '{origem}:simulacao': {sorted(desconhecidos_sim)}"
        )
    distribuicoes = [
        _construir(Distribuicao, item, f"{origem}:simulacao:distribuicoes[{i}]")
        for i, item in enumerate(bloco_sim.get("distribuicoes", []))
    ]

    return ArquivoModelo(
        empresa=construir_empresa(dados, origem=origem),
        sensibilidade=bloco_sens,
        cenarios=bloco_cen,
        distribuicoes=distribuicoes,
        simulacoes=int(bloco_sim.get("simulacoes", 10_000)),
        metrica_simulacao=bloco_sim.get("metrica", "equity_value"),
    )


def construir_empresa(dados: dict[str, Any], origem: str = "<dados>") -> Empresa:
    """Monta uma ``Empresa`` a partir do dicionario ja carregado."""
    dados = dict(dados)
    blocos = {
        "macro": PremissasMacro,
        "custo_capital": PremissasCustoCapital,
        "perpetuidade": PremissasPerpetuidade,
        "ponte": PonteValor,
    }
    montados: dict[str, Any] = {}
    for chave, cls in blocos.items():
        bruto = dados.pop(chave, None)
        if bruto is not None:
            montados[chave] = _construir(cls, bruto, f"{origem}:{chave}")

    operacionais = dados.pop("operacionais", None)
    if operacionais is not None:
        montados["operacionais"] = _construir(
            PremissasOperacionais,
            _expandir_operacionais(operacionais),
            f"{origem}:operacionais",
        )

    restantes = {
        chave: dados[chave]
        for chave in ("nome", "data_base", "moeda", "unidade")
        if chave in dados
    }
    desconhecidos = set(dados) - set(restantes)
    if desconhecidos:
        raise ValueError(
            f"Blocos desconhecidos em '{origem}': {sorted(desconhecidos)}. "
            "Blocos aceitos: ['nome', 'data_base', 'moeda', 'unidade', 'macro', "
            "'custo_capital', 'operacionais', 'perpetuidade', 'ponte']"
        )
    if "nome" not in restantes:
        raise ValueError(f"'{origem}' precisa declarar 'nome'.")

    return Empresa(**restantes, **montados)


def carregar_comparaveis(caminho: str | Path) -> tuple[Alvo, list[Comparavel]]:
    """Le um arquivo com o bloco ``alvo`` e a lista ``comparaveis``."""
    dados = carregar_dados(caminho)
    if "alvo" not in dados or "comparaveis" not in dados:
        raise ValueError(
            f"{caminho} precisa dos blocos 'alvo' e 'comparaveis'."
        )
    alvo = _construir(Alvo, dados["alvo"], f"{caminho}:alvo")
    comparaveis = [
        _construir(Comparavel, item, f"{caminho}:comparaveis[{i}]")
        for i, item in enumerate(dados["comparaveis"])
    ]
    if not comparaveis:
        raise ValueError(f"{caminho} nao tem nenhum comparavel.")
    return alvo, comparaveis
