"""Dados de mercado: curva real brasileira e expectativas do Focus.

Serve a um proposito so, e vale dizer qual para nao virar gaveta de API: medir
o **risco-pais que o mercado cobra**, em vez de usar o valor de referencia
embarcado em ``dados_setoriais.py``.

O Ke continua montado em USD (ver a decisao em CLAUDE.md). O que muda e de onde
sai o ``risco_pais`` dessa conta. Hoje ele e um numero de ordem de grandeza; a
curva de NTN-B permite observa-lo.

A aritmetica
------------

A NTN-B paga taxa **real**. Para comparar com uma taxa nominal em USD e preciso
nominaliza-la pela inflacao esperada::

    rf_brl_nominal = (1 + taxa_real) x (1 + ipca_esperado) - 1

E converter o rf americano para BRL pelo mesmo diferencial de inflacao que o
motor ja usa::

    rf_usd_em_brl = (1 + rf_usd) x (1 + ipca) / (1 + inflacao_usd) - 1

A diferenca entre os dois e o que o mercado cobra a mais para financiar o Brasil.

O que essa diferenca e, e o que ela nao e
----------------------------------------

O termo que **domina** e o premio de risco de carregar o Brasil -- e ele que se
quer medir. Liquidez da NTN-B e ruido de inflacao sao de segunda ordem, mas
existem, e por isso a funcao devolve as parcelas junto do resultado: quem le
decide quanto atribuir a risco-pais, e o app nao troca o padrao sozinho.

**A medida atual e um piso, nao um ponto.** A NTN-B e indexada: quem a carrega
nao corre risco de inflacao. Quem carrega titulo nominal corre, e cobra por
isso -- o premio de risco de inflacao::

    titulo nominal = juro real + inflacao esperada + premio de risco de inflacao
    NTN-B          = juro real                                       (indexada)

Nominalizar a NTN-B so com a inflacao esperada, como se faz aqui, omite esse
premio e produz um ``rf_brl_nominal`` baixo demais -- logo, um risco-pais
subestimado.

A correcao esta ao alcance e nao foi feita: usar a **inflacao implicita**
(prefixado menos NTN-B de prazo equivalente) no lugar do IPCA do Focus. Ela ja
embute o premio, e os dois titulos vem do mesmo arquivo que ``curva_ntnb`` le.
"""

from __future__ import annotations

import http.client
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

URL_FOCUS = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais"
)
URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
URL_TESOURO = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)

SERIE_SELIC_META = 432
SERIE_IPCA_12M = 13522

ENCODING = "latin-1"
TEMPO_LIMITE = 180
TENTATIVAS = 2

# O titulo padrao da curva real: IPCA+ sem juros semestrais.
TITULO_NTNB = "Tesouro IPCA+"
# Prazo de referencia para o risco-pais. Longo o bastante para nao depender do
# ciclo de juros, curto o bastante para ter liquidez.
ANOS_REFERENCIA = 10


class ErroMercado(Exception):
    """Falha ao obter ou interpretar um dado de mercado."""


def diretorio_cache() -> Path:
    return Path.home() / ".cache" / "valuation" / "mercado"


def _buscar(url: str, cabecalhos: dict | None = None) -> bytes:
    """GET com as mesmas garantias do leitor da CVM: retentativa e erro tratado."""
    ultimo: Exception | None = None
    for _ in range(TENTATIVAS):
        try:
            pedido = urllib.request.Request(url, headers=cabecalhos or {})
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as erro:
            raise ErroMercado(f"{url} respondeu {erro.code}.") from erro
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as erro:
            ultimo = erro
    raise ErroMercado(f"Nao consegui obter {url}: {ultimo}") from ultimo


# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------


# O Focus publica **duas** estatisticas para a mesma coleta e o mesmo ano, no
# campo ``baseCalculo``: 0 usa as respostas dos ultimos 30 dias, 1 usa so as dos
# ultimos 5 dias uteis. Sem filtrar, cada ano volta duplicado -- medido na coleta
# de 14/08/2026, o IPCA de 2027 aparecia com mediana 4,2402 (base 0, 148 casas) e
# 4,2060 (base 1, 69 casas), e o codigo pegava uma das duas por ordem de linha.
#
# A base 0 e a do relatorio Focus publicado, e tem **mais que o dobro de
# respondentes**. A 1 e mais recente e mais ruidosa; fica disponivel por
# parametro para quem quiser a leitura do dia.
BASE_30_DIAS = 0
BASE_5_DIAS = 1


def expectativas(
    indicador: str, cache: Path | None = None, base: int = BASE_30_DIAS
) -> pd.DataFrame:
    """Projecoes do Focus para um indicador, por ano de referencia.

    Devolve a coleta mais recente, com mediana, dispersao e quantas casas
    responderam -- a dispersao importa: 151 casas projetando Selic entre 12,25%
    e 14,25% nao e a mesma coisa que consenso.
    """
    filtro = urllib.parse.quote(f"Indicador eq '{indicador}'")
    url = f"{URL_FOCUS}?$format=json&$orderby=Data desc&$top=120&$filter={filtro}"
    dados = json.loads(_buscar(url.replace(" ", "%20")).decode("utf-8"))
    linhas = dados.get("value") or []
    if not linhas:
        raise ErroMercado(f"O Focus nao devolveu nada para '{indicador}'.")

    tabela = pd.DataFrame(linhas)
    recente = tabela["Data"].max()
    tabela = tabela[tabela["Data"] == recente]
    if "baseCalculo" in tabela.columns:
        escolhida = tabela[tabela["baseCalculo"] == base]
        if not escolhida.empty:
            tabela = escolhida
    saida = (
        tabela.assign(ano=tabela["DataReferencia"].astype(int))
        .set_index("ano")[["Mediana", "Media", "DesvioPadrao", "numeroRespondentes"]]
        .sort_index()
    )
    saida.attrs["coleta"] = str(recente)[:10]
    return saida


def ipca_esperado(anos_a_frente: int = 3, cache: Path | None = None) -> float:
    """IPCA de longo prazo pelo Focus, em decimal.

    Usa o ano mais distante disponivel dentro da janela: a projecao curta carrega
    o choque corrente, e o que se quer aqui e a inflacao de regime.
    """
    tabela = expectativas("IPCA", cache)
    limite = date.today().year + anos_a_frente
    candidatos = tabela[tabela.index <= limite]
    if candidatos.empty:
        raise ErroMercado("O Focus nao tem IPCA para a janela pedida.")
    return float(candidatos["Mediana"].iloc[-1]) / 100.0


# ---------------------------------------------------------------------------
# Curva real
# ---------------------------------------------------------------------------


def curva_ntnb(caminho: str | Path | None = None) -> pd.DataFrame:
    """Taxa real das NTN-B por vencimento, da coleta mais recente do arquivo.

    O arquivo do Tesouro tem o historico inteiro e passa de 30 MB; quando vem da
    rede, so os primeiros blocos sao lidos, que ja contem a coleta mais recente.
    """
    if caminho is not None:
        bruto = Path(caminho).read_bytes()
    else:
        bruto = _buscar(URL_TESOURO, {"Range": "bytes=0-400000"})

    quebra = b"\r\n" if b"\r\n" in bruto else b"\n"
    linhas = bruto.split(quebra)
    if len(linhas) < 2:
        raise ErroMercado("O arquivo do Tesouro veio vazio.")

    # A ultima linha pode ter sido cortada no meio pelo Range.
    corpo = [l for l in linhas[1:-1] if l.startswith(TITULO_NTNB.encode(ENCODING) + b";")]
    if not corpo:
        raise ErroMercado("Nao achei NTN-B no recorte do arquivo do Tesouro.")

    registros = []
    for linha in corpo:
        campos = linha.decode(ENCODING).split(";")
        if len(campos) < 4:
            continue
        registros.append(
            {
                "vencimento": pd.to_datetime(campos[1], format="%d/%m/%Y"),
                "data_base": pd.to_datetime(campos[2], format="%d/%m/%Y"),
                "taxa_real": float(campos[3].replace(",", ".")) / 100.0,
            }
        )

    tabela = pd.DataFrame(registros)
    recente = tabela["data_base"].max()
    return tabela[tabela["data_base"] == recente].sort_values("vencimento").reset_index(drop=True)


def taxa_real_longa(curva: pd.DataFrame, anos: int = ANOS_REFERENCIA) -> float:
    """Taxa real do vencimento mais proximo do prazo pedido."""
    if curva.empty:
        raise ErroMercado("A curva veio vazia.")
    alvo = pd.Timestamp(curva["data_base"].iloc[0]) + pd.DateOffset(years=anos)
    distancia = (curva["vencimento"] - alvo).abs()
    return float(curva.loc[distancia.idxmin(), "taxa_real"])


# ---------------------------------------------------------------------------
# O que isto existe para calcular
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiscoPaisImplicito:
    """O que a curva real diz sobre o premio de financiar o Brasil."""

    taxa_real_ntnb: float
    ipca_esperado: float
    rf_brl_nominal: float
    rf_usd: float
    rf_usd_em_brl: float
    diferenca: float
    vencimento: str = ""

    @property
    def explicacao(self) -> str:
        return (
            f"NTN-B de {self.vencimento} paga {self.taxa_real_ntnb:.2%} real; com "
            f"IPCA esperado de {self.ipca_esperado:.2%}, isso e "
            f"{self.rf_brl_nominal:.2%} nominal em BRL. O rf americano de "
            f"{self.rf_usd:.2%} convertido para BRL da {self.rf_usd_em_brl:.2%}. "
            f"A diferenca e {self.diferenca:.2%}."
        )

    @property
    def ressalva(self) -> str:
        return (
            "Esta diferenca nao e risco soberano puro: carrega o premio de "
            "liquidez da NTN-B e qualquer descasamento entre a inflacao usada "
            "aqui e a que o mercado precifica. Use-a como ordem de grandeza, e "
            "confira antes de trocar a premissa."
        )


def risco_pais_implicito(
    taxa_real: float,
    ipca: float,
    rf_usd: float,
    inflacao_usd: float,
    vencimento: str = "",
) -> RiscoPaisImplicito:
    """Quanto o mercado cobra a mais em BRL do que em USD, pela curva real.

    Puro de proposito: recebe taxas e devolve a conta, sem tocar a rede. E onde
    o erro de real contra nominal moraria, entao e o que precisa de teste.
    """
    for nome, valor in (("taxa_real", taxa_real), ("ipca", ipca), ("rf_usd", rf_usd)):
        if not np.isfinite(valor):
            raise ValueError(f"{nome} precisa ser um numero.")

    rf_brl_nominal = (1 + taxa_real) * (1 + ipca) - 1
    rf_usd_em_brl = (1 + rf_usd) * (1 + ipca) / (1 + inflacao_usd) - 1
    return RiscoPaisImplicito(
        taxa_real_ntnb=taxa_real,
        ipca_esperado=ipca,
        rf_brl_nominal=rf_brl_nominal,
        rf_usd=rf_usd,
        rf_usd_em_brl=rf_usd_em_brl,
        diferenca=rf_brl_nominal - rf_usd_em_brl,
        vencimento=vencimento,
    )


def medir_risco_pais(
    rf_usd: float,
    inflacao_usd: float,
    anos: int = ANOS_REFERENCIA,
    caminho_curva: str | Path | None = None,
    ipca: float | None = None,
) -> RiscoPaisImplicito:
    """Busca curva e Focus e devolve o risco-pais implicito."""
    curva = curva_ntnb(caminho_curva)
    taxa = taxa_real_longa(curva, anos)
    inflacao = ipca if ipca is not None else ipca_esperado()

    alvo = pd.Timestamp(curva["data_base"].iloc[0]) + pd.DateOffset(years=anos)
    distancia = (curva["vencimento"] - alvo).abs()
    vencimento = curva.loc[distancia.idxmin(), "vencimento"].strftime("%d/%m/%Y")

    return risco_pais_implicito(taxa, inflacao, rf_usd, inflacao_usd, vencimento)


# ---------------------------------------------------------------------------
# O bloco macro inteiro, numa chamada
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroDoFocus:
    """As premissas macro como o mercado as projeta, prontas para comparar.

    Existe para responder de uma vez a pergunta que o analista faz ao abrir a
    tela: "o que eu digitei esta perto do consenso?". Traz a **data da coleta** e
    quantas casas responderam porque projecao de consenso sem numero de
    respondentes nao e consenso, e sim media de quem quis responder.
    """

    ipca: float
    pib_real: float
    selic: float
    cambio: float
    ano_de_referencia: int
    coleta: str
    respondentes: dict[str, int]

    def comparar(self, macro) -> pd.DataFrame:
        """O que esta no modelo contra o que o Focus projeta, lado a lado."""
        linhas = {
            "IPCA": (macro.inflacao_brl, self.ipca),
            "PIB real": (getattr(macro, "pib_real", float("nan")), self.pib_real),
        }
        return pd.DataFrame(
            [
                {
                    "Premissa": nome,
                    "No modelo": no_modelo,
                    "Focus": no_focus,
                    "Diferença": no_modelo - no_focus,
                }
                for nome, (no_modelo, no_focus) in linhas.items()
            ]
        ).set_index("Premissa")


# Os nomes dos indicadores vem **acentuados** do Olinda, e "PIB Total" nao e
# "PIB": pedir o nome errado devolve lista vazia, e nao erro.
INDICADORES_FOCUS = {
    "ipca": "IPCA",
    "pib_real": "PIB Total",
    "selic": "Selic",
    "cambio": "Câmbio",
}


def macro_do_focus(anos_a_frente: int = 3, cache: Path | None = None) -> MacroDoFocus:
    """IPCA, PIB real, Selic e câmbio de longo prazo, pelo Focus.

    Usa o ano mais distante dentro da janela, e nao o proximo: a projecao curta
    carrega o choque corrente, e premissa de perpetuidade quer regime. Medido na
    coleta de 14/08/2026, a diferenca entre os dois nao e pequena -- IPCA de
    5,02% para 2026 contra **3,50%** para 2029.

    **Nao troca nada sozinho.** Devolve os numeros para a tela mostrar ao lado
    dos que o usuario digitou; aplicar e decisao dele. O padrao do app continua
    sendo a pratica do dono do projeto (IPCA 5%, PIB real 1,5%), que e mais
    conservadora que o consenso nos dois.
    """
    limite = date.today().year + anos_a_frente
    valores: dict[str, float] = {}
    respondentes: dict[str, int] = {}
    coleta = ""
    ano_escolhido = limite

    for chave, indicador in INDICADORES_FOCUS.items():
        tabela = expectativas(indicador, cache)
        coleta = coleta or str(tabela.attrs.get("coleta", ""))
        candidatos = tabela[tabela.index <= limite]
        if candidatos.empty:
            raise ErroMercado(f"O Focus nao tem '{indicador}' para a janela pedida.")
        linha = candidatos.iloc[-1]
        ano_escolhido = int(candidatos.index[-1])
        # Cambio e preco em reais por dolar, e nao taxa: nao se divide por 100.
        valores[chave] = float(linha["Mediana"]) / (1.0 if chave == "cambio" else 100.0)
        respondentes[chave] = int(linha["numeroRespondentes"])

    return MacroDoFocus(
        ipca=valores["ipca"],
        pib_real=valores["pib_real"],
        selic=valores["selic"],
        cambio=valores["cambio"],
        ano_de_referencia=ano_escolhido,
        coleta=coleta,
        respondentes=respondentes,
    )
