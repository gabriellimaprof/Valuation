"""Importacao de demonstracoes financeiras de planilhas de qualquer origem.

A mesma funcao ``importar`` atende o template do proprio app, o export da CVM/B3
e o export de terminal (Economatica, Bloomberg, Capital IQ). O que muda entre
eles -- codigo de conta, nomenclatura, sinal dos custos, posicao do cabecalho --
e absorvido aqui, e o resultado sai sempre no mesmo vocabulario canonico.

Nada e descartado em silencio: linhas nao reconhecidas, contas derivadas e
inconsistencias viram campos do resultado, para que o app possa mostrar ao
usuario o que entendeu de cada arquivo antes de modelar em cima.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .esquema import (
    CHAVES_OBRIGATORIAS,
    CONTAS,
    DERIVACOES,
    POR_CHAVE,
    Conta,
    reconhecer,
)
from .leitura import Grade, carregar_abas, linhas_da_grade, localizar_grade

CONFIANCA_MINIMA = 0.6


@dataclass(frozen=True)
class LinhaNaoReconhecida:
    """Uma linha da planilha que o importador nao soube classificar."""

    rotulo: str
    aba: str
    melhor_palpite: str | None
    confianca: float


@dataclass(frozen=True)
class Demonstracoes:
    """Demonstracoes financeiras normalizadas: contas canonicas x anos."""

    empresa: str
    valores: pd.DataFrame
    origem: str = ""
    unidade: str = "unidades monetarias"
    moeda: str = "BRL"
    mapeamento: dict[str, str] = field(default_factory=dict)
    derivadas: dict[str, str] = field(default_factory=dict)
    nao_reconhecidas: list[LinhaNaoReconhecida] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def anos(self) -> list[int]:
        return list(self.valores.columns)

    def tem(self, chave: str) -> bool:
        """A conta existe e tem ao menos um valor?"""
        return chave in self.valores.index and self.valores.loc[chave].notna().any()

    def serie(self, chave: str) -> pd.Series:
        """Serie anual de uma conta, com ``NaN`` onde nao ha dado."""
        if chave not in self.valores.index:
            return pd.Series(np.nan, index=self.valores.columns, name=chave)
        return self.valores.loc[chave]

    def valor(self, chave: str, ano: int | None = None) -> float:
        """Valor de uma conta em um ano (por padrao, o mais recente disponivel)."""
        serie = self.serie(chave).dropna()
        if serie.empty:
            return float("nan")
        if ano is None:
            return float(serie.iloc[-1])
        return float(serie.get(ano, float("nan")))

    @property
    def ano_base(self) -> int | None:
        """Ultimo ano com dados, que e a data-base natural do valuation."""
        return self.anos[-1] if self.anos else None

    def ebitda(self) -> pd.Series:
        """EBITDA = EBIT + depreciacao e amortizacao."""
        return self.serie("ebit").add(self.serie("depreciacao_amortizacao"), fill_value=0)

    def divida_bruta(self) -> pd.Series:
        """Divida bruta = emprestimos de curto prazo + de longo prazo."""
        return self.serie("divida_curto_prazo").add(
            self.serie("divida_longo_prazo"), fill_value=0
        )

    def divida_liquida(self) -> pd.Series:
        """Divida liquida = divida bruta - caixa - aplicacoes financeiras."""
        caixa = self.serie("caixa_equivalentes").add(
            self.serie("aplicacoes_financeiras"), fill_value=0
        )
        return self.divida_bruta().sub(caixa, fill_value=0)

    def capital_giro(self) -> pd.Series:
        """Capital de giro operacional = recebiveis + estoques - fornecedores.

        Deliberadamente restrito as tres contas operacionais classicas: incluir
        todo o circulante misturaria caixa e divida de curto prazo, que ja
        entram na ponte de valor e seriam contados duas vezes.
        """
        return (
            self.serie("contas_receber")
            .add(self.serie("estoques"), fill_value=0)
            .sub(self.serie("fornecedores"), fill_value=0)
        )

    def tabela(self, demonstracao: str | None = None) -> pd.DataFrame:
        """Tabela com rotulos legiveis, opcionalmente filtrada por demonstracao."""
        chaves = [
            c.chave
            for c in CONTAS
            if c.chave in self.valores.index
            and (demonstracao is None or c.demonstracao == demonstracao)
        ]
        tabela = self.valores.loc[chaves].copy()
        tabela.index = [POR_CHAVE[k].rotulo for k in chaves]
        return tabela

    def escalar(self, divisor: float, nova_unidade: str) -> "Demonstracoes":
        """Converte a unidade dos valores (por exemplo, reais para R$ milhoes)."""
        if divisor == 0:
            raise ValueError("O divisor de escala nao pode ser zero.")
        return Demonstracoes(
            empresa=self.empresa,
            valores=self.valores / divisor,
            origem=self.origem,
            unidade=nova_unidade,
            moeda=self.moeda,
            mapeamento=dict(self.mapeamento),
            derivadas=dict(self.derivadas),
            nao_reconhecidas=list(self.nao_reconhecidas),
            avisos=list(self.avisos)
            # Milhar com ponto: o texto vai direto para a tela, e "1,000,000"
            # se le como um e pouco em portugues.
            + [f"Valores divididos por {divisor:,.0f}.".replace(",", ".")],
        )


def _coletar_linhas(
    abas: dict[str, pd.DataFrame],
) -> list[tuple[str, str, str | None, dict[int, float]]]:
    """Percorre todas as abas e devolve ``(aba, rotulo, codigo, valores por ano)``."""
    coletadas = []
    for nome, dados in abas.items():
        grade: Grade | None = localizar_grade(dados, aba=nome)
        if grade is None:
            continue
        for rotulo, codigo, valores in linhas_da_grade(grade):
            coletadas.append((nome, rotulo, codigo, valores))
    return coletadas


def _ajustar_sinal(conta: Conta, valores: dict[int, float]) -> tuple[dict[int, float], bool]:
    """Padroniza contas de custo/despesa como magnitude positiva.

    A CVM publica custos com sinal negativo; terminais costumam publicar
    positivos. O motor de valuation subtrai essas contas explicitamente, entao
    guardar sempre a magnitude evita que a mesma empresa mude de valor conforme
    a origem do arquivo.
    """
    if not conta.sinal_invertido:
        return valores, False
    negativos = sum(1 for v in valores.values() if np.isfinite(v) and v < 0)
    positivos = sum(1 for v in valores.values() if np.isfinite(v) and v > 0)
    if negativos and positivos:
        return {ano: abs(v) for ano, v in valores.items()}, True
    return {ano: abs(v) for ano, v in valores.items()}, False


def _derivar(
    tabela: dict[str, dict[int, float]], anos: list[int]
) -> dict[str, str]:
    """Preenche contas ausentes a partir das disponiveis, ate estabilizar."""
    derivadas: dict[str, str] = {}
    for _ in range(len(DERIVACOES) + 1):
        mudou = False
        for derivacao in DERIVACOES:
            if derivacao.chave in tabela:
                continue
            if not all(req in tabela for req in derivacao.requer):
                continue
            calculada = {}
            for ano in anos:
                partes = [tabela[req].get(ano, float("nan")) for req in derivacao.requer]
                if any(not np.isfinite(p) for p in partes):
                    continue
                if len(partes) == 1:
                    calculada[ano] = partes[0]
                else:
                    calculada[ano] = (
                        partes[0] - partes[1]
                        if "-" in derivacao.formula
                        else partes[0] + partes[1]
                    )
            if calculada:
                tabela[derivacao.chave] = calculada
                derivadas[derivacao.chave] = derivacao.explicacao
                mudou = True
        if not mudou:
            break
    return derivadas


def _conferir(demonstracoes_valores: pd.DataFrame, avisos: list[str]) -> None:
    """Confere identidades contabeis e registra divergencias como aviso."""
    def serie(chave: str) -> pd.Series | None:
        if chave not in demonstracoes_valores.index:
            return None
        s = demonstracoes_valores.loc[chave]
        return s if s.notna().any() else None

    ativo, passivo = serie("ativo_total"), serie("passivo_total")
    if ativo is not None and passivo is not None:
        diferenca = (ativo - passivo).abs()
        escala = ativo.abs().replace(0, np.nan)
        desvio = (diferenca / escala).max()
        if np.isfinite(desvio) and desvio > 0.01:
            avisos.append(
                f"Ativo total e passivo total divergem em ate {desvio:.1%} em algum ano. "
                "Confira se as duas metades do balanco vieram do mesmo arquivo."
            )

    receita = serie("receita_liquida")
    if receita is not None and (receita.dropna() < 0).any():
        avisos.append("Ha receita liquida negativa; confira o sinal da planilha de origem.")

    ebit, lucro = serie("ebit"), serie("lucro_liquido")
    if ebit is not None and lucro is not None:
        # Lucro liquido acima do EBIT e possivel (resultado financeiro positivo),
        # mas se acontece em todos os anos costuma indicar linha trocada.
        if (lucro.dropna() > ebit.dropna()).all() and len(lucro.dropna()) >= 3:
            avisos.append(
                "O lucro liquido supera o EBIT em todos os anos. Isso e possivel com "
                "resultado financeiro positivo, mas vale conferir se as linhas nao "
                "foram trocadas na importacao."
            )


def importar(
    caminho: str | Path,
    empresa: str | None = None,
    unidade: str = "unidades monetarias",
    moeda: str = "BRL",
    anos_maximos: int | None = None,
) -> Demonstracoes:
    """Importa demonstracoes financeiras de uma planilha.

    Detecta sozinho onde estao os anos e as contas, reconhece cada linha pelo
    codigo CVM ou pelo nome, padroniza sinais, deriva o que faltar e confere as
    identidades contabeis.

    ``anos_maximos`` mantem apenas os N anos mais recentes, util quando o export
    traz uma decada inteira e so os ultimos anos interessam.
    """
    caminho = Path(caminho)
    abas = carregar_abas(caminho)
    coletadas = _coletar_linhas(abas)
    if not coletadas:
        raise ValueError(
            f"Nao encontrei nenhuma tabela com anos em {caminho.name}. "
            "Verifique se a planilha tem uma linha de cabecalho com os exercicios."
        )

    tabela: dict[str, dict[int, float]] = {}
    mapeamento: dict[str, str] = {}
    confiancas: dict[str, float] = {}
    nao_reconhecidas: list[LinhaNaoReconhecida] = []
    avisos: list[str] = []

    for aba, rotulo, codigo, valores in coletadas:
        resultado = reconhecer(rotulo, codigo)
        if resultado.chave is None or resultado.confianca < CONFIANCA_MINIMA:
            nao_reconhecidas.append(
                LinhaNaoReconhecida(rotulo, aba, resultado.chave, resultado.confianca)
            )
            continue

        conta = POR_CHAVE[resultado.chave]
        valores, sinal_misto = _ajustar_sinal(conta, valores)
        if sinal_misto:
            avisos.append(
                f"'{rotulo}' tem sinais trocados entre anos; usei a magnitude "
                f"em todos. Confira {conta.rotulo}."
            )

        anterior = confiancas.get(conta.chave, -1.0)
        if resultado.confianca > anterior or (
            resultado.confianca == anterior and conta.chave not in tabela
        ):
            tabela[conta.chave] = valores
            mapeamento[conta.chave] = f"{rotulo} ({aba})"
            confiancas[conta.chave] = resultado.confianca

    anos = sorted({ano for valores in tabela.values() for ano in valores})
    if anos_maximos:
        anos = anos[-anos_maximos:]
    if not anos:
        raise ValueError(f"Nenhum ano com dados em {caminho.name}.")

    derivadas = _derivar(tabela, anos)

    ordem = [c.chave for c in CONTAS if c.chave in tabela]
    valores_df = pd.DataFrame(
        {ano: {chave: tabela[chave].get(ano, np.nan) for chave in ordem} for ano in anos},
        index=ordem,
        columns=anos,
    )

    faltando = [
        POR_CHAVE[chave].rotulo
        for chave in CHAVES_OBRIGATORIAS
        if chave not in valores_df.index or valores_df.loc[chave].isna().all()
    ]
    if faltando:
        avisos.append(
            "Contas obrigatorias nao encontradas: " + ", ".join(faltando) + ". "
            "Mapeie-as manualmente antes de modelar."
        )

    _conferir(valores_df, avisos)

    return Demonstracoes(
        empresa=empresa or caminho.stem,
        valores=valores_df,
        origem=caminho.name,
        unidade=unidade,
        moeda=moeda,
        mapeamento=mapeamento,
        derivadas=derivadas,
        nao_reconhecidas=nao_reconhecidas,
        avisos=avisos,
    )


def aplicar_mapeamento_manual(
    demonstracoes: Demonstracoes,
    caminho: str | Path,
    mapa: dict[str, str],
) -> Demonstracoes:
    """Reimporta o arquivo forcando o vinculo ``rotulo original -> conta canonica``.

    E o que a tela de conferencia do app usa quando o usuario corrige uma linha
    que o reconhecimento automatico errou ou nao encontrou.
    """
    desconhecidas = set(mapa.values()) - set(POR_CHAVE)
    if desconhecidas:
        raise ValueError(f"Contas canonicas inexistentes: {sorted(desconhecidas)}")

    abas = carregar_abas(caminho)
    coletadas = _coletar_linhas(abas)
    tabela = {
        chave: dict(zip(demonstracoes.anos, demonstracoes.valores.loc[chave]))
        for chave in demonstracoes.valores.index
    }
    mapeamento = dict(demonstracoes.mapeamento)

    from .esquema import normalizar

    alvos = {normalizar(rotulo): chave for rotulo, chave in mapa.items()}
    for aba, rotulo, _codigo, valores in coletadas:
        chave = alvos.get(normalizar(rotulo))
        if chave is None:
            continue
        valores, _ = _ajustar_sinal(POR_CHAVE[chave], valores)
        tabela[chave] = valores
        mapeamento[chave] = f"{rotulo} ({aba}) [manual]"

    anos = demonstracoes.anos
    derivadas = _derivar(tabela, anos)
    ordem = [c.chave for c in CONTAS if c.chave in tabela]
    valores_df = pd.DataFrame(
        {ano: {chave: tabela[chave].get(ano, np.nan) for chave in ordem} for ano in anos},
        index=ordem,
        columns=anos,
    )

    avisos: list[str] = []
    _conferir(valores_df, avisos)
    rotulos_mapeados = {normalizar(r) for r in mapa}

    return Demonstracoes(
        empresa=demonstracoes.empresa,
        valores=valores_df,
        origem=demonstracoes.origem,
        unidade=demonstracoes.unidade,
        moeda=demonstracoes.moeda,
        mapeamento=mapeamento,
        derivadas={**demonstracoes.derivadas, **derivadas},
        nao_reconhecidas=[
            linha
            for linha in demonstracoes.nao_reconhecidas
            if normalizar(linha.rotulo) not in rotulos_mapeados
        ],
        avisos=avisos,
    )
