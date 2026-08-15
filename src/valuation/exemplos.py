"""Arquivos de premissas de exemplo, gerados por ``valuation exemplo``.

Servem como ponto de partida e como documentacao viva do formato: todo campo
aceito aparece em algum dos dois arquivos.
"""

from __future__ import annotations

from pathlib import Path

EMPRESA_YAML = """\
# Modelo de premissas de valuation.
# Todas as taxas sao decimais: 0.12 = 12% a.a.
# Valores monetarios em R$ milhoes, coerentes entre si.

nome: Industrias Exemplo S.A.
data_base: 2025-12-31
moeda: BRL
unidade: R$ milhoes

macro:
  inflacao_brl: 0.04        # IPCA de longo prazo
  inflacao_usd: 0.023       # inflacao americana de longo prazo
  aliquota_ir: 0.34         # IRPJ 25% + CSLL 9%

custo_capital:
  rf_usd: 0.045             # T-Bond 10 anos
  erp_maduro: 0.045         # premio de risco do mercado americano
  risco_pais: 0.025         # premio de risco-pais Brasil (EMBI+ / CDS)
  lambda_pais: 1.0          # exposicao da empresa ao risco-pais
  premio_tamanho: 0.0       # premio adicional para empresas menores
  beta_alavancado_setor: 1.05
  divida_pl_setor: 0.45     # D/E medio dos comparaveis, para desalavancar
  divida_pl_alvo: 0.50      # D/E alvo da empresa, para realavancar e ponderar
  spread_credito: 0.025     # usado se custo_divida_brl nao for informado
  # custo_divida_brl: 0.135 # descomente para informar o Kd direto em BRL

operacionais:
  receita_base: 1200.0      # receita liquida do ano base (ano 0)
  horizonte: 5              # permite escrever premissas anuais como numero unico
  crescimento_receita:   [0.12, 0.10, 0.08, 0.06, 0.05]
  margem_ebitda:         [0.180, 0.185, 0.190, 0.190, 0.190]
  depreciacao_pct_receita: 0.045
  capex_pct_receita:     [0.060, 0.055, 0.050, 0.050, 0.047]
  capital_giro_pct_receita: 0.12   # saldo, nao variacao

perpetuidade:
  metodo: gordon            # 'gordon' ou 'multiplo'
  crescimento_perpetuo: 0.045   # nao deve superar a inflacao + crescimento real do PIB
  roic_perpetuidade: 0.15   # normaliza o reinvestimento; remova para Gordon simples
  # multiplo_saida: 7.0     # usado quando metodo = multiplo

ponte:
  divida_bruta: 900.0
  caixa: 250.0
  aplicacoes_financeiras: 0.0
  minoritarios: 30.0
  contingencias: 60.0
  deficit_atuarial: 0.0
  ativos_nao_operacionais: 0.0
  acoes_em_circulacao: 150.0     # em milhoes, coerente com a unidade

# --- Analises que acompanham o valuation (todos os blocos sao opcionais) ---

sensibilidade:
  metrica: equity_value
  linhas:
    caminho: wacc           # 'wacc' e especial: forca a taxa de desconto
    valores: [0.105, 0.110, 0.115, 0.120, 0.125]
  colunas:
    caminho: perpetuidade.crescimento_perpetuo
    valores: [0.035, 0.040, 0.045, 0.050, 0.055]

cenarios:
  Pessimista:
    operacionais.margem_ebitda: 0.16
    perpetuidade.crescimento_perpetuo: 0.035
  Base: {}
  Otimista:
    operacionais.margem_ebitda: 0.21
    perpetuidade.crescimento_perpetuo: 0.050

simulacao:
  simulacoes: 5000
  metrica: equity_value
  distribuicoes:
    - caminho: wacc
      tipo: triangular
      parametros: {minimo: 0.100, moda: 0.115, maximo: 0.135}
    - caminho: perpetuidade.crescimento_perpetuo
      tipo: triangular
      parametros: {minimo: 0.030, moda: 0.045, maximo: 0.055}
    - caminho: operacionais.margem_ebitda
      tipo: normal
      parametros: {media: 0.185, desvio: 0.015}
      limite_inferior: 0.10
      limite_superior: 0.28
"""

COMPARAVEIS_YAML = """\
# Peer group para avaliacao relativa.
# Valores em R$ milhoes, dos ultimos 12 meses.
# valor_mercado = capitalizacao de mercado do equity
# divida_liquida = divida bruta - caixa (pode ser negativa)

alvo:
  nome: Industrias Exemplo S.A.
  receita: 1200.0
  ebitda: 216.0
  ebit: 162.0
  lucro_liquido: 78.0
  patrimonio_liquido: 620.0
  divida_liquida: 650.0
  acoes_em_circulacao: 150.0

comparaveis:
  - nome: Comparavel Alfa
    valor_mercado: 2400.0
    divida_liquida: 900.0
    receita: 1850.0
    ebitda: 351.0
    ebit: 259.0
    lucro_liquido: 145.0
    patrimonio_liquido: 1100.0

  - nome: Comparavel Beta
    valor_mercado: 1750.0
    divida_liquida: 420.0
    receita: 1320.0
    ebitda: 224.0
    ebit: 158.0
    lucro_liquido: 96.0
    patrimonio_liquido: 780.0

  - nome: Comparavel Gama
    valor_mercado: 3900.0
    divida_liquida: -150.0
    receita: 2600.0
    ebitda: 546.0
    ebit: 425.0
    lucro_liquido: 288.0
    patrimonio_liquido: 1950.0

  - nome: Comparavel Delta
    valor_mercado: 980.0
    divida_liquida: 610.0
    receita: 1100.0
    ebitda: 154.0
    ebit: 88.0
    lucro_liquido: 21.0
    patrimonio_liquido: 430.0

  # Prejuizo no exercicio: P/L sai como n/a e nao entra nas estatisticas,
  # mas os multiplos de EV continuam validos.
  - nome: Comparavel Epsilon
    valor_mercado: 1400.0
    divida_liquida: 880.0
    receita: 1600.0
    ebitda: 192.0
    ebit: 96.0
    lucro_liquido: -35.0
    patrimonio_liquido: 690.0
"""


def escrever_exemplos(destino: Path) -> list[Path]:
    """Grava os arquivos de exemplo em ``destino`` e devolve os caminhos."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = {
        "empresa_exemplo.yaml": EMPRESA_YAML,
        "comparaveis_exemplo.yaml": COMPARAVEIS_YAML,
    }
    escritos = []
    for nome, conteudo in arquivos.items():
        caminho = destino / nome
        caminho.write_text(conteudo, encoding="utf-8")
        escritos.append(caminho)
    return escritos
