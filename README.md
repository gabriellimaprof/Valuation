# Valuation

Ferramentas de valuation de empresas com foco no mercado brasileiro: fluxo de
caixa descontado, avaliação relativa por múltiplos, montagem de WACC/CAPM com
prêmio de risco-país, análise de sensibilidade, cenários e Monte Carlo — com
exportação para Excel **com fórmulas vivas**.

O modelo de cada empresa é um arquivo YAML versionável. Isso significa que dá
para revisar premissas em pull request, comparar duas versões de um valuation e
reproduzir exatamente o mesmo número meses depois.

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Começando

```bash
valuation exemplo                                    # gera arquivos de exemplo
valuation dcf exemplos/empresa_exemplo.yaml --excel modelo.xlsx
```

Outros comandos:

```bash
valuation wacc exemplos/empresa_exemplo.yaml         # só a montagem do custo de capital
valuation multiplos exemplos/comparaveis_exemplo.yaml
valuation dcf premissas.yaml --meio-de-ano --sensibilidade
valuation dcf premissas.yaml --comparaveis peers.yaml --excel modelo.xlsx
```

Como biblioteca:

```python
from valuation import carregar_empresa, avaliar, exportar_excel

empresa = carregar_empresa("premissas.yaml")
resultado = avaliar(empresa, meio_de_ano=True)

print(resultado.resumo())
print(resultado.projecao.tabela())

exportar_excel(resultado, "modelo.xlsx")
```

## O arquivo de premissas

Todas as taxas são decimais (`0.12` = 12% a.a.) e os valores monetários ficam na
mesma unidade dentro de um modelo. `valuation exemplo` gera um arquivo comentado
com todos os campos aceitos.

```yaml
nome: Industrias Exemplo S.A.
data_base: 2025-12-31
unidade: R$ milhoes

macro:
  inflacao_brl: 0.04
  inflacao_usd: 0.023
  aliquota_ir: 0.34          # IRPJ 25% + CSLL 9%

custo_capital:
  rf_usd: 0.045
  erp_maduro: 0.045
  risco_pais: 0.025
  beta_alavancado_setor: 1.05
  divida_pl_setor: 0.45      # D/E dos comparáveis, para desalavancar
  divida_pl_alvo: 0.50       # D/E alvo, para realavancar e ponderar
  spread_credito: 0.025

operacionais:
  receita_base: 1200.0
  horizonte: 5               # permite escrever premissas anuais como número único
  crescimento_receita:   [0.12, 0.10, 0.08, 0.06, 0.05]
  margem_ebitda:         [0.180, 0.185, 0.190, 0.190, 0.190]
  depreciacao_pct_receita: 0.045
  capex_pct_receita:     [0.060, 0.055, 0.050, 0.050, 0.047]
  capital_giro_pct_receita: 0.12    # saldo, não variação

perpetuidade:
  metodo: gordon
  crescimento_perpetuo: 0.045
  roic_perpetuidade: 0.15    # normaliza o reinvestimento

ponte:
  divida_bruta: 900.0
  caixa: 250.0
  minoritarios: 30.0
  contingencias: 60.0
  acoes_em_circulacao: 150.0
```

Blocos opcionais `sensibilidade`, `cenarios` e `simulacao` deixam a análise
inteira versionada junto com as premissas. Um campo com nome errado gera erro em
vez de ser ignorado em silêncio.

## Decisões de modelagem

Algumas escolhas afetam o número final e vale saber quais são:

**Custo de capital em duas moedas.** O Ke é montado em USD nominal
(`rf_usd + β × ERP_maduro + λ × risco_país`) e convertido para BRL nominal pelo
diferencial de inflação de longo prazo. Somar um prêmio de risco americano
direto a uma NTN-B contaria risco soberano duas vezes.

**Perpetuidade com reinvestimento normalizado.** Com `roic_perpetuidade`
informado, o fluxo perpétuo vira `NOPAT_n × (1+g) × (1 − g/ROIC)`. Crescer para
sempre exige reinvestir para sempre; usar o FCFF do último ano projetado
costuma superestimar o valor terminal quando aquele ano teve capex baixo.

**Capital de giro é estoque.** `capital_giro_pct_receita` descreve o *saldo*
como percentual da receita; a variação que entra no fluxo é derivada dele.

**Imposto sobre o EBIT.** O FCFF é desalavancado por construção, então o imposto
incide sobre o EBIT, não sobre o LAIR. Prejuízo não gera crédito no fluxo.

**Múltiplos de EV e de equity não se misturam.** EV/EBITDA produz Enterprise
Value e passa pela ponte da dívida líquida; P/L já produz equity e não passa.
Denominador não positivo vira `n/a` e sai das estatísticas do peer group.

**Erro de premissa não vira célula vazia.** Uma combinação economicamente
impossível (g acima do WACC) vira `NaN` na tabela e rodada descartada no Monte
Carlo. Já um nome de premissa digitado errado levanta erro — uma tabela inteira
de `NaN` por causa de um typo é pior do que nenhuma tabela, porque parece
resultado.

**Monte Carlo com semente fixa.** Um valuation que muda de número a cada
execução é indefensável em revisão.

## A planilha gerada

As abas **Premissas**, **Custo de Capital**, **Projeção** e **DCF** são escritas
com fórmulas do Excel, não com valores. Quem receber o arquivo altera uma
premissa e o modelo inteiro recalcula; um revisor rastreia cada número até a
origem. Convenção de cores: azul é premissa editável, preto é fórmula da própria
aba, verde é referência a outra aba.

As abas de **Múltiplos**, **Sensibilidade**, **Cenários** e **Monte Carlo**
trazem valores calculados no Python e vêm rotuladas como tal — uma tabela de
sensibilidade viva exigiria replicar o modelo inteiro por célula.

Os testes em `tests/test_excel_formulas.py` avaliam o workbook fora do Excel e
conferem, célula a célula, que as fórmulas reproduzem o motor Python. Uma
planilha bonita que calcula diferente do motor é pior do que planilha nenhuma,
porque o erro só aparece na mão de quem recebeu o arquivo.

## Testes

```bash
pytest
```

A validação das fórmulas do Excel depende do pacote `formulas`
(`pip install formulas`); sem ele esses testes são pulados em vez de dar falso
positivo.

## Estrutura

| Módulo | Responsabilidade |
| --- | --- |
| `premissas.py` | estruturas de entrada e suas validações |
| `custo_capital.py` | beta, CAPM com risco-país, Kd, WACC |
| `projecao.py` | projeção explícita, FCFF e FCFE |
| `dcf.py` | desconto, valor terminal, ponte EV → equity |
| `multiplos.py` | avaliação relativa por comparáveis |
| `sensibilidade.py` | tabelas, cenários e Monte Carlo |
| `modelo.py` | orquestração e substituição de premissas |
| `entrada.py` | leitura de YAML/JSON |
| `excel.py` | exportação com fórmulas vivas |
| `cli.py` | linha de comando |

## Aviso

Os números valem o que valem as premissas. A ferramenta automatiza a aritmética
e a documentação do modelo, não o julgamento — revise as premissas antes de usar
qualquer resultado em decisão de investimento.
