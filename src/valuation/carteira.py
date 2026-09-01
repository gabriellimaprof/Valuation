"""Varios valuations lado a lado: premissa contra premissa, e contra o historico.

`comparacao.py` compara **duas versoes do mesmo** valuation e responde "o que
mudou e quanto moveu o valor". Esta peca responde outra pergunta: com tres ou
quatro companhias modeladas na mesa, **em qual delas eu estou sendo otimista?**

A decisao de desenho que separa comparacao util de tabela bonita
---------------------------------------------------------------

Por em coluna a margem projetada de cada companhia -- 22%, 15%, 31% -- **nao
responde nada**. A margem de uma varejista nao se compara com a de uma geradora,
e quem olha a tabela ou ja sabe disso (e a coluna nao acrescenta) ou nao sabe (e
a coluna engana).

O que se compara entre negocios diferentes e a **distancia entre a premissa e o
que aquela companhia entregou**. Projetar 22% para quem entregou 20% e
continuidade; projetar 15% para quem entregou 9% e uma afirmacao sobre mudanca, e
ela precisa de motivo. Lado a lado, as distancias sao comparaveis mesmo quando os
niveis nao sao -- e e assim que o otimismo aparece.

E a mesma ideia do balizador, que ja responde "e muito para esta empresa?" ao
lado de cada campo. Aqui ela atravessa companhias.

Tres coisas que esta peca **nao** faz
-------------------------------------

* **Nao da nota nem ranking.** Ordenar por "quem esta mais barato" converteria
  julgamento em numero e daria ao chute aparencia de medida -- a mesma decisao ja
  tomada em `qualitativo.py`, onde ha teste reprovando quem acrescentar `nota`.
* **Nao decide quais sao comparaveis.** Isso e `pares.py`, e o criterio dele e
  perfil economico. Aqui entra o que o analista poe na mesa, inclusive duas
  versoes da mesma companhia -- que sao tao comparaveis quanto duas companhias.
* **Nao recalcula premissa nenhuma.** Cada valuation e o que o analista salvou.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .historico import AnaliseHistorica, analisar
from .modelo import ResultadoValuation, avaliar
from .premissas import Empresa
from .projeto import Projeto
from .qualidade import RUIM, SEM_DADOS, avaliar_qualidade


def _medio(valores) -> float:
    """A media dos anos projetados de um direcionador, ou NaN."""
    serie = [float(v) for v in (valores or []) if np.isfinite(float(v))]
    return float(np.mean(serie)) if serie else float("nan")


def _mediana(analise: AnaliseHistorica | None, indicador: str) -> float:
    if analise is None:
        return float("nan")
    try:
        return float(analise.mediana(indicador))
    except Exception:
        return float("nan")


@dataclass(frozen=True)
class Premissa:
    """Uma premissa projetada, ao lado do que a companhia entregou.

    A distancia e o que atravessa negocios diferentes: `projetado` e `historico`
    so se comparam dentro da mesma companhia.
    """

    nome: str
    projetado: float
    historico: float

    @property
    def distancia(self) -> float:
        """Projetado menos entregue. Positivo = a projecao pede melhora."""
        if not (np.isfinite(self.projetado) and np.isfinite(self.historico)):
            return float("nan")
        return self.projetado - self.historico

    @property
    def mensuravel(self) -> bool:
        return bool(np.isfinite(self.distancia))


@dataclass(frozen=True)
class ModeloNaMesa:
    """Um valuation salvo, reduzido ao que se compara com os outros."""

    nome: str
    caminho: Path | None = None
    premissas: tuple[Premissa, ...] = ()
    wacc: float = float("nan")
    crescimento_perpetuo: float = float("nan")
    equity_value: float = float("nan")
    valor_por_acao: float = float("nan")
    preco: float = float("nan")
    unidade: str = ""
    qualidade: str = SEM_DADOS
    conversao: float = float("nan")
    erro: str = ""

    @property
    def legivel(self) -> bool:
        return not self.erro

    @property
    def margem_de_seguranca(self) -> float:
        """Quanto o valor excede o preco pedido, em fracao do valor.

        So existe com preco informado -- e preco nao se busca sozinho neste app.
        Sem ele a coluna fica vazia, e nao zerada: zero significaria "esta no
        preco justo", que e uma afirmacao.
        """
        if not (np.isfinite(self.valor_por_acao) and np.isfinite(self.preco)):
            return float("nan")
        if self.valor_por_acao <= 0:
            return float("nan")
        return 1 - self.preco / self.valor_por_acao

    @property
    def otimismo(self) -> float:
        """Fracao das premissas medidas que pede melhora sobre o historico.

        **Nao e nota**: e contagem, e ela vem sempre acompanhada das distancias
        que a produziram. Uma premissa acima do historico pode ter todo motivo --
        o numero diz onde olhar, nao o que concluir.
        """
        medidas = [p for p in self.premissas if p.mensuravel]
        if not medidas:
            return float("nan")
        return sum(1 for p in medidas if p.distancia > 0) / len(medidas)


def _premissas_de(empresa: Empresa, analise: AnaliseHistorica | None) -> tuple[Premissa, ...]:
    """Os direcionadores projetados, cada um contra a mediana entregue.

    Sao os quatro em que "projetado contra entregue" e a mesma grandeza dos dois
    lados. `capital_giro_pct_receita` fica de fora de proposito: o historico mede
    o **saldo** e a serie dele e bem mais volatil que as demais, entao a distancia
    ali diz mais sobre o ano-base do que sobre a premissa.
    """
    op = empresa.operacionais
    tem_recorrente = (
        analise is not None and "Margem EBITDA recorrente" in analise.indicadores.index
    )
    return (
        Premissa(
            "Crescimento da receita",
            _medio(op.crescimento_receita),
            _mediana(analise, "Crescimento da receita"),
        ),
        Premissa(
            "Margem EBITDA",
            _medio(op.margem_ebitda),
            # A **recorrente**, e nao a reportada: e a base que
            # `sugerir_premissas` projeta, e comparar contra a reportada acusaria
            # distancia onde o app so tirou impairment.
            _mediana(analise, "Margem EBITDA recorrente")
            if tem_recorrente
            else _mediana(analise, "Margem EBITDA"),
        ),
        Premissa(
            "Capex / Receita",
            _medio(op.capex_pct_receita),
            _mediana(analise, "Capex / Receita"),
        ),
        Premissa(
            "Depreciacao / Receita",
            _medio(op.depreciacao_pct_receita),
            _mediana(analise, "Depreciacao / Receita"),
        ),
    )


def por_na_mesa(
    projeto: Projeto, nome: str | None = None, caminho: Path | None = None
) -> ModeloNaMesa:
    """Reduz um valuation salvo ao que se compara com os outros.

    Erro de avaliacao **vira linha com o problema visivel**, e nao excecao: um
    projeto quebrado no meio da mesa nao pode derrubar a comparacao dos outros. E
    a mesma regra de `biblioteca.listar`.
    """
    empresa = projeto.empresa
    rotulo = nome or empresa.nome

    analise = None
    if projeto.demonstracoes is not None and getattr(projeto.demonstracoes, "anos", None):
        try:
            analise = analisar(projeto.demonstracoes)
        except Exception:
            analise = None

    try:
        resultado: ResultadoValuation = avaliar(empresa)
    except Exception as erro:
        return ModeloNaMesa(nome=rotulo, caminho=caminho, erro=str(erro))

    qualidade, conversao = SEM_DADOS, float("nan")
    if analise is not None:
        try:
            q = avaliar_qualidade(analise)
            qualidade, conversao = q.veredito, q.conversao_mediana
        except Exception:
            pass

    preco = float("nan")
    alvo = projeto.alvo
    if alvo is not None:
        bruto = getattr(alvo, "preco", None)
        if bruto is not None and np.isfinite(float(bruto)):
            preco = float(bruto)

    por_acao = resultado.dcf.valor_por_acao
    return ModeloNaMesa(
        nome=rotulo,
        caminho=caminho,
        premissas=_premissas_de(empresa, analise),
        wacc=float(resultado.custo_capital.wacc_brl),
        crescimento_perpetuo=float(empresa.perpetuidade.crescimento_perpetuo),
        equity_value=float(resultado.dcf.equity_value),
        valor_por_acao=float(por_acao) if por_acao is not None else float("nan"),
        preco=preco,
        unidade=empresa.unidade,
        qualidade=qualidade,
        conversao=conversao,
    )


@dataclass(frozen=True)
class Carteira:
    """Os modelos na mesa, e as tabelas que os comparam."""

    modelos: list[ModeloNaMesa] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.modelos)

    @property
    def legiveis(self) -> list[ModeloNaMesa]:
        return [m for m in self.modelos if m.legivel]

    @property
    def unidades(self) -> set[str]:
        return {m.unidade for m in self.legiveis if m.unidade}

    @property
    def mistura_unidades(self) -> bool:
        """Modelos em unidades diferentes na mesma tabela.

        Um em R$ mil ao lado de um em R$ milhoes faz a coluna de equity value se
        ler errado por mil vezes, e nada na tabela denuncia. As colunas
        percentuais continuam validas -- por isso isto e aviso e nao recusa.
        """
        return len(self.unidades) > 1

    def resumo(self) -> pd.DataFrame:
        """Uma linha por modelo: o que ele vale e como ele desconta."""
        linhas = [
            {
                "Modelo": m.nome,
                "WACC": m.wacc,
                "g perpetuo": m.crescimento_perpetuo,
                "Equity value": m.equity_value,
                "Valor por acao": m.valor_por_acao,
                "Preco": m.preco,
                "Margem de seguranca": m.margem_de_seguranca,
                "Qualidade dos lucros": m.qualidade,
                "Conversao de caixa": m.conversao,
            }
            for m in self.legiveis
        ]
        return pd.DataFrame(linhas).set_index("Modelo") if linhas else pd.DataFrame()

    def premissas(self) -> pd.DataFrame:
        """Cada premissa projetada ao lado do que aquela companhia entregou.

        Tres colunas por modelo, e nao uma: **projetado, entregue e a
        distancia**. So a terceira atravessa negocios diferentes, e mostrar as
        outras duas e o que permite conferi-la.
        """
        if not self.legiveis:
            return pd.DataFrame()
        nomes = [p.nome for p in self.legiveis[0].premissas]
        linhas = []
        for nome in nomes:
            linha: dict[str, Any] = {"Premissa": nome}
            for m in self.legiveis:
                p = next((x for x in m.premissas if x.nome == nome), None)
                if p is None:
                    continue
                linha[f"{m.nome} - projetado"] = p.projetado
                linha[f"{m.nome} - entregue"] = p.historico
                linha[f"{m.nome} - distancia"] = p.distancia
            linhas.append(linha)
        return pd.DataFrame(linhas).set_index("Premissa")

    def distancias(self) -> pd.DataFrame:
        """So as distancias, que e a tabela que se le atravessando companhias."""
        if not self.legiveis:
            return pd.DataFrame()
        nomes = [p.nome for p in self.legiveis[0].premissas]
        dados = {
            m.nome: [
                next((p.distancia for p in m.premissas if p.nome == nome), float("nan"))
                for nome in nomes
            ]
            for m in self.legiveis
        }
        return pd.DataFrame(dados, index=nomes)

    def leitura(self) -> list[str]:
        """O que a mesa diz, em frases -- sem ranking e sem veredito.

        Aponta **onde olhar**: o modelo cuja projecao mais pede melhora sobre o
        proprio historico, e a premissa que mais se afasta nele. Nao diz qual
        comprar: isso depende de coisas que a tabela nao tem.
        """
        if len(self.legiveis) < 2:
            return []

        frases = []
        if self.mistura_unidades:
            frases.append(
                "**Os modelos estão em unidades diferentes** ("
                + ", ".join(sorted(self.unidades))
                + "). As colunas em percentual continuam comparáveis; as de "
                "valor, não — um modelo em R$ mil ao lado de um em R$ milhões se "
                "lê errado por mil vezes."
            )

        com_otimismo = [m for m in self.legiveis if np.isfinite(m.otimismo)]
        if com_otimismo:
            pior = max(com_otimismo, key=lambda m: m.otimismo)
            medidas = [p for p in pior.premissas if p.mensuravel]
            if pior.otimismo > 0 and medidas:
                maior = max(medidas, key=lambda p: p.distancia)
                frases.append(
                    f"**{pior.nome}** é o modelo cuja projeção mais pede melhora "
                    f"sobre o próprio histórico: {pior.otimismo:.0%} das premissas "
                    "medidas estão acima do entregue, e a que mais se afasta é "
                    f"**{maior.nome}** ({maior.projetado:.1%} projetado contra "
                    f"{maior.historico:.1%} entregue)."
                )
            elif medidas:
                # **Distancia zero e um achado, e nao a ausencia de um.** Modelo
                # derivado do historico pelo botao tem premissa igual a mediana
                # entregue por construcao -- e dizer isso e util: significa que
                # ninguem afirmou nada sobre mudanca ainda, e que o valor que
                # esta na tela e extrapolacao, nao tese.
                frases.append(
                    "**Nenhum destes modelos projeta acima do próprio "
                    "histórico.** As premissas são as medianas entregues, o que "
                    "acontece quando elas foram derivadas do histórico e ainda "
                    "não revisadas: o valor na tela é extrapolação, e não uma "
                    "tese sobre o que vai mudar."
                )

        ruins = [m for m in self.legiveis if m.qualidade == RUIM]
        if ruins:
            frases.append(
                "Qualidade dos lucros **ruim** em "
                + ", ".join(f"**{m.nome}**" for m in ruins)
                + " — a distância entre lucro e caixa muda a leitura do "
                "resultado, e ela entra antes da premissa."
            )
        return frases


def montar(projetos, nomes=None) -> Carteira:
    """Monta a mesa a partir de projetos ja carregados."""
    nomes = list(nomes or [])
    modelos = [
        por_na_mesa(projeto, nome=nomes[i] if i < len(nomes) else None)
        for i, projeto in enumerate(projetos)
    ]
    return Carteira(modelos=modelos)


def montar_da_biblioteca(caminhos) -> Carteira:
    """Monta a mesa a partir de valuations guardados na biblioteca."""
    from .biblioteca import abrir

    modelos = []
    for caminho in caminhos:
        alvo = Path(caminho)
        try:
            projeto = abrir(alvo)
        except Exception as erro:
            modelos.append(ModeloNaMesa(nome=alvo.stem, caminho=alvo, erro=str(erro)))
            continue
        modelos.append(por_na_mesa(projeto, caminho=alvo))
    return Carteira(modelos=modelos)
