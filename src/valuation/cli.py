"""Interface de linha de comando.

    valuation dcf premissas.yaml --excel modelo.xlsx
    valuation wacc premissas.yaml
    valuation multiplos comparaveis.yaml
    valuation exemplo --destino exemplos/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import formato
from .custo_capital import calcular_custo_capital
from .entrada import ArquivoModelo, carregar_comparaveis, carregar_modelo
from .excel import exportar_excel
from .modelo import avaliar
from .multiplos import avaliar_por_multiplos, estatisticas, tabela_comparaveis
from .sensibilidade import cenarios as rodar_cenarios
from .sensibilidade import monte_carlo, tabela_sensibilidade

LARGURA = 78


def _titulo(texto: str) -> None:
    print(f"\n{texto}")
    print("=" * min(len(texto), LARGURA))


def _tabela(df: pd.DataFrame, formato: str = "{:,.1f}") -> None:
    with pd.option_context(
        "display.max_columns", None,
        "display.width", 200,
        "display.float_format", formato.format,
    ):
        print(df.to_string())


def _pct(valor: float) -> str:
    """Percentual no padrao brasileiro -- e ele **nao era**.

    A CLI usava `f"{valor:.2%}"`, que produz "12.34%" com ponto decimal:
    formatacao inglesa numa ferramenta em portugues, e discordando do relatorio
    e do app, que dizem "12,34%" do mesmo numero. Nenhum teste pegava, porque
    cada modulo tinha a propria copia do formatador e testava a sua.
    """
    return formato.pct(valor, casas=2, ausente="n/a")


def _dinheiro(valor: float | None, unidade: str) -> str:
    if valor is None or not np.isfinite(valor):
        return "n/a"
    return f"{valor:,.1f} {unidade}"


def _eixos_padrao(modelo: ArquivoModelo, wacc_base: float) -> tuple[tuple, tuple]:
    """Eixos de sensibilidade em torno do caso base, quando o arquivo nao define.

    WACC e crescimento perpetuo em passos de 0,5 p.p. -- a granularidade usual
    de uma tabela que vai para o comite.
    """
    g_base = modelo.empresa.perpetuidade.crescimento_perpetuo
    waccs = [round(wacc_base + d, 6) for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    gs = [round(g_base + d, 6) for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    return ("wacc", waccs), ("perpetuidade.crescimento_perpetuo", gs)


def _montar_sensibilidade(
    modelo: ArquivoModelo, wacc_base: float, **kwargs
) -> pd.DataFrame:
    if modelo.sensibilidade:
        linhas = modelo.sensibilidade["linhas"]
        colunas = modelo.sensibilidade["colunas"]
        eixo_l = (linhas["caminho"], [float(v) for v in linhas["valores"]])
        eixo_c = (colunas["caminho"], [float(v) for v in colunas["valores"]])
        metrica = modelo.sensibilidade.get("metrica", "equity_value")
    else:
        eixo_l, eixo_c = _eixos_padrao(modelo, wacc_base)
        metrica = "equity_value"
    return tabela_sensibilidade(
        modelo.empresa, eixo_l, eixo_c, metrica=metrica, **kwargs
    )


def comando_dcf(args: argparse.Namespace) -> int:
    modelo = carregar_modelo(args.arquivo)
    empresa = modelo.empresa
    # As analises derivadas precisam rodar sob exatamente as mesmas convencoes do
    # caso base, senao o cenario "Base" nao reproduz o numero principal.
    convencoes = {"meio_de_ano": args.meio_de_ano, "tipo_fluxo": args.fluxo}
    resultado = avaliar(empresa, **convencoes)
    unidade = empresa.unidade

    _titulo(f"{empresa.nome} - Fluxo de caixa descontado")
    if empresa.data_base:
        print(f"Data-base: {empresa.data_base}")
    print(f"Convencao de desconto: {'meio de ano' if args.meio_de_ano else 'fim de ano'}")

    _titulo("Custo de capital")
    for rotulo, valor in resultado.custo_capital.resumo().items():
        formato = f"{valor:.3f}" if "Beta" in rotulo else _pct(valor)
        print(f"  {rotulo:.<40} {formato}")

    _titulo("Projecao")
    _tabela(resultado.projecao.tabela())

    _titulo("Fluxos descontados")
    _tabela(resultado.dcf.tabela_fluxos(), "{:,.3f}")

    _titulo("Resultado")
    dcf = resultado.dcf
    print(f"  VP dos fluxos explicitos.......... {_dinheiro(dcf.valor_presente_explicito, unidade)}")
    print(f"  Valor terminal (fim do ano n)..... {_dinheiro(dcf.valor_terminal, unidade)}")
    print(f"  VP do valor terminal.............. {_dinheiro(dcf.valor_presente_terminal, unidade)}")
    print(f"  Enterprise Value.................. {_dinheiro(dcf.enterprise_value, unidade)}")
    print(f"  (-) Dívida líquida................ {_dinheiro(-empresa.ponte.divida_liquida, unidade)}")
    print(f"  Equity Value...................... {_dinheiro(dcf.equity_value, unidade)}")
    if dcf.valor_por_acao is not None:
        print(f"  Valor por ação.................... {dcf.valor_por_acao:,.2f}")
    print(f"  % do EV vindo da perpetuidade..... {_pct(dcf.peso_perpetuidade)}")
    if dcf.peso_perpetuidade > 0.75:
        print(
            "  [atencao] mais de 75% do valor vem da perpetuidade; considere\n"
            "            alongar a projecao explicita antes de defender o numero."
        )

    tabela_sens = None
    if args.sensibilidade or modelo.sensibilidade:
        tabela_sens = _montar_sensibilidade(
            modelo, resultado.custo_capital.wacc_brl, **convencoes
        )
        _titulo(f"Sensibilidade ({tabela_sens.index.name} x {tabela_sens.columns.name})")
        _tabela(tabela_sens)

    tabela_cen = None
    if modelo.cenarios:
        tabela_cen = rodar_cenarios(empresa, modelo.cenarios, **convencoes)
        _titulo("Cenarios")
        _tabela(tabela_cen)

    simulacao = None
    if args.monte_carlo or modelo.distribuicoes:
        if not modelo.distribuicoes:
            print(
                "\n[aviso] --monte-carlo pedido, mas o arquivo nao declara o bloco "
                "'simulacao'. Sem distribuicoes nao ha o que simular."
            )
        else:
            simulacao = monte_carlo(
                empresa,
                modelo.distribuicoes,
                simulacoes=modelo.simulacoes,
                metrica=modelo.metrica_simulacao,
                **convencoes,
            )
            _titulo(f"Monte Carlo ({simulacao.simulacoes:,} rodadas)")
            for rotulo, valor in simulacao.resumo().items():
                print(f"  {rotulo:.<32} {valor:,.1f}")
            if simulacao.descartadas:
                print(
                    f"  {simulacao.descartadas:,} rodadas descartadas por combinacao "
                    "de premissas inviavel."
                )

    comparaveis = alvo = None
    if args.comparaveis:
        alvo, comparaveis = carregar_comparaveis(args.comparaveis)
        _titulo("Avaliacao relativa")
        _tabela(avaliar_por_multiplos(alvo, comparaveis), "{:,.2f}")

    if args.excel:
        destino = exportar_excel(
            resultado,
            args.excel,
            sensibilidade=tabela_sens,
            comparaveis=comparaveis,
            alvo=alvo,
            simulacao=simulacao,
            cenarios=tabela_cen,
        )
        print(f"\nPlanilha gravada em: {destino}")

    return 0


def comando_wacc(args: argparse.Namespace) -> int:
    modelo = carregar_modelo(args.arquivo)
    empresa = modelo.empresa
    resultado = calcular_custo_capital(empresa.custo_capital, empresa.macro)

    _titulo(f"{empresa.nome} - Custo de capital")
    for rotulo, valor in resultado.resumo().items():
        formato = f"{valor:.3f}" if "Beta" in rotulo else _pct(valor)
        print(f"  {rotulo:.<40} {formato}")
    print(
        "\nO Ke e montado em USD nominal (rf + beta x ERP + risco-pais) e convertido\n"
        "para BRL pelo diferencial de inflacao de longo prazo."
    )
    return 0


def comando_multiplos(args: argparse.Namespace) -> int:
    alvo, comparaveis = carregar_comparaveis(args.arquivo)

    _titulo("Multiplos dos comparaveis")
    _tabela(tabela_comparaveis(comparaveis), "{:,.2f}")

    _titulo("Estatisticas do peer group")
    _tabela(estatisticas(comparaveis), "{:,.2f}")

    _titulo(f"Valor implicito de {alvo.nome} ({args.referencia} do setor)")
    _tabela(avaliar_por_multiplos(alvo, comparaveis, args.referencia), "{:,.2f}")
    print(
        "\nn/a indica multiplo sem significado economico (denominador nao positivo),\n"
        "excluido tambem das estatisticas."
    )
    return 0


def comando_exemplo(args: argparse.Namespace) -> int:
    from . import exemplos

    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)
    escritos = exemplos.escrever_exemplos(destino)
    print("Arquivos de exemplo criados:")
    for caminho in escritos:
        print(f"  {caminho}")
    print(f"\nExperimente:\n  valuation dcf {escritos[0]} --excel modelo.xlsx")
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valuation",
        description="Valuation de empresas: FCD, multiplos, WACC e sensibilidade.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_dcf = sub.add_parser("dcf", help="roda o fluxo de caixa descontado")
    p_dcf.add_argument("arquivo", help="arquivo YAML/JSON de premissas")
    p_dcf.add_argument("--excel", help="caminho da planilha a gerar")
    p_dcf.add_argument(
        "--meio-de-ano", action="store_true", help="desconta os fluxos em t - 0,5"
    )
    p_dcf.add_argument(
        "--fluxo", choices=("fcff", "fcfe"), default="fcff", help="tipo de fluxo"
    )
    p_dcf.add_argument(
        "--sensibilidade",
        action="store_true",
        help="tabela WACC x crescimento perpetuo em torno do caso base",
    )
    p_dcf.add_argument(
        "--monte-carlo",
        action="store_true",
        help="roda a simulacao declarada no bloco 'simulacao' do arquivo",
    )
    p_dcf.add_argument("--comparaveis", help="arquivo de comparaveis para cotejo")
    p_dcf.set_defaults(func=comando_dcf)

    p_wacc = sub.add_parser("wacc", help="mostra a montagem do custo de capital")
    p_wacc.add_argument("arquivo", help="arquivo YAML/JSON de premissas")
    p_wacc.set_defaults(func=comando_wacc)

    p_mult = sub.add_parser("multiplos", help="avaliacao relativa por comparaveis")
    p_mult.add_argument("arquivo", help="arquivo YAML/JSON com alvo e comparaveis")
    p_mult.add_argument(
        "--referencia",
        default="Mediana",
        choices=("Mediana", "Media", "1o quartil", "3o quartil"),
        help="estatistica do peer group aplicada ao alvo",
    )
    p_mult.set_defaults(func=comando_multiplos)

    p_ex = sub.add_parser("exemplo", help="gera arquivos de premissas de exemplo")
    p_ex.add_argument("--destino", default="exemplos", help="pasta de destino")
    p_ex.set_defaults(func=comando_exemplo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as erro:
        print(f"\nErro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
