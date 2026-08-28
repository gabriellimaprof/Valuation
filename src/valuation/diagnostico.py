"""Diagnostico automatico do modelo: o app criticando o proprio valuation.

Um DCF sempre devolve um numero. O numero ser *defensavel* depende de coisas
que a aritmetica nao verifica: crescer para sempre acima da economia, crescer
sem reinvestir, projetar margem que a empresa nunca entregou, deixar a
perpetuidade responder por quase todo o valor.

Cada achado explica o que foi encontrado, por que aquilo importa e o que fazer
-- e nao apenas que algo esta fora de um intervalo. Para um analista em
formacao, esta e a parte do app que ensina; para um analista experiente, e a
checklist que ninguem lembra de rodar inteira antes de mandar o material.

As faixas usadas sao heuristicas de mercado, nao leis. Um achado e um convite a
justificar a premissa, nunca uma proibicao.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .dcf import valor_terminal_gordon
from .historico import AnaliseHistorica
from .qualidade import CGO_BOM
from .modelo import ResultadoValuation

ERRO = "erro"
ALERTA = "alerta"
INFORMACAO = "informacao"

_ORDEM_SEVERIDADE = {ERRO: 0, ALERTA: 1, INFORMACAO: 2}


def _pct(valor: float, casas: int = 1) -> str:
    """Percentual no padrao brasileiro, com virgula decimal.

    Os achados sao lidos por quem trabalha em portugues; "9,0%" e o que essa
    pessoa espera ver, e "9.0%" destoa do resto do app.
    """
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def _num(valor: float, casas: int = 1) -> str:
    """Numero no padrao brasileiro: milhar com ponto, decimal com virgula."""
    if not np.isfinite(valor):
        return "n/d"
    return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")

# Faixas de referencia. Deliberadamente largas: servem para pegar o absurdo, nao
# para impor uma visao de mundo.
BETA_MINIMO, BETA_MAXIMO = 0.3, 2.5
WACC_MINIMO_BRL, WACC_MAXIMO_BRL = 0.07, 0.30
PESO_PERPETUIDADE_ALTO = 0.75
# Duas grandezas diferentes, que por descuido dividiam o mesmo corte: D/E mede
# divida sobre patrimonio, ND/EBITDA mede divida sobre geracao de caixa. Que os
# dois numeros calhassem de ser 3,5 era coincidencia, nao calibracao -- e o corte
# unico dava a impressao de que uma medicao valia para os dois.
#
# Medido nas companhias de 2024, mediana de 2020-2024 por companhia:
#
#   ND/EBITDA  n=449  P50 1,93  P75 3,40  P90 6,23  -> 3,5 acusa 23,4%
#   D/E        n=420  P50 0,93  P75 1,79  P90 3,23  -> 2,0 acusa 21,0%
#
# E o 3,5 compartilhado acusava so **8,6%** em D/E: nao era um corte alto, era um
# corte que quase nunca disparava, mascarado por parecer calibrado.
DIVIDA_EBITDA_ALTA = 3.5
DIVIDA_PL_ALTA = 2.0
MARGEM_ROIC_WACC_EXCEPCIONAL = 0.10
# Acima disto, o retorno passa a depender mais do mercado do que da empresa.
PESO_RERATING_ALTO = 0.40
TSR_IMPLAUSIVEL = 0.40
# Abaixo disto, a maior parte do EBITDA nao chega ao caixa. Nao e defeito por si
# -- empresa que cresce rapido prende caixa no giro --, mas precisa de explicacao.
#
# Era 0,60 e acusava 47,3% das 423 companhias medidas. Com o juro pago ja
# padronizado no operacional, a mediana brasileira converte 54% -- o FCO e
# liquido de imposto e de juro, e o EBITDA e antes dos dois. O corte e o quartil
# inferior observado.
CONVERSAO_CAIXA_BAIXA = 0.15
# Descolamento entre o juro da DRE e o juro pago que merece o achado.
#
# Era 0,02, e disparava em **82,3% das 368 companhias** que publicam os dois
# numeros: a linha 3.06.02 da CVM junta variacao cambial e monetaria de todo o
# passivo, entao a mediana brasileira ja descola sem nada de anormal.
#
# O corte e o **P75 da safra corrente**, e ele se move: em 2020-2024 era 16,9
# p.p., e em 2021-2025 e **10,0 p.p.** A distribuicao encolheu quando 2020 saiu
# da janela -- ano de desvalorizacao forte do real -- e as correcoes de leitura
# do juro pago entraram. Mantido o corte antigo, ele acusaria 4,2% da amostra
# nova, e o de severidade alta acusaria **zero**: sinal que nunca dispara e tao
# inutil quanto o que dispara sempre. Ver ``referencias.DESCOLAMENTO_DO_JURO``.
JUROS_CAPITALIZADOS = 0.100
# A partir daqui o arrendamento deixa de ser detalhe da divida e passa a mudar a
# leitura do EBITDA e da alavancagem. Em Petrobras chega a metade.
#
# Medido: o peso do aluguel no EBITDA tem P75 de **0,206** nas 297 companhias que
# publicam o desembolso, e o corte acusa 26,3%. E o quartil, por acaso e nao por
# projeto -- mas agora esta medido.
# Reconferido na safra 2021-2025 (n=417): P75 = 0,227, e o corte de 0,20 cai no
# **percentil 71**. Segue sendo o quartil alto, como foi calibrado.
#
# A distribuicao e bimodal na pratica -- P10 = 0 e P95 = 1,0 --, entao a mediana
# de 4,1% engana: ou a companhia quase nao tem arrendamento, ou ele **e** a
# divida dela. E isso que faz o corte valer a pena.
LEASING_RELEVANTE = 0.20



# A distancia a partir da qual as premissas deixam de poder descrever a
# companhia importada. E folgada de proposito: quem normaliza uma receita
# ciclica, ou projeta a partir de um ano-base que nao e o ultimo, continua
# descrevendo a mesma empresa. O que este corte pega e a **troca de companhia**
# -- o modelo de partida tem receita de 1.000 e 100 milhoes de acoes, e a WEG
# importada tem 41 bilhoes e 4,2 bilhoes de acoes: fatores de 41x e 42x.
FATOR_DE_OUTRA_COMPANHIA = 3.0


def premissas_descrevem_o_historico(empresa, demonstracoes) -> str | None:
    """Por que o modelo **nao** descreve o historico importado, ou ``None``.

    Existe porque importar as demonstracoes adota o nome da companhia mas nao as
    premissas -- deriva-las e um clique separado, e deve continuar sendo: aplicar
    sozinho sobrescreveria o que o analista ja tivesse montado.

    O que nao pode e o intervalo entre as duas coisas ficar **calado**. Depois de
    importar a WEG, a barra lateral e o Inicio anunciavam "WEG SA -- Equity Value
    698,8" e "R$ 6,99 por acao": os numeros da empresa de partida, com o nome da
    companhia em cima. Um valuation de outra empresa assinado com o nome da
    certa e o mesmo defeito que o nome padrao ja tinha causado, pelo lado
    oposto -- e este e pior, porque o numero e plausivel.

    Compara **escala**, e nao igualdade: receita-base e numero de acoes. Sao as
    duas grandezas que nao sobrevivem a troca de companhia.
    """
    if demonstracoes is None or not getattr(demonstracoes, "anos", None):
        return None

    def _fora_de_escala(do_modelo: float, do_historico: float) -> bool:
        if not np.isfinite(do_modelo) or not np.isfinite(do_historico):
            return False
        if do_modelo <= 0 or do_historico <= 0:
            return False
        maior, menor = max(do_modelo, do_historico), min(do_modelo, do_historico)
        return maior / menor > FATOR_DE_OUTRA_COMPANHIA

    # **Este texto vai para a tela**, e por isso vem acentuado. O resto do
    # modulo escreve em ASCII por ser codigo; o que o usuario le, nao.
    unidade = f" {empresa.unidade}" if getattr(empresa, "unidade", "") else ""

    razoes = []
    try:
        receita = float(demonstracoes.valor("receita_liquida"))
    except Exception:  # noqa: BLE001 -- historico sem a conta nao acusa nada
        receita = float("nan")
    if _fora_de_escala(empresa.operacionais.receita_base, receita):
        razoes.append(
            f"a receita-base do modelo é {_num(empresa.operacionais.receita_base)}"
            f"{unidade} e o último exercício importado tem {_num(receita)}"
        )

    try:
        acoes = float(demonstracoes.valor("acoes_em_circulacao"))
    except Exception:  # noqa: BLE001
        acoes = float("nan")
    if _fora_de_escala(empresa.ponte.acoes_em_circulacao, acoes):
        razoes.append(
            f"o modelo tem {_num(empresa.ponte.acoes_em_circulacao)} ações e a "
            f"companhia importada tem {_num(acoes)}"
        )

    if not razoes:
        return None
    return "; ".join(razoes)


@dataclass(frozen=True)
class Achado:
    """Um ponto do modelo que merece atencao, com o porque e o que fazer."""

    codigo: str
    severidade: str
    titulo: str
    detalhe: str
    acao: str = ""
    referencia: str = ""

    @property
    def icone(self) -> str:
        return {ERRO: "🔴", ALERTA: "🟡", INFORMACAO: "🔵"}.get(self.severidade, "•")


@dataclass(frozen=True)
class Diagnostico:
    """Conjunto de achados de um modelo, do mais grave para o menos."""

    achados: list[Achado] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.achados)

    def por_severidade(self, severidade: str) -> list[Achado]:
        return [a for a in self.achados if a.severidade == severidade]

    @property
    def erros(self) -> list[Achado]:
        return self.por_severidade(ERRO)

    @property
    def alertas(self) -> list[Achado]:
        return self.por_severidade(ALERTA)

    @property
    def aprovado(self) -> bool:
        """O modelo passou sem nenhum achado grave?"""
        return not self.erros

    def tabela(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Severidade": a.severidade,
                    "Achado": a.titulo,
                    "Detalhe": a.detalhe,
                    "O que fazer": a.acao,
                    "Referencia": a.referencia,
                }
                for a in self.achados
            ]
        )


def _ordenar(achados: list[Achado]) -> list[Achado]:
    return sorted(achados, key=lambda a: _ORDEM_SEVERIDADE.get(a.severidade, 9))


def diagnosticar(
    resultado: ResultadoValuation,
    analise: AnaliseHistorica | None = None,
    crescimento_nominal_economia: float | None = None,
    retorno=None,
) -> Diagnostico:
    """Roda a bateria de verificacoes sobre um valuation ja calculado.

    ``analise`` habilita as comparacoes com o historico da propria empresa, que
    sao as mais uteis: uma margem de 25% nao e otimista em abstrato, e otimista
    para quem entregou 18% nos ultimos cinco anos.

    ``crescimento_nominal_economia`` e o teto natural do crescimento perpetuo.
    Sem ele, vem da propria macro da empresa: inflacao de longo prazo composta
    com o PIB real. Antes eram 2% de PIB real fixos no codigo, o que fazia o
    teto ignorar quem tinha estressado a macro.

    ``retorno`` e uma ``DecomposicaoTSR`` ja calculada. Com ela, a checklist
    passa a cobrir tambem a tese de retorno -- de onde vem o ganho esperado e se
    ele compensa o risco -- e nao apenas a consistencia interna do fluxo.
    """
    empresa = resultado.empresa
    wacc = resultado.dcf.taxa_desconto
    g = empresa.perpetuidade.crescimento_perpetuo
    if crescimento_nominal_economia is None:
        crescimento_nominal_economia = empresa.macro.pib_nominal

    achados: list[Achado] = []
    achados += _checar_perpetuidade(resultado, g, wacc, crescimento_nominal_economia)
    achados += _checar_reinvestimento(resultado, g, wacc)
    achados += _checar_capex_perpetuo(resultado)
    achados += _checar_custo_de_capital(resultado, wacc)
    achados += _checar_estrutura_do_valor(resultado)
    # Nao exige historico: a hipotese esta nas premissas e no resultado, e
    # vale igual para quem modelou a mao sem importar demonstracao nenhuma.
    achados += _checar_perpetuidade_do_arrendamento(resultado)
    achados += _checar_fosso_perpetuo(resultado, analise)
    if analise is not None:
        achados += _checar_equivalencia_no_ebit(analise)
    if analise is not None:
        achados += _checar_contra_historico(resultado, analise)
    if retorno is not None:
        achados += _checar_retorno(resultado, retorno)

    return Diagnostico(achados=_ordenar(achados))


def _checar_retorno(resultado: ResultadoValuation, retorno) -> list[Achado]:
    """Verificacoes sobre a tese de retorno, e nao sobre o fluxo de caixa."""
    achados = []
    ke = resultado.custo_capital.ke_brl
    tsr = retorno.tsr
    if not np.isfinite(tsr):
        return achados

    if tsr < ke:
        achados.append(
            Achado(
                codigo="retorno_abaixo_do_exigido",
                severidade=ALERTA,
                titulo=(
                    f"Retorno esperado ({_pct(tsr)}) abaixo do exigido ({_pct(ke)})"
                ),
                detalhe=(
                    "A este preço, o investimento entrega menos do que o risco da "
                    f"empresa pede — uma diferença de {_pct(ke - tsr)} ao ano. Comprar "
                    "assim é aceitar ser mal remunerado pelo risco assumido."
                ),
                acao=(
                    "Veja em Retorno esperado qual o preço máximo para o retorno que "
                    "você exige, ou revise as premissas que sustentam o lucro projetado."
                ),
                referencia="CFA Institute, Equity Asset Valuation, cap. 1",
            )
        )

    peso = abs(retorno.contribuicao_multiplo) / abs(tsr) if tsr else float("nan")
    if np.isfinite(peso) and peso > PESO_RERATING_ALTO:
        direcao = "expansão" if retorno.contribuicao_multiplo > 0 else "contração"
        achados.append(
            Achado(
                codigo="retorno_depende_de_rerating",
                severidade=ALERTA,
                titulo=f"{_pct(peso, 0)} do retorno vem de {direcao} de múltiplo",
                detalhe=(
                    "Essa parcela não depende de a empresa entregar coisa alguma: "
                    "depende de quanto o próximo comprador estará disposto a pagar. "
                    "Uma tese apoiada principalmente aí é uma aposta sobre o humor do "
                    "mercado, não sobre o negócio."
                ),
                acao=(
                    "Explicite por que o mercado reavaliaria a empresa, e calcule o "
                    "retorno no cenário em que o múltiplo não muda."
                ),
                referencia="Damodaran, The Little Book of Valuation, cap. 7",
            )
        )

    if tsr > TSR_IMPLAUSIVEL:
        achados.append(
            Achado(
                codigo="retorno_implausivel",
                severidade=ALERTA,
                titulo=f"Retorno esperado de {_pct(tsr, 0)} ao ano",
                detalhe=(
                    "Retornos dessa ordem raramente sobrevivem a uma revisão. Costumam "
                    "vir de preço de entrada muito abaixo do valor, de crescimento "
                    "otimista ou de múltiplo de saída generoso — e o mercado "
                    "dificilmente deixaria uma oportunidade dessas de pé."
                ),
                acao=(
                    "Confira o preço de entrada e o múltiplo de saída antes de "
                    "defender o número."
                ),
                referencia="",
            )
        )

    entrada, saida = retorno.multiplo_entrada, retorno.multiplo_saida
    if entrada > 0 and saida > entrada * 1.2:
        achados.append(
            Achado(
                codigo="multiplo_de_saida_generoso",
                severidade=INFORMACAO,
                titulo=(
                    f"Múltiplo de saída ({_num(saida, 1)}x) mais de 20% acima do de "
                    f"entrada ({_num(entrada, 1)}x)"
                ),
                detalhe=(
                    "O modelo assume vender mais caro, por real de lucro, do que "
                    "comprou. É possível, mas é uma hipótese sobre o mercado que "
                    "convém estar consciente."
                ),
                acao="Rode também com o múltiplo de saída igual ao de entrada.",
                referencia="",
            )
        )

    return achados


def _checar_perpetuidade(
    resultado: ResultadoValuation, g: float, wacc: float, teto_economia: float
) -> list[Achado]:
    achados = []
    perp = resultado.empresa.perpetuidade

    if perp.metodo == "gordon":
        if g > teto_economia:
            achados.append(
                Achado(
                    codigo="g_acima_da_economia",
                    severidade=ALERTA,
                    titulo=f"Crescimento perpétuo de {_pct(g, 1)} supera a economia",
                    detalhe=(
                        f"O modelo faz a empresa crescer {_pct(g, 1)} para sempre, acima do "
                        f"crescimento nominal estimado da economia ({_pct(teto_economia, 1)}). "
                        "Crescer acima da economia para sempre significa que a empresa "
                        "acabaria por se tornar maior que o próprio PIB."
                    ),
                    acao=(
                        f"Reduza o crescimento perpétuo para no máximo {_pct(teto_economia, 1)}, "
                        "ou alongue a projeção explícita se a empresa ainda tem uma fase "
                        "de crescimento acelerado a percorrer."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 12 (stable growth)",
                )
            )
        if wacc - g < 0.02:
            achados.append(
                Achado(
                    codigo="spread_wacc_g_estreito",
                    severidade=ALERTA,
                    titulo="Diferença entre WACC e crescimento perpétuo muito estreita",
                    detalhe=(
                        f"WACC de {_pct(wacc, 2)} contra crescimento de {_pct(g, 2)}: o denominador "
                        f"da perpetuidade e apenas {_pct(wacc - g, 2)}. Nessa faixa, uma "
                        "mudanca de 0,5 p.p. em qualquer um dos dois altera o valor da "
                        "empresa em dezenas de por cento."
                    ),
                    acao=(
                        "Olhe a tabela de sensibilidade antes de defender o número: "
                        "provavelmente a faixa de valor e larga demais para um número único."
                    ),
                    referencia="CFA Institute, Equity Asset Valuation, cap. 4",
                )
            )

        roic_perp = perp.roic_perpetuidade
        if roic_perp is None and g > 0:
            achados.append(
                Achado(
                    codigo="perpetuidade_sem_reinvestimento",
                    severidade=ALERTA,
                    titulo="Crescimento perpétuo sem reinvestimento explícito",
                    detalhe=(
                        f"A perpetuidade cresce {_pct(g, 1)} ao ano a partir do fluxo do ultimo "
                        "ano projetado, sem exigir reinvestimento para sustentar esse "
                        "crescimento. Isso costuma superestimar o valor terminal, porque "
                        "crescer para sempre exige investir para sempre."
                    ),
                    acao=(
                        "Informe o ROIC de perpetuidade. O modelo passa a descontar do "
                        "fluxo perpétuo a taxa de reinvestimento g/ROIC, que e a forma "
                        "consistente de crescer."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 12",
                )
            )
        elif roic_perp is not None:
            if perp.ancora != "livre" and perp.roic_real is None:
                achados.append(
                    Achado(
                        codigo="reinvestimento_nao_indexado",
                        severidade=INFORMACAO,
                        titulo="ROIC perpétuo fixo com crescimento ancorado na macro",
                        detalhe=(
                            f"O crescimento perpétuo é derivado da inflação, mas o ROIC de "
                            f"{_pct(roic_perp, 1)} fica parado. Como a taxa de reinvestimento "
                            f"é g/ROIC — hoje {_pct(g / roic_perp, 1)} do NOPAT —, estressar "
                            "a inflação sobe o numerador e deixa o denominador onde estava. "
                            "O modelo passa a cobrar capital que a inflação não pediu, e o "
                            "estresse de inflação sai exagerado."
                        ),
                        acao=(
                            "Informe o ROIC em termos reais (roic_real) para que o nominal "
                            "acompanhe a inflação. O valor de hoje não muda — muda só a "
                            "resposta ao estresse macro."
                        ),
                        referencia="Damodaran, Investment Valuation, cap. 12 (inflation)",
                    )
                )
            if roic_perp <= wacc:
                achados.append(
                    Achado(
                        codigo="roic_perpetuo_abaixo_do_wacc",
                        severidade=ALERTA,
                        titulo=f"ROIC perpétuo ({_pct(roic_perp, 1)}) não supera o WACC ({_pct(wacc, 1)})",
                        detalhe=(
                            "Quando o retorno sobre o capital não supera o custo do capital, "
                            "cada real reinvestido destrói valor. Nesse regime, crescer "
                            "*reduz* o valor da empresa em vez de aumenta-lo."
                        ),
                        acao=(
                            "Se essa é mesmo a realidade do negócio, considere crescimento "
                            "perpétuo zero: a empresa vale mais distribuindo caixa do que "
                            "reinvestindo."
                        ),
                        referencia="Damodaran, The Little Book of Valuation, cap. 4",
                    )
                )
            elif roic_perp - wacc > MARGEM_ROIC_WACC_EXCEPCIONAL:
                achados.append(
                    Achado(
                        codigo="roic_perpetuo_excepcional",
                        severidade=ALERTA,
                        titulo=f"ROIC perpétuo {_pct(roic_perp - wacc, 1)} acima do WACC, para sempre",
                        detalhe=(
                            f"O modelo assume ROIC de {_pct(roic_perp, 1)} contra WACC de "
                            f"{_pct(wacc, 1)} em perpetuidade. Manter esse spread para sempre "
                            "equivale a supor uma barreira de entrada que nunca e erodida "
                            "pela concorrência."
                        ),
                        acao=(
                            "Justifique a vantagem competitiva (marca, rede, licença, "
                            "escala) ou aproxime o ROIC perpétuo do WACC."
                        ),
                        referencia="Damodaran, Investment Valuation, cap. 12",
                    )
                )

    return achados


def _checar_reinvestimento(
    resultado: ResultadoValuation, g: float, wacc: float
) -> list[Achado]:
    achados = []
    proj = resultado.projecao

    capex_final = float(proj.capex[-1])
    deprec_final = float(proj.depreciacao[-1])
    if deprec_final > 0 and capex_final < deprec_final and g > 0:
        achados.append(
            Achado(
                codigo="capex_abaixo_da_depreciacao",
                severidade=ALERTA,
                titulo="Empresa entra na perpetuidade investindo menos do que deprecia",
                detalhe=(
                    f"No ultimo ano projetado o capex e {_num(capex_final / deprec_final, 2)}x a "
                    f"depreciacao, mas a empresa cresce {_pct(g, 1)} para sempre depois disso. "
                    "Uma base de ativos que encolhe não sustenta receita que cresce."
                ),
                acao=(
                    "Eleve o capex do ultimo ano para ao menos o nivel da depreciacao, ou "
                    "use a normalizacao por ROIC na perpetuidade."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
            )
        )

    # ROIC marginal: quanto de NOPAT adicional cada real reinvestido gerou.
    nopat = proj.nopat
    reinvestimento = proj.capex - proj.depreciacao + proj.variacao_capital_giro
    if len(nopat) >= 2:
        delta_nopat = np.diff(nopat)
        base = reinvestimento[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            roic_marginal = np.where(base > 0, delta_nopat / base, np.nan)
        validos = roic_marginal[np.isfinite(roic_marginal)]
        if validos.size:
            mediana = float(np.median(validos))
            if mediana > 1.0:
                achados.append(
                    Achado(
                        codigo="roic_marginal_implausivel",
                        severidade=ALERTA,
                        titulo=f"Retorno sobre o capital novo implícito de {_pct(mediana, 0)}",
                        detalhe=(
                            "A projeção gera NOPAT adicional muito acima do que reinveste: "
                            f"cada real investido produz {_num(mediana, 2)} de lucro operacional "
                            "por ano. Isso normalmente indica margem crescendo sem que o "
                            "modelo cobre o investimento correspondente."
                        ),
                        acao=(
                            "Confira capex e capital de giro projetados. Crescimento de "
                            "receita quase sempre exige capital de giro proporcional."
                        ),
                        referencia="Damodaran, Investment Valuation, cap. 11",
                    )
                )
            elif mediana < 0:
                achados.append(
                    Achado(
                        codigo="roic_marginal_negativo",
                        severidade=ALERTA,
                        titulo="A projeção reinveste e o lucro operacional cai",
                        detalhe=(
                            "O NOPAT projetado diminui apesar do reinvestimento. Se isso e "
                            "intencional (setor em declínio), tudo bem; se não, há "
                            "inconsistência entre margens e investimento."
                        ),
                        acao="Reveja a trajetoria de margens frente ao capex projetado.",
                        referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
                    )
                )

    return achados


def _checar_custo_de_capital(resultado: ResultadoValuation, wacc: float) -> list[Achado]:
    achados = []
    cc = resultado.custo_capital
    premissas = resultado.empresa.custo_capital

    if not BETA_MINIMO <= cc.beta_realavancado <= BETA_MAXIMO:
        achados.append(
            Achado(
                codigo="beta_fora_da_faixa",
                severidade=ALERTA,
                titulo=f"Beta realavancado de {_num(cc.beta_realavancado, 2)} fora da faixa usual",
                detalhe=(
                    f"Betas de empresas listadas concentram-se entre {_num(BETA_MINIMO, 1)} e "
                    f"{_num(BETA_MAXIMO, 1)}. Fora dessa faixa costuma haver erro no beta do "
                    "setor ou na estrutura de capital alvo."
                ),
                acao="Confira o beta do setor e o D/E alvo usado para realavancar.",
                referencia="CFA Institute, Equity Asset Valuation, cap. 2",
            )
        )

    if not WACC_MINIMO_BRL <= wacc <= WACC_MAXIMO_BRL:
        achados.append(
            Achado(
                codigo="wacc_fora_da_faixa",
                severidade=ALERTA,
                titulo=f"WACC de {_pct(wacc, 2)} fora da faixa típica em BRL nominal",
                detalhe=(
                    f"Para empresas brasileiras, o WACC nominal em reais costuma ficar "
                    f"entre {_pct(WACC_MINIMO_BRL, 0)} e {_pct(WACC_MAXIMO_BRL, 0)}. Valores fora "
                    "disso geralmente vem de taxa livre de risco, risco-país ou inflacao "
                    "informados em unidade errada."
                ),
                acao="Confira se todas as taxas estão em decimais (0,045 e não 4,5).",
                referencia="Damodaran, country risk premiums",
            )
        )

    if cc.kd_bruto_brl > cc.ke_brl:
        achados.append(
            Achado(
                codigo="kd_acima_do_ke",
                severidade=ALERTA,
                titulo="Custo da dívida acima do custo do capital próprio",
                detalhe=(
                    f"Kd de {_pct(cc.kd_bruto_brl, 2)} contra Ke de {_pct(cc.ke_brl, 2)}. O credor "
                    "tem prioridade sobre o acionista no recebimento, entao normalmente "
                    "exige menos retorno. O inverso sugere erro em uma das duas pontas."
                ),
                acao="Reveja o spread de crédito ou o premio de risco do equity.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    if premissas.divida_pl_alvo > DIVIDA_PL_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_alvo_alta",
                severidade=INFORMACAO,
                titulo=f"Estrutura de capital alvo bastante alavancada (D/E {_num(premissas.divida_pl_alvo, 1)})",
                detalhe=(
                    "Com essa alavancagem, o beta realavancado e o custo da dívida deveriam "
                    "refletir risco de crédito relevante. O modelo não ajusta isso sozinho."
                ),
                acao="Considere elevar o spread de crédito coerentemente com a alavancagem.",
                referencia="Damodaran, Applied Corporate Finance, cap. 8",
            )
        )

    return achados


def _checar_estrutura_do_valor(resultado: ResultadoValuation) -> list[Achado]:
    achados = []
    peso = resultado.dcf.peso_perpetuidade

    if np.isfinite(peso) and peso > PESO_PERPETUIDADE_ALTO:
        achados.append(
            Achado(
                codigo="peso_da_perpetuidade",
                severidade=ALERTA,
                titulo=f"{_pct(peso, 0)} do valor vem da perpetuidade",
                detalhe=(
                    "Quase todo o valor está depois do horizonte projetado, ou seja, "
                    "depende de duas premissas (crescimento perpétuo e taxa de desconto) "
                    "em vez das projeções que você construiu linha a linha."
                ),
                acao=(
                    "Alongue a projeção explícita até a empresa atingir maturidade -- "
                    "normalmente 7 a 10 anos para empresas ainda em crescimento."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 12",
            )
        )

    if resultado.equity_value <= 0:
        achados.append(
            Achado(
                codigo="equity_negativo",
                severidade=ERRO,
                titulo="Valor do equity negativo ou nulo",
                detalhe=(
                    f"O Enterprise Value de {_num(resultado.enterprise_value, 1)} não cobre a "
                    "dívida líquida e os demais itens da ponte. Ou a empresa está "
                    "efetivamente insolvente, ou há erro de unidade entre a projeção e o "
                    "balanço."
                ),
                acao=(
                    "Confirme que projeção e ponte estão na mesma unidade (ambas em R$ mil "
                    "ou ambas em R$ milhões)."
                ),
                referencia="",
            )
        )

    fluxos_negativos = int((resultado.dcf.fluxos < 0).sum())
    if fluxos_negativos and fluxos_negativos == len(resultado.dcf.fluxos):
        achados.append(
            Achado(
                codigo="todos_os_fluxos_negativos",
                severidade=ERRO,
                titulo="Todos os fluxos de caixa projetados são negativos",
                detalhe=(
                    "A empresa queima caixa em todo o horizonte explícito e ainda assim "
                    "recebe um valor terminal positivo. O valor fica inteiramente apoiado "
                    "em uma recuperacao que o modelo não mostra."
                ),
                acao="Alongue a projeção até o ano em que a empresa passa a gerar caixa.",
                referencia="Damodaran, Valuing Young and Distressed Companies",
            )
        )
    elif fluxos_negativos:
        achados.append(
            Achado(
                codigo="fluxos_negativos",
                severidade=INFORMACAO,
                titulo=f"{fluxos_negativos} ano(s) com fluxo de caixa negativo",
                detalhe=(
                    "Normal em fase de investimento pesado, mas exige que a empresa "
                    "tenha como financiar o período."
                ),
                acao="Confira se a estrutura de capital projetada suporta a queima.",
                referencia="",
            )
        )

    return achados


def _checar_contra_historico(
    resultado: ResultadoValuation, analise: AnaliseHistorica
) -> list[Achado]:
    """Compara as premissas projetadas com o que a empresa de fato entregou."""
    achados = []
    proj = resultado.projecao

    margem_projetada = float(np.median(proj.ebitda / proj.receita))
    margens_hist = analise.linha("Margem EBITDA").replace([np.inf, -np.inf], np.nan).dropna()
    if not margens_hist.empty:
        maxima, minima = float(margens_hist.max()), float(margens_hist.min())
        if margem_projetada > maxima + 0.02:
            achados.append(
                Achado(
                    codigo="margem_acima_do_historico",
                    severidade=ALERTA,
                    titulo=(
                        f"Margem EBITDA projetada ({_pct(margem_projetada, 1)}) acima do melhor "
                        f"ano histórico ({_pct(maxima, 1)})"
                    ),
                    detalhe=(
                        "O modelo assume que a empresa passa a operar acima do melhor "
                        "desempenho que ja teve, e mantem esse patamar."
                    ),
                    acao=(
                        "Explicite o que muda: ganho de escala, mix, reestruturação, "
                        "repasse de preço. Sem uma razão concreta, use a mediana histórica."
                    ),
                    referencia="CFA Institute, Financial Statement Analysis",
                )
            )
        elif margem_projetada < minima - 0.02:
            achados.append(
                Achado(
                    codigo="margem_abaixo_do_historico",
                    severidade=INFORMACAO,
                    titulo=(
                        f"Margem EBITDA projetada ({_pct(margem_projetada, 1)}) abaixo do pior "
                        f"ano histórico ({_pct(minima, 1)})"
                    ),
                    detalhe="A projeção e mais conservadora do que qualquer ano ja realizado.",
                    acao="Confirme se o conservadorismo e intencional.",
                    referencia="",
                )
            )

    crescimento_projetado = float(np.median(np.diff(proj.receita) / proj.receita[:-1])) if len(proj.receita) > 1 else float("nan")
    cagr_hist = analise.mediana("Crescimento da receita")
    if np.isfinite(crescimento_projetado) and np.isfinite(cagr_hist):
        if crescimento_projetado > cagr_hist + 0.05:
            achados.append(
                Achado(
                    codigo="crescimento_acima_do_historico",
                    severidade=ALERTA,
                    titulo=(
                        f"Crescimento projetado ({_pct(crescimento_projetado, 1)}) bem acima do "
                        f"histórico ({_pct(cagr_hist, 1)})"
                    ),
                    detalhe=(
                        "A aceleracao precisa vir de algum lugar: novo mercado, nova "
                        "capacidade, aquisição. Nenhum deles e gratuito."
                    ),
                    acao=(
                        "Verifique se o capex projetado comporta a expansão de receita "
                        "assumida."
                    ),
                    referencia="Damodaran, Investment Valuation, cap. 11",
                )
            )

    # --- contraprovas de caixa, quando a origem trouxe a DFC aberta ---------

    conversao = analise.mediana("Conversao de caixa (FCO / EBITDA)")
    if np.isfinite(conversao) and conversao < CONVERSAO_CAIXA_BAIXA:
        # **Antes de acusar a operacao, olhar o degrau de cima.** O FCO e liquido
        # de giro, imposto e juro; o caixa gerado pelas operacoes nao e. Medido
        # em 2024, metade da base tem CGO alto e FCO baixo -- nelas o resultado
        # vira caixa, e o que consome esta abaixo da operacao. Um achado que diz
        # "receita reconhecida antes de ser recebida" ali manda o analista
        # procurar no lugar errado.
        operacional = analise.mediana("Conversao operacional (CGO / EBITDA)")
        gera_caixa = np.isfinite(operacional) and operacional >= CGO_BOM
        achados.append(
            Achado(
                codigo="ebitda_nao_vira_caixa",
                severidade=ALERTA,
                titulo=(
                    f"Só {_pct(conversao, 0)} do EBITDA virou caixa, mas a "
                    f"operação converte {_pct(operacional, 0)}"
                    if gera_caixa
                    else f"Só {_pct(conversao, 0)} do EBITDA virou caixa operacional"
                ),
                detalhe=(
                    "O EBITDA é o ponto de partida do valor, mas quem paga dívida "
                    "e dividendo é o caixa. **Aqui o resultado vira caixa**: o "
                    "caixa gerado pelas operações é "
                    f"{_pct(operacional, 0)} do EBITDA. A distância até o FCO "
                    "está no capital de giro, no imposto de renda e no juro "
                    "pagos — que são consumo abaixo da operação, e não sinal de "
                    "resultado que não se realiza."
                    if gera_caixa
                    else "O EBITDA é o ponto de partida do valor, mas quem paga "
                    "dívida e dividendo é o caixa. Conversão baixa e persistente "
                    "**já no caixa gerado pelas operações** costuma significar "
                    "lucro preso no capital de giro ou receita reconhecida antes "
                    "de ser recebida."
                ),
                acao=(
                    "Veja a ponte EBITDA → CGO → FCO no histórico para saber qual "
                    "dos três consome, e quanto. Se for juro, o problema é de "
                    "estrutura de capital, não de operação."
                    if gera_caixa
                    else "Olhe o investimento em giro no histórico antes de "
                    "projetar margem estável."
                ),
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 20",
            )
        )

    achados += _checar_arrendamento_projetado(resultado, analise)
    achados += _checar_itens_nao_recorrentes(resultado, analise)

    leasing = analise.ultimo("Arrendamento / Divida bruta")
    if np.isfinite(leasing) and leasing > LEASING_RELEVANTE:
        achados.append(
            Achado(
                codigo="divida_e_muito_arrendamento",
                severidade=INFORMACAO,
                titulo=f"{_pct(leasing, 0)} da dívida bruta é arrendamento (IFRS 16)",
                detalhe=(
                    "Desde 2019 o aluguel vira ativo de direito de uso e passivo de "
                    "arrendamento, e a despesa sai do EBITDA para virar depreciação "
                    "mais juros. Duas consequências: o EBITDA fica maior do que era "
                    "antes da norma, e essa dívida já está no balanço."
                ),
                acao=(
                    "Não capitalize o aluguel de novo — contaria a mesma dívida duas "
                    "vezes. Ao comparar múltiplos, confirme que os pares seguem a "
                    "mesma norma."
                ),
                referencia="CPC 06 (R2) / IFRS 16",
            )
        )

    kd_competencia = analise.mediana("Custo da divida efetivo")
    kd_caixa = analise.mediana("Custo da divida pelo caixa")
    if (
        np.isfinite(kd_competencia)
        and np.isfinite(kd_caixa)
        and kd_competencia > kd_caixa + JUROS_CAPITALIZADOS
    ):
        achados.append(
            Achado(
                codigo="juros_capitalizados",
                severidade=INFORMACAO,
                titulo=(
                    f"A despesa financeira ({_pct(kd_competencia, 1)} da dívida) supera "
                    f"o juro efetivamente pago ({_pct(kd_caixa, 1)})"
                ),
                detalhe=(
                    "Parte do custo da dívida não saiu do caixa no período: pode ter "
                    "sido capitalizada em obra, acumulada para pagar depois ou ser "
                    "variação cambial e monetária sem desembolso. Descolar é o "
                    "normal — a mediana brasileira descola 8,2 p.p. —, mas esta "
                    "companhia está no quartil que mais descola."
                ),
                acao=(
                    "Para o Kd do WACC, o custo contratado importa mais que o pago no "
                    "ano; para o fluxo do acionista, o pago."
                ),
                referencia="",
            )
        )

    roic_hist = analise.mediana("ROIC")
    roic_perp = resultado.empresa.perpetuidade.roic_perpetuidade
    if roic_perp is not None and np.isfinite(roic_hist) and roic_perp > roic_hist + 0.05:
        achados.append(
            Achado(
                codigo="roic_perpetuo_acima_do_historico",
                severidade=ALERTA,
                titulo=(
                    f"ROIC de perpetuidade ({_pct(roic_perp, 1)}) acima do histórico "
                    f"({_pct(roic_hist, 1)})"
                ),
                detalhe=(
                    "A perpetuidade assume um retorno sobre o capital melhor do que a "
                    "empresa costuma entregar, e para sempre."
                ),
                acao="Ancore o ROIC perpétuo no histórico, salvo mudanca estrutural clara.",
                referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
            )
        )

    alavancagem = analise.ultimo("Divida liquida / EBITDA")
    if np.isfinite(alavancagem) and alavancagem > DIVIDA_EBITDA_ALTA:
        achados.append(
            Achado(
                codigo="alavancagem_historica_alta",
                severidade=INFORMACAO,
                titulo=f"Dívida líquida / EBITDA de {_num(alavancagem, 1)}x no ultimo ano",
                detalhe=(
                    "Alavancagem nesse patamar costuma vir acompanhada de covenants e de "
                    "custo de dívida mais alto do que o de uma empresa media do setor."
                ),
                acao="Confira se o spread de crédito usado reflete esse nivel de risco.",
                referencia="CFA Institute, Corporate Finance",
            )
        )

    return achados


def _checar_arrendamento_projetado(
    resultado: ResultadoValuation, analise: AnaliseHistorica
) -> list[Achado]:
    """A empresa cresce assinando aluguel, e a projecao nao cobra por isso.

    Nao e o mesmo achado que ``divida_e_muito_arrendamento``, que fala do
    **estoque**. Este fala do **fluxo**: contrato novo cria passivo sem passar
    pelo capex, entao a projecao de uma rede que abre lojas mostra EBITDA
    subindo, capex parado e FCFF generoso, enquanto a divida cresce todo ano.
    A ponte, congelada na data-base, nunca ve isso -- e o erro cresce com o
    horizonte, porque cada ano projetado acrescenta passivo que ninguem desconta.
    """
    from .casos_especiais import ler_leasing

    leasing = ler_leasing(analise)
    if not leasing.relevante or not leasing.acompanha_a_receita:
        return []

    operacionais = resultado.empresa.operacionais
    if operacionais is None:
        return []
    crescimento = float(np.median(operacionais.crescimento_receita))
    if not np.isfinite(crescimento) or crescimento <= 0:
        return []

    adicao = leasing.adicao_anual_implicita(crescimento)
    horizonte = operacionais.horizonte
    return [
        Achado(
            codigo="arrendamento_cresce_e_nao_e_projetado",
            severidade=ALERTA,
            titulo=(
                f"{_pct(leasing.peso, 0)} da dívida é arrendamento, e ele cresce "
                f"{_pct(leasing.crescimento_anual, 0)} ao ano"
            ),
            detalhe=(
                f"O passivo de arrendamento acompanhou o negócio no histórico "
                f"({_pct(leasing.crescimento_anual, 0)} ao ano contra "
                f"{_pct(leasing.crescimento_receita, 0)} da receita), mas a projeção "
                "não o faz crescer: contrato novo de aluguel não passa pelo capex. "
                f"Projetando {_pct(crescimento, 0)} de crescimento, o passivo subiria "
                f"cerca de {_num(adicao, 0)} por ano — e ao longo dos {horizonte} anos "
                "isso é dívida que o modelo assume, entrega ao acionista e nunca "
                "subtrai, porque a ponte está congelada na data-base."
            ),
            acao=(
                "Some ao item de dívida bruta da ponte o valor presente dos "
                "arrendamentos que a projeção implica, ou reduza o crescimento para "
                "o que a empresa consegue sustentar sem abrir pontos novos."
            ),
            referencia="Damodaran, Investment Valuation, cap. 3 (lease adjustments)",
        )
    ]


# A adicao perpetua de arrendamento acima disto deixa de ser detalhe do fluxo
# terminal e passa a ser premissa de valor. Medido: a Raia Drogasil consome 13,1%
# do FCFF terminal com adicao de arrendamento, e o Grupo SBF, 39,2%.
ADICAO_PERPETUA_RELEVANTE = 0.10


# Folga do ROIC perpetuo sobre o WACC a partir da qual a hipotese deixa de ser
# detalhe e passa a ser a afirmacao central do modelo. Faixa de leitura: o que
# importa nao e o corte, e o **preco** da hipotese, que o achado calcula.
FOSSO_PERPETUO_RELEVANTE = 0.02


def _checar_fosso_perpetuo(
    resultado: ResultadoValuation, analise: AnaliseHistorica | None
) -> list[Achado]:
    """ROIC perpetuo acima do WACC e dizer que o fosso nunca erode.

    **A tela de Qualitativo pergunta "por quanto tempo o retorno excedente
    resiste?", e o modelo ja respondeu: para sempre.** Ela so nao dizia isso, e
    o analista respondia a pergunta qualitativa sem ver que a premissa dele ja
    tinha uma resposta embutida -- e uma resposta forte.

    O achado converte a hipotese em preco, do jeito que o DCF reverso faz:
    recalcula o valor terminal com ``ROIC = WACC`` -- o mundo em que a vantagem
    se dissipa e a empresa passa a apenas remunerar o capital -- e mostra quanto
    do equity depende da diferenca. Nao diz que a hipotese esta errada: diz
    quanto ela vale, que e o que permite defende-la ou baixa-la.

    Quando ha historico, confronta com o que a companhia **de fato** entregou:
    supor excedente perpetuo tendo batido o WACC em 2 de 6 anos e uma afirmacao
    sobre mudanca, e ela precisa de motivo.
    """
    perpetuidade = resultado.empresa.perpetuidade
    if perpetuidade.metodo != "gordon":
        return []
    roic_perp = perpetuidade.roic_perpetuidade
    if roic_perp is None:
        return []

    dcf = resultado.dcf
    wacc = dcf.taxa_desconto
    folga = roic_perp - wacc
    if not np.isfinite(folga) or folga < FOSSO_PERPETUO_RELEVANTE:
        return []

    projecao = resultado.projecao
    try:
        vt_sem_fosso = valor_terminal_gordon(
            fluxo_final=float(dcf.fluxos[-1]),
            taxa=wacc,
            crescimento=perpetuidade.crescimento_perpetuo,
            base_normalizada=float(projecao.nopat[-1]),
            retorno=wacc,
        )
    except ValueError:  # inclui CombinacaoInviavel
        return []

    fator = 1 / (1 + wacc) ** projecao.horizonte
    perda = dcf.valor_presente_terminal - vt_sem_fosso * fator
    if not resultado.equity_value:
        return []
    peso = perda / abs(resultado.equity_value)

    historico = ""
    if analise is not None:
        roics = analise.linha("ROIC").replace([np.inf, -np.inf], np.nan).dropna()
        if not roics.empty:
            acima = int((roics > wacc).sum())
            historico = (
                f" No período importado a empresa superou o WACC em **{acima} de "
                f"{len(roics)}** exercícios"
                + (
                    ", o que sustenta a hipótese — mas sustentar o passado não é "
                    "o mesmo que projetá-lo para sempre."
                    if acima == len(roics)
                    else ", então supor excedente perpétuo é uma afirmação sobre "
                    "mudança, e ela precisa de motivo."
                )
            )

    return [
        Achado(
            codigo="fosso_perpetuo",
            severidade=INFORMACAO,
            titulo=(
                f"O modelo supõe fosso permanente: ROIC perpétuo de "
                f"{_pct(roic_perp, 1)} contra WACC de {_pct(wacc, 1)}"
            ),
            detalhe=(
                f"Um ROIC perpétuo {_pct(folga, 1)} acima do custo de capital diz "
                "que a vantagem competitiva **nunca erode** — nem por entrante, "
                "nem por substituto, nem por regulação. É a hipótese mais forte "
                f"do modelo, e ela vale **{_pct(peso, 1)} do equity value**: é "
                "quanto o valor cairia se o retorno convergisse ao custo de "
                "capital, que é o que a teoria de competição prevê no longo "
                f"prazo.{historico}"
            ),
            acao=(
                "Responda em **Qualitativo** de onde vem o retorno excedente e o "
                "que impede a cópia — se a resposta não convencer você, baixe o "
                "ROIC de perpetuidade em direção ao WACC e veja o valor que sobra."
            ),
            referencia="Damodaran, Investment Valuation, cap. 12",
        )
    ]


# Peso da equivalencia sobre o EBIT a partir do qual o descasamento entre lucro
# e caixa deixa de ser detalhe. Medido no DFP consolidado de 2024: das 226
# companhias com equivalencia diferente de zero, **56 passam de 10% do EBIT** e
# **20 passam de 50%**.
EQUIVALENCIA_RELEVANTE = 0.10


def _checar_equivalencia_no_ebit(analise: AnaliseHistorica) -> list[Achado]:
    """Equivalencia patrimonial esta no EBIT **por competencia**, e nao e caixa.

    O FCFF projetado sai de ``NOPAT + D&A - capex - giro``, e o NOPAT vem do
    EBIT. Onde a equivalencia pesa, o modelo desconta um lucro que **nao virou
    dinheiro**: o que entra no caixa e o dividendo que a investida distribui, e
    ele costuma ser menor.

    Na Itausa de 2024 a equivalencia e de R$ 15.369,0 mi sobre um EBIT de
    R$ 16.388,0 mi -- o EBIT dela e quase so equivalencia --, e os proventos
    recebidos foram R$ 8.250,0 mi. Descontar o primeiro ao WACC avalia um lucro
    que a companhia nao recebeu.

    **O app avisa e nao corrige**, pela mesma razao de sempre: trocar
    equivalencia por dividendo mudaria o valuation de 56 companhias em silencio,
    e ha caso em que a retencao na investida e reinvestimento legitimo que vale
    o que vale. O que nao pode e a diferenca ficar invisivel.

    Tambem nao se soma o dividendo ao FCFF: ele e a **realizacao em caixa da
    mesma equivalencia** que ja esta no EBIT, e somar os dois conta o lucro duas
    vezes -- que era a correcao ingenua que este achado existe para evitar.
    """
    demonstracoes = analise.demonstracoes
    ano = demonstracoes.ano_base
    if ano is None:
        return []

    equivalencia = demonstracoes.valor("equivalencia_patrimonial", ano)
    ebit = demonstracoes.valor("ebit", ano)
    if not (np.isfinite(equivalencia) and np.isfinite(ebit)) or not ebit:
        return []
    peso = equivalencia / ebit
    if abs(peso) < EQUIVALENCIA_RELEVANTE:
        return []

    from .investimento import compor_investimento

    composicao = compor_investimento(demonstracoes, ano)
    proventos = composicao.proventos_recebidos if composicao is not None else 0.0
    virou_caixa = (
        f"No mesmo exercício entraram {_num(proventos)} de dividendos e juros "
        "recebidos das investidas — "
        + (
            f"**{_pct(proventos / equivalencia)} do que o resultado reconheceu**."
            if equivalencia
            else "a diferença é o que ficou retido nelas."
        )
        if proventos
        else "**Nenhum dividendo de investida apareceu no caixa deste "
        "exercício** — o resultado das investidas foi reconhecido e ficou lá."
    )

    return [
        Achado(
            codigo="equivalencia_no_ebit",
            severidade=ALERTA if abs(peso) >= 0.50 else INFORMACAO,
            titulo=(
                f"A equivalência patrimonial vale {_pct(peso, 0)} do EBIT — e "
                "ela não é caixa"
            ),
            detalhe=(
                f"O EBIT de {_num(ebit)} inclui {_num(equivalencia)} de resultado "
                "de investidas, reconhecido por **competência**. O FCFF desconta "
                "esse lucro como se fosse caixa da operação, e ele não é: o que "
                f"chega ao caixa é o dividendo que a investida distribui. "
                f"{virou_caixa}"
            ),
            acao=(
                "Se a companhia é uma holding, o caminho é avaliar as investidas "
                "separadamente e somar — um FCFF ao WACC sobre lucro de "
                "equivalência mistura duas entidades. Se são coligadas "
                "acessórias, considere projetar a margem **sem** a equivalência e "
                "tratar a participação como ativo não operacional na ponte. "
                "**Não some o dividendo recebido ao FCFF**: ele é a realização da "
                "mesma equivalência que já está no EBIT."
            ),
            referencia="Damodaran, Investment Valuation, cap. 16 (cross holdings)",
        )
    ]


def _checar_perpetuidade_do_arrendamento(
    resultado: ResultadoValuation,
) -> list[Achado]:
    """O valor terminal supoe que a rede abre loja para sempre, no mesmo ritmo.

    O ``fluxo_final`` que entra no Gordon **ja vem liquido da adicao de
    arrendamento**. Como a adicao e proporcional a receita e a receita cresce a
    ``g``, a hipotese embutida e que a razao arrendamento/receita fica constante
    ate o infinito. E internamente consistente -- quem cresce mantendo
    intensidade de aluguel precisa mesmo de contrato novo -- e por isso e o
    padrao. Mas nao e neutra, e ninguem a escolheu.

    A leitura alternativa e a rede parar de crescer em area no fim do horizonte
    explicito. Medido, a distancia entre as duas nao e pequena:

        Lojas Renner    adicao 8,1% do FCFF terminal   equity +6,9%
        Raia Drogasil          13,1%                          +13,9%
        Pague Menos            21,5%                          +27,9%
        Grupo SBF              39,2%                          +96,7%

    O achado nao diz qual esta certa. Diz quanto custa a que esta montada, que e
    o que o analista precisa para escolher.
    """
    projecao = resultado.projecao
    variacao = getattr(projecao, "variacao_arrendamento", None)
    if variacao is None or not len(variacao):
        return []

    adicao = float(variacao[-1])
    fcff_final = float(projecao.fcff[-1])
    if not (np.isfinite(adicao) and np.isfinite(fcff_final)) or fcff_final <= 0:
        return []
    peso = adicao / fcff_final
    if peso < ADICAO_PERPETUA_RELEVANTE:
        return []

    # Quanto o valor terminal subiria se a adicao parasse no fim do horizonte.
    dcf = resultado.dcf
    fator = 1 / (1 + dcf.taxa_desconto) ** projecao.horizonte
    perpetuidade = resultado.empresa.perpetuidade
    if perpetuidade.metodo != "gordon":
        return []
    try:
        vt_sem = valor_terminal_gordon(
            fluxo_final=fcff_final + adicao,
            taxa=dcf.taxa_desconto,
            crescimento=perpetuidade.crescimento_perpetuo,
            base_normalizada=float(projecao.nopat[-1]),
            retorno=perpetuidade.roic_perpetuidade,
        )
    except ValueError:  # inclui CombinacaoInviavel
        return []
    folga = (vt_sem * fator - dcf.valor_presente_terminal)
    if resultado.equity_value:
        folga_relativa = folga / abs(resultado.equity_value)
    else:
        return []

    return [
        Achado(
            codigo="arrendamento_cresce_para_sempre",
            severidade=INFORMACAO,
            titulo=(
                f"O valor terminal supõe abertura de pontos para sempre "
                f"({_pct(peso, 0)} do FCFF final vai em contrato novo)"
            ),
            detalhe=(
                "O fluxo que entra na perpetuidade já está líquido da adição de "
                "arrendamento. Como a adição acompanha a receita e a receita cresce "
                f"a {_pct(perpetuidade.crescimento_perpetuo, 1)}, isso supõe que a "
                "razão arrendamento/receita fica constante **para sempre** — a rede "
                "continua abrindo ponto no mesmo ritmo, eternamente. É consistente, "
                "e é o padrão por isso. Mas se a rede parasse de crescer em área no "
                f"fim do horizonte, o equity seria {_pct(folga_relativa, 1)} maior."
            ),
            acao=(
                "Decida qual das duas descreve o negócio. Rede madura que só repõe "
                "contrato vencido está mais perto da segunda; rede em expansão, da "
                "primeira. O modelo não escolhe sozinho."
            ),
            referencia="Damodaran, Investment Valuation, cap. 3 (lease adjustments)",
        )
    ]


# A partir daqui o que nao se repete deixa de ser detalhe e passa a definir o
# EBIT do periodo.
#
# O numero que estava aqui -- "47% das companhias com item nao recorrente" --
# media outra coisa: so as companhias que tinham item, e num ano so. Medido em
# ``ResultadoRecorrente.peso``, que e a grandeza que este corte de fato olha
# (mediana do **modulo** de nao recorrente sobre EBIT, 2020-2024, n=467):
#
#   P25 0,032   P50 0,099   P75 0,266   P90 0,723
#   0,20 acusa 31,9% da base; 0,25, o quartil, acusaria 27,2%
#
# Fica em 0,20 e nao no quartil de proposito: "um quinto do EBIT" e um limiar com
# significado proprio, e a diferenca para o P75 e pequena. O que nao podia ficar
# era o numero errado no comentario, dando a impressao de calibracao que nao houve.
NAO_RECORRENTE_RELEVANTE = 0.20


def _checar_itens_nao_recorrentes(
    resultado: ResultadoValuation, analise: AnaliseHistorica
) -> list[Achado]:
    """Reversao de impairment, venda de ativo, ganho tributario ou judicial.

    Todos entram na DRE **do SG&A para baixo** e podem fazer EBIT, LAIR e lucro
    liquido superarem o lucro bruto. Nada disso e erro contabil -- e nada disso
    se repete. Projetar margem a partir de um ano assim e projetar o evento.
    """
    from .casos_especiais import ver_recorrente

    recorrente = ver_recorrente(analise)
    if recorrente is None or not np.isfinite(recorrente.peso):
        return []

    achados: list[Achado] = []
    anos_estranhos = recorrente.anos_com_lucro_acima_do_bruto()
    if anos_estranhos:
        equivalencia = recorrente.equivalencia.dropna()
        pela_equivalencia = (
            not equivalencia.empty and abs(float(equivalencia.iloc[-1])) > 0
        )
        causa = (
            "equivalência patrimonial — a companhia vive do resultado de "
            "coligadas, e não da própria operação"
            if pela_equivalencia
            else "itens não recorrentes lançados do SG&A para baixo"
        )
        achados.append(
            Achado(
                codigo="lucro_acima_do_lucro_bruto",
                severidade=INFORMACAO,
                titulo=(
                    f"Lucro líquido superou o lucro bruto em "
                    f"{', '.join(str(a) for a in anos_estranhos)}"
                ),
                detalhe=(
                    "Contabilmente é possível e não indica erro: reversão de "
                    "impairment, venda de ativo, ganho tributário ou judicial "
                    "entram abaixo do lucro bruto e podem superá-lo. Aqui a causa "
                    f"aparenta ser {causa}."
                ),
                acao=(
                    "Confira a margem EBIT recorrente antes de projetar: o resultado "
                    "desse ano não veio da operação e não se repete."
                ),
                referencia="",
            )
        )

    if recorrente.peso >= NAO_RECORRENTE_RELEVANTE:
        margem = recorrente.margem_ebit.dropna()
        margem_rec = recorrente.margem_ebit_recorrente.dropna()
        if not margem.empty and not margem_rec.empty:
            achados.append(
                Achado(
                    codigo="ebit_depende_de_nao_recorrente",
                    severidade=ALERTA,
                    titulo=(
                        f"{_pct(recorrente.peso, 0)} do EBIT vem de itens que não "
                        "se repetem"
                    ),
                    detalhe=(
                        f"Impairment, outras receitas e outras despesas operacionais "
                        f"respondem por {_pct(recorrente.peso, 0)} do EBIT na mediana "
                        f"do período. A margem EBIT reportada é "
                        f"{_pct(float(margem.iloc[-1]))} e a recorrente, "
                        f"{_pct(float(margem_rec.iloc[-1]))}."
                    ),
                    acao=(
                        "Ancore a projeção na margem recorrente. A reportada embute "
                        "um evento que não volta no ano seguinte — e quando o item "
                        "foi uma perda, a recorrente é **maior**, não menor."
                    ),
                    referencia="CFA Institute, Financial Statement Analysis",
                )
            )
    return achados


# ---------------------------------------------------------------------------
# Capex muito acima da depreciacao entrando na perpetuidade
# ---------------------------------------------------------------------------

# **O inverso ja existia e este nao.** `capex_abaixo_da_depreciacao` acusa a base
# de ativos que encolhe enquanto a receita cresce; faltava o outro lado -- a
# empresa que entra na perpetuidade investindo muitas vezes o que deprecia, o que
# afirma expansao pesada **para sempre**.
#
# A lacuna apareceu ao medir a correcao do capex de imovel de renda. Com
# "propriedades para investimento" dentro da conta, a premissa da Multiplan foi
# de 1,5% para 28,2% da receita, e o equity caiu **59,8%** -- a leitura ficou
# certa (o dinheiro saiu mesmo) e a projecao passou a supor que ela constroi
# shopping no mesmo ritmo, eternamente. Medido junto: Allos -26,2%, BR Malls
# -33,7%, WEG (controle, sem imovel) 0,0%.
#
# O corte e o **P90** da base, medido na safra 2021-2025 (n=389):
#
#   P25 0,56x   mediana 0,99x   P75 1,75x   P90 3,15x   P95 5,42x
#
# A mediana em 1,0x e o estado estacionario -- repor o que se gasta. Acima de 3x
# estao 10,5% das companhias, que e a raridade que um sinal deve ter para dirigir
# atencao. Na Multiplan o capex projetado e 2,97x a depreciacao; no MRV, 5,83x.
CAPEX_MUITO_ACIMA_DA_DEPRECIACAO = 3.0


def _checar_capex_perpetuo(resultado: ResultadoValuation) -> list[Achado]:
    """A perpetuidade supoe expansao pesada para sempre? E quanto isso custa.

    Nao diz qual hipotese esta certa -- empresa em ciclo de expansao **de fato**
    investe multiplos da depreciacao, e a projecao a partir da mediana historica
    e defensavel. Diz quanto vale a que esta montada, que e o que o analista
    precisa para escolher.
    """
    projecao = resultado.projecao
    capex = float(projecao.capex[-1])
    deprec = float(projecao.depreciacao[-1])
    if not (np.isfinite(capex) and np.isfinite(deprec)) or deprec <= 0:
        return []

    razao = capex / deprec
    if razao < CAPEX_MUITO_ACIMA_DA_DEPRECIACAO:
        return []

    perpetuidade = resultado.empresa.perpetuidade
    if perpetuidade.metodo != "gordon":
        return []

    # Quanto o valor subiria se a expansao parasse no fim do horizonte explicito
    # -- capex convergindo para a depreciacao, que e o estado estacionario.
    dcf = resultado.dcf
    fcff_final = float(projecao.fcff[-1])
    fator = 1 / (1 + dcf.taxa_desconto) ** projecao.horizonte
    try:
        vt_sem = valor_terminal_gordon(
            fluxo_final=fcff_final + (capex - deprec),
            taxa=dcf.taxa_desconto,
            crescimento=perpetuidade.crescimento_perpetuo,
            base_normalizada=float(projecao.nopat[-1]),
            retorno=perpetuidade.roic_perpetuidade,
        )
    except ValueError:  # inclui CombinacaoInviavel
        return []

    folga = vt_sem * fator - dcf.valor_presente_terminal
    if not resultado.equity_value:
        return []
    folga_relativa = folga / abs(resultado.equity_value)

    return [
        Achado(
            codigo="capex_perpetuo_acima_da_depreciacao",
            severidade=INFORMACAO,
            titulo=(
                f"O valor terminal supõe expansão para sempre "
                f"(capex de {_num(razao, 2)}x a depreciação)"
            ),
            detalhe=(
                f"No último ano projetado o capex é {_num(razao, 2)}x a depreciação, e "
                "o fluxo que entra na perpetuidade já está líquido dessa diferença. "
                "Isso supõe que a companhia continua expandindo a base de ativos no "
                "mesmo ritmo, **eternamente** — e não apenas repondo o que gasta. "
                f"Se a expansão parasse no fim do horizonte, o equity seria "
                f"{_pct(folga_relativa, 1)} maior. Na base brasileira a mediana é "
                "1,0x, ou seja, repor o que se deprecia; acima de 3x estão 10% das "
                "companhias."
            ),
            acao=(
                "Decida se a companhia está num ciclo de expansão que termina ou num "
                "regime permanente. Empresa de imóvel de renda e incorporadora ficam "
                "na primeira com frequência: o capex delas constrói ativo novo, e "
                "projetar a mediana histórica como perpétua cobra a construção sem "
                "creditar a receita que ela geraria."
            ),
            referencia="Koller, Goedhart & Wessels, Valuation, cap. 10",
        )
    ]
