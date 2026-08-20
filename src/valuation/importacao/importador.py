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

# Recuo da arvore publicada. E o espaco de figura (U+2007), e nao o comum:
# o espaco normal colapsa quando o rotulo e renderizado como HTML, e a
# hierarquia -- que e a informacao -- desapareceria na tela.
RECUO = "\u2007" * 3


def _escalar_detalhe(detalhe: pd.DataFrame | None, divisor: float) -> pd.DataFrame | None:
    """Divide so as colunas de ano da arvore; codigo e nivel nao sao valores."""
    if detalhe is None or detalhe.empty:
        return detalhe
    copia = detalhe.copy()
    anos = [c for c in copia.columns if isinstance(c, int)]
    copia[anos] = copia[anos] / divisor
    return copia


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
    # Como buscar estes mesmos dados de novo, quando a origem permite. ``origem``
    # e uma frase para o usuario ler; esta e a mesma informacao em forma de
    # dados, para o app poder reexecutar a busca em vez de pedir que ele refaca
    # tudo a mao quando sair um exercicio novo. Dicionario simples porque ele
    # atravessa a serializacao em YAML e cada origem descreve o seu jeito.
    fonte: dict = field(default_factory=dict)
    # A demonstracao como foi publicada, inteira. O vocabulario canonico e o que
    # o motor consome -- umas dezenas de contas --, mas a DF publicada e uma
    # arvore: 1.01.01 esta dentro de 1.01, que esta dentro de 1. E a quebra que
    # explica de onde vem o total, e joga-la fora para ficar so com as contas do
    # modelo perde exatamente a parte que o analista usa para entender o numero.
    # Colunas: codigo, rotulo, demonstracao, nivel e uma por ano.
    detalhe: pd.DataFrame | None = None

    def arvore(self, demonstracao: str | None = None) -> pd.DataFrame:
        """A demonstracao publicada inteira, na ordem e na hierarquia do plano.

        O recuo do rotulo vem do nivel do codigo, entao a tabela se le como a
        demonstracao se le: o pai acima, as filhas abaixo dele, somando de volta.
        """
        if self.detalhe is None or self.detalhe.empty:
            return pd.DataFrame()

        tabela = self.detalhe
        if demonstracao is not None:
            tabela = tabela[tabela["demonstracao"] == demonstracao]
        if tabela.empty:
            return pd.DataFrame()

        tabela = tabela.sort_values("ordem")
        anos = [c for c in tabela.columns if isinstance(c, int)]
        rotulos = [
            RECUO * (int(nivel) - 1) + str(rotulo)
            for nivel, rotulo in zip(tabela["nivel"], tabela["rotulo"])
        ]
        saida = tabela[anos].copy()
        saida.index = pd.Index(rotulos, name="Conta")
        return saida


    def dre_gerencial(self) -> pd.DataFrame:
        """A DRE na forma em que o analista a monta, com os subtotais que usa.

        A CVM publica a DRE numa arvore que serve para fiscalizar, nao para
        modelar: ``3.04`` e um bloco unico chamado "Despesas/Receitas
        Operacionais" que junta SG&A, impairment, outras receitas, outras
        despesas e equivalencia patrimonial. Quem projeta precisa dos cinco
        separados, porque tres deles nao se repetem e um nao e operacional.

        A ponte montada aqui::

            Receita liquida
            (-) Custos
            = Lucro bruto
            (-) SG&A
            (+/-) Equivalencia patrimonial
            (+/-) Outros (impairment e outras receitas/despesas)
            = EBIT
            (+) D&A
            = EBITDA
            (-) Itens nao recorrentes
            = EBITDA ajustado
            (+) Receitas financeiras
            (-) Despesas financeiras
            (+/-) Derivativos e cambio
            = LAIR
            (-) IR corrente
            (-) IR diferido
            = Lucro liquido consolidado
            (-) Nao controladores
            = Controladores

        **O SG&A e obtido por subtracao**, e nao pelas contas ``3.04.01`` e
        ``3.04.02``: elas so existem em 297 e 454 das 467 companhias, enquanto
        ``3.04`` existe em todas. Tirando dele impairment, outras e
        equivalencia sobra o SG&A de verdade, para qualquer companhia.

        **Derivativos e cambio saem por residuo** do resultado financeiro. Nao
        ha codigo padronizado para eles: quando a companhia abre a linha, ela
        cai num codigo livre dentro de ``3.06``, e o residuo a captura. Quando
        nao abre, o residuo e zero -- que e a resposta certa.
        """
        def s(chave: str) -> pd.Series:
            return self.serie(chave).reindex(self.valores.columns)

        zero = pd.Series(0.0, index=self.valores.columns)

        receita = s("receita_liquida")
        custos = s("custo_produtos_vendidos")
        bruto = s("lucro_bruto")
        if bruto.isna().all():
            bruto = receita.sub(custos, fill_value=0)

        impairment = s("impairment").fillna(0)
        outras_receitas = s("outras_receitas_operacionais").fillna(0)
        outras_despesas = s("outras_despesas_operacionais").fillna(0)
        equivalencia = s("equivalencia_patrimonial").fillna(0)
        outros = impairment.add(outras_receitas).add(outras_despesas)

        ebit = s("ebit")

        # O bloco 3.04 vem do proprio EBIT, e nao da conta guardada. Motivo: ele
        # **pode ser positivo** -- numa holding a equivalencia patrimonial supera
        # as despesas, e a Itausa tem 3.04 de +R$ 14 bi. ``despesas_operacionais``
        # e guardada como magnitude, entao o sinal se perde e o SG&A sai com a
        # ordem de grandeza do lucro de coligadas. Derivando de ``3.05 - 3.03``,
        # que e identidade, a ponte fecha em holding e em industria.
        bloco = ebit.sub(bruto, fill_value=0)
        if ebit.isna().all():
            bloco = -s("despesas_operacionais").fillna(0)
        sga = -(bloco.sub(outros).sub(equivalencia))
        if ebit.isna().all():
            ebit = bruto.sub(sga).add(equivalencia).add(outros)

        depreciacao = s("depreciacao_amortizacao").fillna(0)
        ebitda = ebit.add(depreciacao, fill_value=0)
        ebitda_ajustado = ebitda.sub(outros, fill_value=0)

        receitas_fin = s("receitas_financeiras").fillna(0)
        despesas_fin = s("despesas_financeiras").fillna(0)
        resultado_fin = s("resultado_financeiro")
        derivativos = resultado_fin.sub(receitas_fin).add(despesas_fin).fillna(0)

        lair = s("lucro_antes_impostos")
        if lair.isna().all():
            lair = ebit.add(resultado_fin.fillna(0), fill_value=0)

        # Os dois carregam o sinal publicado: despesa negativa, credito
        # positivo. Somar magnitudes quebraria a ponte de quem teve credito.
        corrente = s("imposto_corrente").fillna(0)
        diferido = s("imposto_diferido").fillna(0)
        impostos = s("impostos")
        if (corrente.abs() + diferido.abs()).sum() == 0 and impostos.notna().any():
            # ``impostos`` (3.08) e guardado com despesa positiva, e o sinal ja
            # veio da identidade da companhia (ver
            # ``_corrigir_sinal_dos_impostos``), entao quem teve credito entra
            # aqui somando -- que e como ele foi publicado.
            corrente = -impostos.fillna(0)

        # ``LAIR - impostos`` da o resultado das operacoes **continuadas**, e nao
        # o lucro consolidado. Quem teve operacao descontinuada no ano tem os
        # dois diferentes: na WEG de 2023 a distancia e de 13,8%.
        descontinuadas = s("operacoes_descontinuadas").fillna(0)
        continuadas = lair.add(corrente, fill_value=0).add(diferido, fill_value=0)

        lucro = s("lucro_liquido")
        controladores = s("lucro_controladores")
        nao_controladores = s("lucro_nao_controladores").fillna(0)
        if controladores.isna().all():
            controladores = lucro.sub(nao_controladores, fill_value=0)

        linhas = {
            "Receita líquida": receita,
            "(−) Custos": -custos.fillna(0),
            "= Lucro bruto": bruto,
            "(−) SG&A": -sga,
            "(+/−) Equivalência patrimonial": equivalencia,
            "(+/−) Outros": outros,
            "= EBIT": ebit,
            "(+) D&A": depreciacao,
            "= EBITDA": ebitda,
            "(−) Itens não recorrentes": -outros,
            "= EBITDA ajustado": ebitda_ajustado,
            "(+) Receitas financeiras": receitas_fin,
            "(−) Despesas financeiras": -despesas_fin,
            "(+/−) Derivativos e câmbio": derivativos,
            "= LAIR": lair,
            "IR corrente": corrente,
            "IR diferido": diferido,
            "= Operações continuadas": continuadas,
            "(+/−) Operações descontinuadas": descontinuadas,
            "= Lucro líquido consolidado": lucro,
            "(−) Não controladores": -nao_controladores,
            "= Controladores": controladores,
        }
        return pd.DataFrame(linhas).T

    # Linhas de subtotal da DRE gerencial, para a tela destacar sem repetir a
    # regra em cada lugar que a exibe.
    SUBTOTAIS_DRE = (
        "= Lucro bruto",
        "= EBIT",
        "= EBITDA",
        "= EBITDA ajustado",
        "= LAIR",
        "= Operações continuadas",
        "= Lucro líquido consolidado",
        "= Controladores",
    )

    def conferir_dre_gerencial(self, tolerancia: float = 0.01) -> pd.DataFrame:
        """Confere cada subtotal contra a soma das linhas que o compoem.

        Existe porque a ponte e montada por subtracao em varios pontos, e
        subtracao com sinal trocado produz uma DRE que parece certa e nao
        fecha. Devolve o desvio relativo de cada subtotal, por ano.
        """
        dre = self.dre_gerencial()

        def linha(nome: str) -> pd.Series:
            return dre.loc[nome] if nome in dre.index else pd.Series(dtype=float)

        checagens = {
            "Lucro bruto": (
                linha("Receita líquida").add(linha("(−) Custos"), fill_value=0),
                linha("= Lucro bruto"),
            ),
            "EBIT": (
                linha("= Lucro bruto")
                .add(linha("(−) SG&A"), fill_value=0)
                .add(linha("(+/−) Equivalência patrimonial"), fill_value=0)
                .add(linha("(+/−) Outros"), fill_value=0),
                linha("= EBIT"),
            ),
            "EBITDA": (
                linha("= EBIT").add(linha("(+) D&A"), fill_value=0),
                linha("= EBITDA"),
            ),
            "EBITDA ajustado": (
                linha("= EBITDA").add(linha("(−) Itens não recorrentes"), fill_value=0),
                linha("= EBITDA ajustado"),
            ),
            "LAIR": (
                linha("= EBIT")
                .add(linha("(+) Receitas financeiras"), fill_value=0)
                .add(linha("(−) Despesas financeiras"), fill_value=0)
                .add(linha("(+/−) Derivativos e câmbio"), fill_value=0),
                linha("= LAIR"),
            ),
            "Operações continuadas": (
                linha("= LAIR")
                .add(linha("IR corrente"), fill_value=0)
                .add(linha("IR diferido"), fill_value=0),
                linha("= Operações continuadas"),
            ),
            "Lucro líquido": (
                linha("= Operações continuadas").add(
                    linha("(+/−) Operações descontinuadas"), fill_value=0
                ),
                linha("= Lucro líquido consolidado"),
            ),
            "Controladores": (
                linha("= Lucro líquido consolidado").add(
                    linha("(−) Não controladores"), fill_value=0
                ),
                linha("= Controladores"),
            ),
        }

        linhas = {}
        for nome, (montado, publicado) in checagens.items():
            diferenca = (montado - publicado).abs()
            escala = publicado.abs().replace(0, np.nan)
            desvio = (diferenca / escala).round(6)
            # Identidade que fecha **exatamente** e aprovacao, e nao "sem dado",
            # mesmo quando o subtotal e zero e nao ha denominador. Sao 9
            # companhias no lucro bruto -- holdings e seguradoras sem linha de
            # receita, onde 0 - 0 = 0 e a resposta certa -- e mais 2 nos
            # controladores. Reportar NaN ali dava a impressao de cobertura
            # faltando onde o que havia era identidade trivialmente verdadeira.
            linhas[nome] = desvio.mask(diferenca == 0, 0.0)
        conferencia = pd.DataFrame(linhas).T
        conferencia.index.name = "Subtotal"
        return conferencia

    def composicao(self, codigo: str, ano: int | None = None) -> pd.DataFrame:
        """Do que uma conta publicada e feita, pelas filhas diretas.

        Responde a pergunta que a conta canonica nao responde: o ativo
        circulante da empresa e caixa ou estoque parado? A divida vence este ano
        ou daqui a cinco? O total nao distingue, e e a distincao que muda a
        leitura de liquidez e de alavancagem.

        So as filhas diretas -- 1.01.01 compoe 1.01, mas 1.01.01.01 compoe
        1.01.01 e somaria em dobro.
        """
        if self.detalhe is None or self.detalhe.empty:
            return pd.DataFrame()

        ano = ano if ano is not None else (self.ano_base or 0)
        if ano not in self.detalhe.columns:
            return pd.DataFrame()

        nivel_filho = codigo.count(".") + 2
        filhas = self.detalhe[
            self.detalhe["codigo"].str.startswith(codigo + ".")
            & (self.detalhe["nivel"] == nivel_filho)
        ]
        if filhas.empty:
            return pd.DataFrame()

        pai = self.detalhe[self.detalhe["codigo"] == codigo]
        total = float(pai[ano].iloc[0]) if not pai.empty else float(filhas[ano].sum())

        tabela = filhas.sort_values("ordem")[["codigo", "rotulo", ano]].copy()
        tabela.columns = ["Código", "Conta", "Valor"]
        tabela["% do total"] = (
            tabela["Valor"] / total if total else np.nan
        )
        return tabela.set_index("Código")

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
        """Tabela com rotulos legiveis, opcionalmente filtrada por demonstracao.

        As linhas saem na ordem do plano de contas -- receita no topo, lucro
        liquido embaixo --, e nao na ordem em que o vocabulario foi escrito. Uma
        DRE fora de ordem obriga o leitor a remontar a demonstracao de cabeca.
        """
        contas = [
            c
            for c in CONTAS
            if c.chave in self.valores.index
            and (demonstracao is None or c.demonstracao == demonstracao)
        ]
        contas.sort(key=lambda c: (c.demonstracao != "dre", c.posicao))
        chaves = [c.chave for c in contas]
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
            fonte=dict(self.fonte),
            # A arvore acompanha a escala: ela mostra os mesmos valores, e uma
            # DFC em reais ao lado de um balanco em milhoes seria ilegivel.
            detalhe=_escalar_detalhe(self.detalhe, divisor),
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
    tabela: dict[str, dict[int, float]],
    anos: list[int],
    mapeamento: dict[str, str] | None = None,
) -> dict[str, str]:
    """Preenche contas ausentes a partir das disponiveis, ate estabilizar.

    ``mapeamento`` e opcional e existe para o de-para nao mentir: quando a D&A
    da DRE e trocada pela da DFC, a origem registrada tem que passar a apontar
    para a linha que de fato virou o numero.
    """
    derivadas: dict[str, str] = {}
    for _ in range(len(DERIVACOES) + 1):
        mudou = False
        for derivacao in DERIVACOES:
            if derivacao.chave in tabela:
                existente = tabela[derivacao.chave].values()
                so_zeros = all(
                    (not np.isfinite(v)) or v == 0 for v in existente
                )
                if not (derivacao.substitui_zero and so_zeros):
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
    corrigidos = _corrigir_sinal_dos_impostos(tabela, anos)
    if corrigidos:
        derivadas["impostos"] = (
            "sinal corrigido pela identidade LAIR - lucro liquido em "
            f"{corrigidos}: a companhia publicou credito de imposto, e nao despesa"
        )
    controladores = _completar_controladores(tabela, anos)
    if controladores:
        derivadas["lucro_controladores"] = (
            f"derivado do consolidado menos minoritarios em {controladores}: a "
            "companhia zerou 3.11.01 nesses anos"
        )
    trocados = _preferir_a_da_do_fluxo_de_caixa(tabela, anos)
    if trocados:
        origem_dre = (mapeamento or {}).get("depreciacao_amortizacao", "a linha da DRE")
        derivadas["depreciacao_amortizacao"] = (
            f"D&A trazida da DFC em {trocados}, no lugar de '{origem_dre}': a linha "
            "da DRE fica dentro de 'Despesas Gerais e Administrativas' e nao inclui "
            "a depreciacao que correu pelo CPV"
        )
        # O de-para tem que apontar para a linha que virou o numero, e nao para a
        # que perdeu: origem registrada errada e o tipo de erro que soma nenhuma
        # denuncia -- que e justamente o que a auditoria de origem existe para pegar.
        if mapeamento is not None and "depreciacao_dfc" in mapeamento:
            mapeamento["depreciacao_amortizacao"] = mapeamento["depreciacao_dfc"]
    abertos = _corrigir_sinal_do_ir_aberto(tabela, anos)
    if abertos:
        derivadas["imposto_corrente"] = derivadas["imposto_diferido"] = (
            f"sinal invertido em {abertos}: a origem trouxe magnitude, e corrente e "
            "diferido precisam do sinal publicado (despesa negativa, credito positivo)"
        )
    return derivadas


def _corrigir_sinal_dos_impostos(
    tabela: dict[str, dict[int, float]], anos: list[int]
) -> str:
    """O sinal do IR vem da identidade da companhia, e nao de convencao de fonte.

    ``impostos`` e guardado com **despesa positiva** -- a convencao que a
    derivacao ``LAIR - lucro liquido`` ja usa e da qual sai a aliquota efetiva.
    Guardar a magnitude perde o credito, e credito nao e caso raro: medido no
    DFP consolidado de 2024, **118 das 467 companhias publicam ``3.08``
    positivo**, somando R$ 71 bi lidos como despesa. O estrago maior nao e na
    ponte da DRE, e na aliquota efetiva: com credito de R$ 6,1 bi sobre LAIR de
    R$ 328,9 mi, a razao passa de 1, e clipada em 100% **zera o NOPAT**.

    Qual sinal e o certo nao se decide por fonte, se mede: **432 das 467
    companhias fecham ``LAIR + 3.08 = 3.09`` com o sinal publicado, e nenhuma
    fecha com a convencao invertida**. Entao ele sai da identidade da propria
    companhia.

    Corrige **so o sinal**, nunca o valor: quando as magnitudes divergem, a
    conta fica como foi lida. Plug que absorve diferenca esconderia erro de
    leitura, que e justamente o que a ponte existe para achar.
    """
    impostos = tabela.get("impostos")
    lair = tabela.get("lucro_antes_impostos")
    lucro = tabela.get("lucro_liquido")
    if not impostos or not lair or not lucro:
        return ""
    descontinuadas = tabela.get("operacoes_descontinuadas") or {}

    def numero(fonte: dict[int, float], ano: int) -> float | None:
        valor = fonte.get(ano)
        return valor if valor is not None and np.isfinite(valor) else None

    corrigidos: list[int] = []
    for ano in anos:
        lido = numero(impostos, ano)
        antes = numero(lair, ano)
        depois = numero(lucro, ano)
        if lido is None or antes is None or depois is None:
            continue
        # ``lucro_liquido`` e o consolidado (3.11); o imposto so alcanca as
        # operacoes continuadas, entao a descontinuada sai antes da conta.
        continuadas = depois - (numero(descontinuadas, ano) or 0.0)
        identidade = antes - continuadas
        escala = max(abs(identidade), abs(lido), 1.0)
        if abs(abs(identidade) - abs(lido)) / escala > 1e-6:
            continue
        if identidade * lido < 0:
            impostos[ano] = identidade
            corrigidos.append(ano)
    return ", ".join(str(ano) for ano in corrigidos)


def _completar_controladores(
    tabela: dict[str, dict[int, float]], anos: list[int]
) -> str:
    """Companhia sem minoritario zera as duas filhas de ``3.11`` e so preenche o pai.

    Medido no DFP consolidado de 2024: **102 das 467 publicam ``3.11.01 = 0`` e
    ``3.11.02 = 0`` com ``3.11`` diferente de zero**. Lido ao pe da letra, o lucro
    dos controladores da CESP seria zero em vez dos R$ 1.078 mi que ela ganhou.

    **A correcao e por ano, e nao pela serie inteira.** A primeira versao disto
    era uma ``Derivacao`` com ``substitui_zero``, que so dispara quando **todos**
    os anos sao zero -- e perde justamente quem muda de pratica no meio. A Viveo
    publica ``3.11.01`` cheio em 2023 (R$ 359,9 mi) e zerado em 2024, e ficava com
    lucro dos controladores zero num ano de prejuizo de R$ 1,4 bilhao.

    Zero legitimo sobrevive: se os minoritarios levaram tudo, ``lucro_liquido -
    lucro_nao_controladores`` da zero de novo.
    """
    controladores = tabela.get("lucro_controladores")
    lucro = tabela.get("lucro_liquido")
    if not lucro:
        return ""
    nao_controladores = tabela.get("lucro_nao_controladores") or {}
    if controladores is None:
        controladores = tabela["lucro_controladores"] = {}

    def numero(fonte: dict[int, float], ano: int) -> float | None:
        valor = fonte.get(ano)
        return valor if valor is not None and np.isfinite(valor) else None

    completados: list[int] = []
    for ano in anos:
        consolidado = numero(lucro, ano)
        if consolidado is None or consolidado == 0:
            continue
        atual = numero(controladores, ano)
        if atual not in (None, 0.0):
            continue
        controladores[ano] = consolidado - (numero(nao_controladores, ano) or 0.0)
        completados.append(ano)
    return ", ".join(str(ano) for ano in completados)


def _preferir_a_da_do_fluxo_de_caixa(
    tabela: dict[str, dict[int, float]], anos: list[int]
) -> str:
    """Entre a D&A da DRE e a da DFC, a da DFC e a completa -- e nao por pouco.

    A linha da DRE mora em ``3.04.02.x``, **dentro de "Despesas Gerais e
    Administrativas"**. Ela so captura a depreciacao que correu pelo SG&A; a que
    correu pelo CPV, que numa industria ou numa concessionaria e a maior parte,
    nao esta ali. O ajuste da DFC (``6.01.01.x``) devolve ao lucro **toda** a D&A
    que o reduziu, que e exatamente o que ``EBITDA = EBIT + D&A`` pede.

    Nao e questao de preferencia: medido nas 467 companhias de 2024, entre as 56
    que publicam as duas, **a da DFC nunca e menor** -- em 34 elas coincidem
    exatamente e em 22 a da DFC e maior, com razao que vai a **310x**. Na CPFL
    Energia a DRE traz R$ 142,0 mi contra R$ 2.303,1 mi da DFC, sobre um EBIT de
    R$ 10,8 bi; na Axia Energia Norte, R$ 5,1 mi contra R$ 1.568,6 mi.

    O efeito e sobre o EBITDA: mediana zero (a maioria ja vinha da DFC ou
    coincide), mas **P90 de +11,2 pontos de margem**. A CPFL Energias Renovaveis
    passa de 48,8% para 67,5%; a Eneva, de 23,7% para 34,3%.

    Quando so a DRE tem o numero (5 companhias), ela fica. A troca entra em
    ``derivadas`` e aparece na tela.
    """
    da = tabela.get("depreciacao_amortizacao")
    dfc = tabela.get("depreciacao_dfc")
    if not da or not dfc:
        return ""

    trocados: list[int] = []
    for ano in anos:
        atual, do_fluxo = da.get(ano), dfc.get(ano)
        if atual is None or do_fluxo is None:
            continue
        if not (np.isfinite(atual) and np.isfinite(do_fluxo)):
            continue
        if do_fluxo == 0:
            continue
        escala = max(abs(atual), abs(do_fluxo), 1.0)
        if abs(atual - do_fluxo) / escala < 1e-6:
            continue
        da[ano] = do_fluxo
        trocados.append(ano)
    return ", ".join(str(ano) for ano in trocados)


def _corrigir_sinal_do_ir_aberto(
    tabela: dict[str, dict[int, float]], anos: list[int]
) -> str:
    """Corrente e diferido guardam o **sinal publicado**, e cada um pode ser credito.

    Nao sao duas metades do mesmo sinal. Medido no DFP consolidado de 2024:
    **221 das 467 companhias tiveram credito no diferido** e 16 no corrente, 8
    nas duas, e em **204 os dois tem sinais opostos** -- o caso mais comum da
    base, nao a excecao. ``3.08.01 + 3.08.02 = 3.08`` fecha com o sinal publicado
    em 440 de 440 companhias que abrem as duas, e em nenhuma com magnitude.

    Da CVM eles ja chegam com o sinal certo. O risco esta na planilha, onde o
    usuario pode digitar as duas como despesa positiva -- e ate agora o template
    mandava fazer exatamente isso. Quando a soma tem a magnitude do total e o
    sinal oposto, foi isso que aconteceu, e os dois viram do lado certo.

    Quando as magnitudes nao batem, **nao mexe**: com corrente e diferido de
    sinais opostos digitados como magnitude a informacao se perdeu, e nao ha
    identidade que a recupere. ``_conferir`` avisa nesse caso.
    """
    corrente = tabela.get("imposto_corrente")
    diferido = tabela.get("imposto_diferido")
    impostos = tabela.get("impostos")
    if not corrente or not diferido or not impostos:
        return ""

    corrigidos: list[int] = []
    for ano in anos:
        cor, dif, total = corrente.get(ano), diferido.get(ano), impostos.get(ano)
        if any(v is None or not np.isfinite(v) for v in (cor, dif, total)):
            continue
        soma = cor + dif
        # ``impostos`` guarda despesa positiva; as filhas, o sinal publicado.
        esperado = -total
        if soma == 0 or esperado == 0:
            continue
        escala = max(abs(esperado), abs(soma), 1.0)
        if abs(abs(esperado) - abs(soma)) / escala > 1e-6:
            continue
        if soma * esperado < 0:
            corrente[ano], diferido[ano] = -cor, -dif
            corrigidos.append(ano)
    return ", ".join(str(ano) for ano in corrigidos)


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

    # A DFC tem uma identidade propria, e ela e o teste mais direto de que as
    # secoes foram classificadas certo: se capex caiu no financiamento ou os
    # juros entraram duas vezes, a soma deixa de bater com a variacao de caixa.
    partes = [serie(c) for c in ("fluxo_operacional", "fluxo_investimento", "fluxo_financiamento")]
    variacao = serie("variacao_caixa")
    if variacao is not None and all(p is not None for p in partes):
        soma = partes[0]
        for parte in partes[1:]:
            soma = soma.add(parte, fill_value=0)
        cambio = serie("variacao_cambial_caixa")
        if cambio is not None:
            soma = soma.add(cambio, fill_value=0)
        escala = variacao.abs().replace(0, np.nan)
        desvio = ((soma - variacao).abs() / escala).max()
        if np.isfinite(desvio) and desvio > 0.02:
            avisos.append(
                f"A DFC nao fecha em ate {desvio:.1%}: operacional, investimento, "
                "financiamento e variacao cambial nao somam a variacao de caixa. "
                "Confira se alguma linha foi classificada na secao errada."
            )

    # Corrente e diferido tem que reconstruir o total. Cada um pode ser credito
    # por conta propria -- em 204 das 467 companhias de 2024 eles tem sinais
    # opostos --, entao a soma nao se confere por magnitude, e sim com sinal.
    corrente, diferido, impostos = (
        serie("imposto_corrente"),
        serie("imposto_diferido"),
        serie("impostos"),
    )
    if corrente is not None and diferido is not None and impostos is not None:
        soma = corrente.fillna(0).add(diferido.fillna(0), fill_value=0)
        escala = impostos.abs().replace(0, np.nan)
        desvio = ((soma + impostos).abs() / escala).max()
        if np.isfinite(desvio) and desvio > 0.01:
            avisos.append(
                f"IR corrente mais IR diferido nao reconstroem o IR total (ate {desvio:.1%} "
                "de diferenca). Os dois precisam do sinal publicado -- despesa negativa, "
                "credito positivo -- e credito e comum no diferido. Se a origem trouxe "
                "magnitude nos dois com sinais que na verdade eram opostos, o sinal se "
                "perdeu e so a origem pode recuperar."
            )

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

    derivadas = _derivar(tabela, anos, mapeamento)

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
    derivadas = _derivar(tabela, anos, mapeamento)
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
        fonte=dict(demonstracoes.fonte),
        detalhe=demonstracoes.detalhe,
    )
