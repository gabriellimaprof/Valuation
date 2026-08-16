"""Biblioteca local de valuations: uma pasta de arquivos, na maquina do usuario.

O app nao grava nada em disco por decisao de arquitetura -- sem estado local, o
mesmo codigo roda no laptop do analista e num servidor compartilhado sem que
dados de um cliente vaguem para a sessao de outro. Essa propriedade e o que
permite publicar o app sem revisar o codigo inteiro antes.

Uma biblioteca contradiz isso, e por isso ela **nasce desligada**. So existe
quando ``VALUATION_BIBLIOTECA`` aponta para uma pasta, o que e uma escolha
deliberada de quem roda o app na propria maquina. Num deploy, a variavel
simplesmente nao e definida e o app continua sem estado -- nao ha caminho de
codigo em que um servidor comece a guardar valuations por acidente.

O formato e o mesmo ``.yaml`` de ``projeto.py``: a biblioteca e uma pasta de
arquivos que o usuario pode versionar, copiar ou abrir num editor. Nao ha banco,
indice nem formato proprio para migrar depois.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .projeto import Projeto, carregar, salvar as salvar_projeto

VARIAVEL = "VALUATION_BIBLIOTECA"
EXTENSAO = ".yaml"

_INVALIDO = re.compile(r"[^a-z0-9]+")


class BibliotecaDesligada(RuntimeError):
    """A biblioteca foi usada sem que ``VALUATION_BIBLIOTECA`` estivesse definida."""


def diretorio() -> Path | None:
    """Pasta da biblioteca, ou ``None`` quando ela esta desligada."""
    bruto = os.environ.get(VARIAVEL, "").strip()
    if not bruto:
        return None
    return Path(bruto).expanduser()


def esta_ligada() -> bool:
    return diretorio() is not None


def _exigir_diretorio(criar: bool = False) -> Path:
    caminho = diretorio()
    if caminho is None:
        raise BibliotecaDesligada(
            f"A biblioteca esta desligada. Defina {VARIAVEL} com a pasta onde "
            "guardar os valuations."
        )
    if criar:
        caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def nome_de_arquivo(empresa: str) -> str:
    """Nome de arquivo seguro a partir do nome da empresa.

    Sanitizar nao e zelo: o nome vem de um campo livre, e sem isso uma empresa
    chamada ``../config`` escreveria fora da pasta da biblioteca.
    """
    texto = unicodedata.normalize("NFKD", empresa or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    limpo = _INVALIDO.sub("_", texto).strip("_")
    return (limpo or "valuation") + EXTENSAO


@dataclass(frozen=True)
class Entrada:
    """Um valuation guardado, descrito sem precisar carrega-lo inteiro."""

    caminho: Path
    empresa: str
    anos: tuple[int, ...]
    unidade: str
    atualizado_em: datetime
    erro: str = ""

    @property
    def nome_do_arquivo(self) -> str:
        return self.caminho.name

    @property
    def periodo(self) -> str:
        if not self.anos:
            return "sem histórico"
        return f"{self.anos[0]}–{self.anos[-1]}"

    @property
    def legivel(self) -> bool:
        return not self.erro


def _descrever(caminho: Path) -> Entrada:
    """Le so o suficiente para listar, sem validar o modelo inteiro.

    Listar nao pode depender de o arquivo ser valido: um valuation salvo por uma
    versao futura, ou editado a mao ate quebrar, precisa aparecer na lista com o
    problema visivel -- e nao sumir dela.
    """
    atualizado = datetime.fromtimestamp(caminho.stat().st_mtime)
    try:
        dados: Any = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as erro:
        return Entrada(caminho, caminho.stem, (), "", atualizado, str(erro))

    if not isinstance(dados, dict):
        return Entrada(
            caminho, caminho.stem, (), "", atualizado, "conteúdo não é um mapeamento"
        )

    empresa = dados.get("empresa") or {}
    demonstracoes = dados.get("demonstracoes") or {}
    anos = tuple(int(a) for a in (demonstracoes.get("anos") or []))
    return Entrada(
        caminho=caminho,
        empresa=str(empresa.get("nome") or caminho.stem),
        anos=anos,
        unidade=str(demonstracoes.get("unidade") or empresa.get("unidade") or ""),
        atualizado_em=atualizado,
    )


def listar() -> list[Entrada]:
    """Valuations guardados, do mais recente para o mais antigo."""
    pasta = diretorio()
    if pasta is None or not pasta.is_dir():
        return []
    entradas = [_descrever(c) for c in pasta.glob(f"*{EXTENSAO}") if c.is_file()]
    return sorted(entradas, key=lambda e: e.atualizado_em, reverse=True)


def guardar(projeto: Projeto, nome_arquivo: str | None = None) -> Path:
    """Grava o projeto na biblioteca e devolve o caminho."""
    pasta = _exigir_diretorio(criar=True)
    nome = nome_arquivo or nome_de_arquivo(projeto.empresa.nome)
    if not nome.endswith(EXTENSAO):
        nome += EXTENSAO
    # ``Path(nome).name`` descarta qualquer diretorio que venha embutido no nome.
    return salvar_projeto(projeto, pasta / Path(nome).name)


def abrir(caminho: str | Path) -> Projeto:
    """Carrega um valuation da biblioteca, recusando caminho de fora dela."""
    pasta = _exigir_diretorio()
    alvo = Path(caminho).expanduser().resolve()
    if pasta.resolve() not in alvo.parents:
        raise ValueError(f"{alvo} nao esta na biblioteca ({pasta}).")
    return carregar(alvo)


def excluir(caminho: str | Path) -> None:
    """Apaga um valuation da biblioteca."""
    pasta = _exigir_diretorio()
    alvo = Path(caminho).expanduser().resolve()
    if pasta.resolve() not in alvo.parents:
        raise ValueError(f"{alvo} nao esta na biblioteca ({pasta}).")
    alvo.unlink(missing_ok=True)
