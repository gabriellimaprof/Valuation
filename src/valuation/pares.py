"""Peer group por perfil economico, em vez de por rotulo de setor.

O problema que isto resolve
---------------------------

O peer group do app saia do ``SETOR_ATIV`` do cadastro da CVM, que e uma
**classificacao de registro**: serve para a autarquia organizar quem protocola o
que. Ela emparelha a WEG com a Plascar porque as duas se registraram como
"Maquinas, Equipamentos, Veiculos e Pecas" -- uma fabrica motores eletricos com
ROIC de 38%, a outra faz autopecas e da prejuizo. Multiplo tirado dai nao
compara nada.

O criterio aqui e o do Damodaran: **comparavel e a empresa com risco,
crescimento e fluxo de caixa parecidos**, e nao a que vende coisa parecida.
Esses tres se medem, entao da para procurar por eles.

Como a distancia e calculada
----------------------------

Cada dimensao vira z-score **robusto** -- mediana e intervalo interquartil, nao
media e desvio. A base da CVM tem margem de 300% e divida/EBITDA de 80: com
media e desvio, um punhado de casos extremos define a escala inteira e todo o
resto colapsa perto de zero.

A distancia e euclidiana sobre as dimensoes que **as duas** companhias tem, e
normalizada pela quantidade delas. Duas empresas comparadas em quatro dimensoes
nao podem parecer mais proximas do que duas comparadas em seis so porque
faltaram dados.

O que este modulo nao sabe
--------------------------

Que negocio a empresa faz. Uma concessionaria de rodovia e um gasoduto tem
margem alta, capex pesado, divida longa e crescimento vegetativo -- perfis
gemeos, negocios diferentes, regulacoes diferentes, riscos diferentes. O perfil
economico e ponto de partida para escolher comparaveis, nao o criterio final. A
tela diz isso; quem usar o modulo direto precisa saber tambem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# As seis dimensoes que descrevem a economia de um negocio. Nao ha preco aqui
# de proposito: comparavel se escolhe pelo negocio, e o preco e o que se vai
# comparar depois.
DIMENSOES: tuple[str, ...] = (
    "Margem EBITDA",
    "ROIC",
    "Giro do capital investido",
    "Capex / Receita",
    "Crescimento da receita",
    "Divida liquida / EBITDA",
    # Quanto do EBITDA e aluguel. Sem esta dimensao, o IFRS 16 emparelha errado:
    # a Smart Fit, com margem EBITDA de 48% inflada por aluguel, caia ao lado de
    # ferrovia e geradora de energia -- empresas de margem alta que sao donas do
    # ativo. Com ela, intensidade de aluguel vira eixo proprio e quem aluga fica
    # perto de quem aluga.
    "Aluguel / EBITDA",
)

# Fora desta razao de receita, a comparacao deixa de ser util mesmo com perfil
# parecido: escala muda poder de barganha, custo de capital e acesso a credito.
FAIXA_DE_PORTE = 10.0

COLUNAS_DE_IDENTIDADE = ("nome", "receita", "setor")

# Quantas das seis dimensoes precisam existir nas duas companhias para a
# comparacao valer. Medido na base: com tres, entram companhias sem margem e sem
# alavancagem que aparecem no topo do ranking por falta de dado, nao por
# semelhanca -- e quem le nao tem como perceber.
MINIMO_DE_DIMENSOES = 4


class UniversoVazio(ValueError):
    """Nao ha companhias suficientes para comparar."""


@dataclass(frozen=True)
class Universo:
    """Perfis economicos de um conjunto de companhias, prontos para comparar."""

    perfis: pd.DataFrame
    anos: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.perfis)

    @property
    def dimensoes(self) -> list[str]:
        return [d for d in DIMENSOES if d in self.perfis.columns]

    def escalas(self) -> pd.DataFrame:
        """Mediana e amplitude interquartil de cada dimensao.

        E o que transforma "margem de 20%" em "quao incomum e essa margem nesta
        base" -- sem isso, dimensoes com unidades diferentes nao somam.
        """
        dados = self.perfis[self.dimensoes].replace([np.inf, -np.inf], np.nan)
        q1 = dados.quantile(0.25)
        q3 = dados.quantile(0.75)
        amplitude = (q3 - q1).replace(0, np.nan)
        return pd.DataFrame({"centro": dados.median(), "escala": amplitude})


def perfil_de(analise) -> dict[str, float]:
    """As dimensoes do perfil, pela mediana historica de cada indicador.

    Mediana e nao ultimo ano: um comparavel escolhido pelo ano de uma greve ou
    de uma aquisicao e um comparavel escolhido pelo ruido.
    """
    perfil = {
        dimensao: analise.mediana(dimensao)
        for dimensao in DIMENSOES
        if dimensao in analise.indicadores.index
    }

    # "Sem aluguel" e "aluguel nao publicado" sao coisas diferentes, e so a
    # primeira e zero. Medido em 2024: 341 companhias tem passivo de
    # arrendamento no balanco e 308 delas publicam o desembolso na DFC. As 33
    # que tem o passivo e nao publicam o desembolso ficam sem a dimensao, e nao
    # com zero -- zero as faria parecer donas do ativo que alugam.
    if "Aluguel / EBITDA" not in perfil:
        d = analise.demonstracoes
        arrendamento = d.serie("arrendamento_curto_prazo").add(
            d.serie("arrendamento_longo_prazo"), fill_value=0
        )
        if not arrendamento.dropna().any():
            perfil["Aluguel / EBITDA"] = 0.0
    return perfil


def _padronizar(valores: pd.Series, escalas: pd.DataFrame) -> pd.Series:
    centro = escalas["centro"].reindex(valores.index)
    escala = escalas["escala"].reindex(valores.index)
    return (valores - centro) / escala


def distancia(
    perfil: dict[str, float] | pd.Series,
    outro: dict[str, float] | pd.Series,
    escalas: pd.DataFrame,
    minimo: int = 1,
) -> tuple[float, int]:
    """Distancia entre dois perfis e quantas dimensoes a sustentam.

    Normalizada pela raiz do numero de dimensoes usadas: sem isso, uma
    companhia que so publica tres delas apareceria artificialmente proxima de
    todo mundo. E devolve a contagem junto, porque distancia de 0,8 apoiada em
    tres dimensoes e distancia de 0,8 apoiada em seis nao sao a mesma coisa --
    quem le precisa poder separar as duas.
    """
    a = pd.Series(perfil, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    b = pd.Series(outro, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    comuns = [d for d in a.index if d in b.index and d in escalas.index]
    if not comuns:
        return float("nan"), 0

    za = _padronizar(a[comuns], escalas)
    zb = _padronizar(b[comuns], escalas)
    diferenca = (za - zb).dropna()
    if diferenca.empty or len(diferenca) < minimo:
        return float("nan"), len(diferenca)
    return float(np.sqrt((diferenca**2).sum() / len(diferenca))), len(diferenca)


def fora_de_porte(receita_alvo: float, receita_par: float, faixa: float = FAIXA_DE_PORTE) -> bool:
    """A diferenca de escala e grande demais para a comparacao valer?"""
    if not (np.isfinite(receita_alvo) and np.isfinite(receita_par)):
        return False
    if receita_alvo <= 0 or receita_par <= 0:
        return False
    razao = max(receita_alvo, receita_par) / min(receita_alvo, receita_par)
    return razao > faixa


def pares_proximos(
    perfil: dict[str, float],
    universo: Universo,
    quantos: int = 10,
    receita: float | None = None,
    faixa_de_porte: float | None = FAIXA_DE_PORTE,
    excluir: int | None = None,
    minimo_de_dimensoes: int = MINIMO_DE_DIMENSOES,
) -> pd.DataFrame:
    """Ordena o universo pela distancia ao perfil informado.

    Devolve, alem da distancia, **cada dimensao lado a lado** com a do alvo. Um
    ranking sem isso pede fe; com isso, quem le confere por que aquelas
    companhias apareceram e descarta as que nao fazem sentido.
    """
    if len(universo) < 2:
        raise UniversoVazio(
            "O universo tem menos de duas companhias; não há como comparar."
        )

    escalas = universo.escalas()
    dimensoes = universo.dimensoes
    linhas = []
    for codigo, registro in universo.perfis.iterrows():
        if excluir is not None and codigo == excluir:
            continue
        d, quantas = distancia(
            perfil, registro[dimensoes], escalas, minimo=minimo_de_dimensoes
        )
        if not np.isfinite(d):
            continue
        linha = {
            "Companhia": registro.get("nome", str(codigo)),
            "Distância": d,
            "Dimensões": quantas,
            "Receita": registro.get("receita", float("nan")),
            "Setor (cadastro)": registro.get("setor", ""),
            "codigo": codigo,
        }
        linha.update({dimensao: registro.get(dimensao, float("nan")) for dimensao in dimensoes})
        linhas.append(linha)

    if not linhas:
        raise UniversoVazio("Nenhuma companhia do universo tem dimensões em comum.")

    tabela = pd.DataFrame(linhas).set_index("Companhia").sort_values("Distância")

    if receita is not None and faixa_de_porte is not None:
        cabe = ~tabela["Receita"].apply(lambda r: fora_de_porte(receita, r, faixa_de_porte))
        tabela = tabela[cabe]

    return tabela.head(quantos)


def explicar(perfil: dict[str, float], par: pd.Series, universo: Universo) -> pd.DataFrame:
    """Dimensao a dimensao, o alvo contra o par e a distancia em cada uma.

    E a tabela que responde "por que esta empresa apareceu como comparavel", e
    a que permite discordar com argumento.
    """
    escalas = universo.escalas()
    linhas = []
    for dimensao in universo.dimensoes:
        alvo = perfil.get(dimensao, float("nan"))
        outro = par.get(dimensao, float("nan"))
        escala = escalas.loc[dimensao, "escala"] if dimensao in escalas.index else np.nan
        afastamento = (
            abs(alvo - outro) / escala
            if np.isfinite(alvo) and np.isfinite(outro) and np.isfinite(escala)
            else float("nan")
        )
        linhas.append(
            {
                "Dimensão": dimensao,
                "Alvo": alvo,
                "Par": outro,
                "Afastamento (em amplitudes)": afastamento,
            }
        )
    return pd.DataFrame(linhas).set_index("Dimensão")


# ---------------------------------------------------------------------------
# Construir e guardar o universo
# ---------------------------------------------------------------------------


def diretorio_cache() -> Path:
    return Path.home() / ".cache" / "valuation" / "universo"


def caminho_do_universo(anos: list[int]) -> Path:
    return diretorio_cache() / f"perfis_{anos[0]}_{anos[-1]}.csv"


def salvar_universo(universo: Universo, caminho: Path | None = None) -> Path:
    destino = Path(caminho or caminho_do_universo(universo.anos))
    destino.parent.mkdir(parents=True, exist_ok=True)
    universo.perfis.to_csv(destino, encoding="utf-8")
    return destino


def carregar_universo(anos: list[int], caminho: Path | None = None) -> Universo:
    """Le o universo ja construido. Levanta ``FileNotFoundError`` se nao existe."""
    origem = Path(caminho or caminho_do_universo(sorted(anos)))
    perfis = pd.read_csv(origem, index_col=0, encoding="utf-8")
    return Universo(perfis=perfis, anos=sorted(anos))


def construir_universo(
    anos: list[int],
    cache: Path | None = None,
    codigos: list[int] | None = None,
    progresso=None,
    indicadores_extra: tuple[str, ...] = (),
) -> Universo:
    """Importa as companhias e mede o perfil economico de cada uma.

    Usa o leitor auditado da CVM, uma companhia por vez, em vez de reler os
    arquivos em paralelo com uma logica propria. E lento -- minutos para a base
    inteira -- e e a escolha certa: uma segunda leitura dos mesmos arquivos
    divergiria da primeira no dia em que uma das duas mudasse, e a divergencia
    apareceria como peer group estranho, que ninguem liga a causa.

    Bancos e seguradoras ficam de fora: margem EBITDA e capex sobre receita nao
    querem dizer neles o que querem dizer no resto.

    ``indicadores_extra`` sao gravados junto sem entrar na distancia. Servem
    para calibrar cortes contra a base -- a mesma passada custosa responde
    "quem se parece com quem" e "onde ficam os cortes de verdade".
    """
    from .historico import analisar
    from .importacao.cvm import carregar_cadastro, importar_cvm, listar_companhias_do_ano

    anos = sorted(anos)
    cache = Path(cache) if cache else None
    catalogo = carregar_cadastro(cache / "cad_cia_aberta.csv") if cache else carregar_cadastro()
    por_codigo = {c.codigo_cvm: c for c in catalogo}
    alvos = codigos if codigos is not None else listar_companhias_do_ano(anos[-1], cache=cache)

    linhas = {}
    for i, codigo in enumerate(alvos, 1):
        if progresso is not None:
            progresso(i, len(alvos))
        try:
            dfs = importar_cvm(codigo, anos, cache=cache, catalogo=catalogo)
            if any("instituicao financeira" in aviso for aviso in dfs.avisos):
                continue
            analise = analisar(dfs)
        except Exception:
            continue

        perfil = perfil_de(analise)
        if len(perfil) < 3:
            continue
        registro = dict(perfil)
        for extra in indicadores_extra:
            registro[extra] = analise.mediana(extra)
        cadastro = por_codigo.get(codigo)
        registro["nome"] = dfs.empresa
        registro["setor"] = getattr(cadastro, "setor", "") or ""
        receita = dfs.serie("receita_liquida").dropna()
        registro["receita"] = float(receita.iloc[-1]) if not receita.empty else float("nan")
        linhas[codigo] = registro

    if not linhas:
        raise UniversoVazio("Nenhuma companhia pôde ser medida nos anos pedidos.")

    perfis = pd.DataFrame(linhas).T
    perfis.index.name = "codigo"
    ordem = (
        [d for d in DIMENSOES if d in perfis.columns]
        + [e for e in indicadores_extra if e in perfis.columns]
        + list(COLUNAS_DE_IDENTIDADE)
    )
    return Universo(perfis=perfis[[c for c in ordem if c in perfis.columns]], anos=anos)


# ---------------------------------------------------------------------------
# Linha de comando: construir o universo leva minutos e nao cabe num botao
# ---------------------------------------------------------------------------


def _principal(argumentos: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m valuation.pares",
        description="Constroi o universo de perfis economicos da base da CVM.",
    )
    parser.add_argument(
        "--anos",
        default="2020-2024",
        help="Intervalo de exercicios, como 2020-2024.",
    )
    parser.add_argument("--cache", default=None, help="Pasta do cache da CVM.")
    opcoes = parser.parse_args(argumentos)

    inicio, _, fim = opcoes.anos.partition("-")
    anos = list(range(int(inicio), int(fim or inicio) + 1))
    cache = Path(opcoes.cache) if opcoes.cache else None

    def progresso(i: int, total: int) -> None:
        if i % 25 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)

    print(f"Construindo o universo de {anos[0]} a {anos[-1]}...", flush=True)
    universo = construir_universo(anos, cache=cache, progresso=progresso)
    destino = salvar_universo(universo)
    print(f"{len(universo)} companhias medidas -> {destino}")
    return 0


if __name__ == "__main__":  # pragma: no cover - ponto de entrada
    raise SystemExit(_principal())


def universos_disponiveis() -> list[tuple[list[int], Path]]:
    """Universos ja construidos em cache, do mais recente para o mais antigo.

    A tela nao pode exigir que o usuario tenha importado exatamente os mesmos
    anos do universo: quem importou 2023-2024 compara-se bem contra um universo
    de 2020-2024, desde que a tela diga qual foi usado.
    """
    pasta = diretorio_cache()
    if not pasta.exists():
        return []
    encontrados = []
    for arquivo in pasta.glob("perfis_*.csv"):
        partes = arquivo.stem.split("_")
        try:
            inicio, fim = int(partes[1]), int(partes[2])
        except (IndexError, ValueError):
            continue
        encontrados.append((list(range(inicio, fim + 1)), arquivo))
    return sorted(encontrados, key=lambda item: item[0][-1], reverse=True)


def universo_mais_proximo(anos: list[int]) -> tuple[Universo, list[int]] | None:
    """O universo em cache que melhor cobre ``anos``, com os anos que ele cobre.

    Prefere o que termina no mesmo exercicio; na falta, o mais recente. Devolve
    ``None`` quando nao ha nenhum -- construir custa minutos e e decisao de quem
    esta na frente da tela, nao efeito colateral de abrir uma aba.
    """
    disponiveis = universos_disponiveis()
    if not disponiveis:
        return None
    alvo = sorted(anos)[-1] if anos else None
    escolhido = next(
        (item for item in disponiveis if item[0][-1] == alvo), disponiveis[0]
    )
    anos_do_universo, caminho = escolhido
    return carregar_universo(anos_do_universo, caminho=caminho), anos_do_universo
