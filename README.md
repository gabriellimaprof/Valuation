# Valuation

App de valuation de empresas com foco no mercado brasileiro. Importa as
demonstrações financeiras, analisa o histórico, projeta o futuro, monta o custo
de capital, desconta os fluxos, testa a sensibilidade das premissas, critica o
próprio modelo e exporta uma planilha Excel **com fórmulas vivas**.

Foi construído para servir duas pessoas ao mesmo tempo. Quem já faz valuation
segue direto pelas telas e usa o diagnóstico como checklist final. Quem está
aprendendo lê os blocos explicativos: cada tela diz o que está calculando, por
que aquilo afeta o valor e qual é o erro comum naquele ponto.

## Rodando

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[app,dev]"

streamlit run app/main.py
```

O app não grava nada em disco — todo o estado vive na sessão. Isso mantém os
dados de cada empresa dentro da própria sessão e deixa o mesmo código pronto
para rodar em um servidor compartilhado sem retrabalho.

Há também uma linha de comando, para rodar um modelo já versionado em YAML:

```bash
valuation exemplo                                             # gera exemplos
valuation dcf exemplos/empresa_exemplo.yaml --excel modelo.xlsx
valuation wacc exemplos/empresa_exemplo.yaml
valuation multiplos exemplos/comparaveis_exemplo.yaml
```

## O caminho pelo app

| Tela | O que faz |
| --- | --- |
| **Dados** | Busca a empresa direto nos **Dados Abertos da CVM** (por nome ou CNPJ), retoma um valuation salvo, ou importa DFs de export CVM/B3, de terminal (Economatica, Bloomberg, Capital IQ) ou do template do app. Mostra o que reconheceu e deixa corrigir o que errou. |
| **Histórico** | Margens, retorno, reinvestimento e ciclo de caixa, com as decomposições de DuPont e de ROIC. |
| **Premissas** | Projeção ano a ano, com a mediana histórica ao lado de cada campo como âncora. |
| **Custo de capital** | Beta por setor, risco-país e estrutura-alvo, com a montagem do WACC passo a passo. |
| **Valor** | Fluxos descontados, composição do valor e a ponte em cascata até o acionista. |
| **Retorno esperado** | TSR (TIR do investimento) aberto em crescimento de lucro, dividendo e re-rating de múltiplo, com o preço máximo para um retorno-alvo. |
| **Sensibilidade** | Mapa de calor bidimensional, cenários coerentes e Monte Carlo. |
| **Múltiplos** | Peer group, valor implícito por múltiplo e confronto com o DCF. |
| **Diagnóstico** | O app criticando o modelo antes de você defender o número. |
| **Exportar** | Planilha com fórmulas vivas e o valuation inteiro salvo em um arquivo YAML, para retomar depois. |

## Importação de demonstrações

A mesma função atende as origens baseadas em arquivo. O que muda entre elas —
código de conta, nomenclatura, sinal dos custos, posição do cabeçalho — é
absorvido no importador, e o resultado sai sempre no mesmo vocabulário canônico.

Detalhes que decidem se a importação funciona na prática:

- A **coluna de códigos CVM** é detectada separadamente da coluna de rótulos.
  Sem isso, "Empréstimos e Financiamentos" de curto e de longo prazo — que têm
  descrição idêntica no export da CVM — colidem e a dívida bruta sai errada.
- **Custos, impostos e capex são padronizados como magnitude positiva**, porque
  a CVM publica negativo e terminais publicam positivo. A mesma empresa não
  pode mudar de valor conforme a origem do arquivo.
- Números aceitam formato brasileiro e americano, negativo entre parênteses e
  símbolo de moeda.

Nada é descartado em silêncio: linhas não reconhecidas, contas derivadas e
divergências nas identidades contábeis aparecem na tela para conferência.

### Dados Abertos da CVM

`importacao/cvm.py` dispensa o arquivo: você escolhe a empresa e os anos, e ele
baixa a DFP de `dados.cvm.gov.br`. O vocabulário é o mesmo de `esquema.py` — o
que o módulo acrescenta é a camada de download e a conversão do **formato
longo** da CVM (uma linha por conta, por exercício) para colunas por ano.

```python
from valuation.importacao import buscar_companhias, carregar_cadastro, importar_cvm

catalogo = carregar_cadastro()                      # cadastro de companhias abertas
weg = buscar_companhias("WEG", catalogo)[0]         # ou por CNPJ
dfs = importar_cvm(weg, range(2019, 2025))          # valores em reais
```

O que o arquivo real exige, e que não se descobre lendo a documentação:

- **O encoding é `latin-1`, não UTF-8**, e o separador é `;`. Ler como UTF-8
  estoura na primeira palavra acentuada.
- **`ORDEM_EXERC` traz `ÚLTIMO` e `PENÚLTIMO` no mesmo arquivo.** O zip de 2024
  já contém 2023; empilhar dois anos sem filtrar duplica o ano do meio. O
  leitor usa só `ÚLTIMO`, então cada exercício entra uma vez e sempre na versão
  publicada no próprio ano.
- **`ESCALA_MOEDA` diz se os valores estão em `MIL` ou em `UNIDADE`**, e varia
  entre empresas do mesmo arquivo — em 2024, 459 companhias em milhares e 8 em
  unidades. A receita da WEG aparece como `37.986.941` (R$ 38 bi) e a da Vivara
  como `2.577.113.417` (R$ 2,6 bi). Ignorar o campo erra por mil vezes, para
  mais ou para menos conforme a empresa. Tudo sai convertido para reais.
- **Nem todo exercício social fecha em 31/12** (Raízen e São Martinho fecham em
  março, Camil em fevereiro): o ano vem de `DT_FIM_EXERC`, não do nome do
  arquivo.
- **Nem toda companhia publica consolidado** — 242 das 709 de 2024 só publicam
  individual. O leitor prefere o consolidado, cai para o individual quando não
  há, e avisa na tela quando isso acontece.
- **O código só vale dentro do plano em que foi escrito.** A CVM usa planos de
  contas distintos para indústria, bancos e seguradoras: `3.06` é "Resultado
  Financeiro" em 450 companhias e "IR e CSLL" em 17. O plano é detectado uma vez
  por companhia; fora do industrial vale só o rótulo, e a tela avisa.
- **Capex, juros pagos e dividendos pagos chegam partidos em várias linhas** e
  são remontados por soma. O que separa um do outro é a direção, não o assunto:
  "Dividendos recebidos" aparece em 80 companhias e não é dividendo pago.

São **62 contas canônicas por companhia**, com a DRE, o balanço e a DFC lidos na
ordem do plano de contas — dívida aberta em debêntures e arrendamento, direito
de uso, goodwill, o FCO separado entre geração e variação de giro. Rodado nas
467 companhias com DFP consolidada de 2024, as identidades fecham em todas:
ativo = passivo, e operacional + investimento + financiamento + câmbio =
variação de caixa.

Os arquivos ficam em cache (`~/.cache/valuation/cvm`): o segundo valuation da
mesma empresa não baixa nada de novo.

## Decisões de modelagem

Algumas escolhas afetam o número final e vale saber quais são:

**Custo de capital em duas moedas.** O Ke é montado em USD nominal
(`rf_usd + β × ERP_maduro + λ × risco_país`) e convertido para BRL nominal pelo
diferencial de inflação de longo prazo. Somar um prêmio de risco americano
direto a uma NTN-B contaria risco soberano duas vezes.

**Perpetuidade com reinvestimento normalizado.** Com `roic_perpetuidade`
informado, o fluxo perpétuo vira `NOPAT_n × (1+g) × (1 − g/ROIC)`. Crescer para
sempre exige reinvestir para sempre.

**Retornos sobre capital médio.** ROIC e ROE usam a média entre saldo de
abertura e de fechamento, como manda o material do CFA. Usar o saldo final
subestima o retorno de quem cresceu no período.

**Capital de giro é estoque.** O percentual informado descreve o *saldo*; a
variação que entra no fluxo é derivada dele. A conta usa apenas recebíveis,
estoques e fornecedores — incluir caixa e dívida de curto prazo os contaria
duas vezes, já que ambos estão na ponte de valor.

**Imposto sobre o EBIT**, já que o FCFF é desalavancado por construção. Prejuízo
fiscal acumulado abate lucro futuro respeitando a **trava dos 30%** da
legislação brasileira.

**O custo da dívida sai do juro pago, não da despesa financeira.** A linha
"Despesas Financeiras" da CVM não é juro de dívida: junta variação cambial e
monetária de todo o passivo. Na WEG de 2024 ela dá 48% da dívida bruta, contra
4,5% de juro efetivamente pago no caixa. Calculado pela DRE, 28% das companhias
recebiam um Kd acima de 25% com a Selic entre 10% e 14% — um WACC inflado que
derrubava o valor em silêncio. Pelo juro pago, nenhuma.

**Um valuation não se faz em uma sentada.** O arquivo salvo guarda tudo —
premissas, demonstrações importadas, comparáveis e convenções de cálculo — em
YAML de propósito: dá para abrir num editor, versionar em Git, revisar em pull
request e comparar duas versões de um mesmo valuation com um diff.

**A decomposição do TSR é exata, não a regra de bolso.** A identidade usada é
`(1 + retorno de preço) = (1 + g_lucro) × (1 + g_múltiplo)`, e o TSR fecha como
`g_lucro + g_múltiplo + (g_lucro × g_múltiplo) + dividendos`. A versão que
circula no mercado — "TSR = crescimento + dividend yield + re-rating" — omite o
termo cruzado, que deixa de ser desprezível justamente no caso em que a conta
importa: crescimento alto com re-rating relevante. Aqui ele aparece separado, e
as parcelas somam o total até a última casa.

**Múltiplos de EV e de equity não se misturam.** EV/EBITDA passa pela ponte da
dívida líquida; P/L não. Denominador não positivo vira `n/a` e sai das
estatísticas do peer group.

**Erro de premissa não vira célula vazia.** Uma combinação economicamente
impossível (g acima do WACC) vira `NaN` na tabela e rodada descartada no Monte
Carlo. Já um nome de premissa digitado errado levanta erro — uma tabela inteira
de `NaN` por causa de um typo é pior do que nenhuma tabela, porque parece
resultado.

**Monte Carlo com semente fixa.** Um valuation que muda de número a cada
execução é indefensável em revisão.

## Parâmetros setoriais

Os betas e prêmios de risco-país embarcados são **valores de referência de ordem
de grandeza**, com data de revisão, para que o app funcione sem rede e para dar
um ponto de partida plausível. Eles não são a base oficial do Damodaran e
envelhecem.

Para trabalho que vai para cliente ou comitê, baixe as planilhas oficiais em
`pages.stern.nyu.edu/~adamodar/New_Home_Page/data.html` e carregue com
`carregar_betas_damodaran` / `carregar_risco_pais_damodaran`.

## A planilha gerada

As abas **Premissas**, **Custo de Capital**, **Projeção** e **DCF** saem com
fórmulas do Excel, não com valores. Quem receber o arquivo altera uma premissa e
o modelo inteiro recalcula. Convenção de cores: azul é premissa editável, preto
é fórmula da própria aba, verde é referência a outra aba.

As abas de **Múltiplos**, **Sensibilidade**, **Cenários** e **Monte Carlo**
trazem valores calculados no Python e vêm rotuladas como tal.

`tests/test_excel_formulas.py` avalia o workbook fora do Excel e confere, célula
a célula, que as fórmulas reproduzem o motor Python. Uma planilha bonita que
calcula diferente do motor é pior do que planilha nenhuma, porque o erro só
aparece na mão de quem recebeu o arquivo.

## Gráficos

A paleta não foi escolhida por gosto: é a instância de referência validada do
guia de dataviz, verificada para banda de luminosidade, piso de croma, separação
sob daltonismo e contraste — em modo claro e escuro. As cores categóricas são
atribuídas sempre na mesma ordem, para que uma série mantenha a mesma cor entre
gráficos e entre telas.

Nenhum gráfico usa eixo secundário: receita e margem viram dois painéis, e a
decomposição de DuPont vira pequenos múltiplos. Todo gráfico tem a tabela de
dados disponível ao lado — três tons ficam abaixo de 3:1 de contraste no modo
claro, e o guia exige rótulo visível ou visão tabular nesse caso.

## Testes

```bash
pytest
```

441 testes cobrindo identidades contábeis, casos de borda econômicos, a
equivalência Excel/Python, as origens de importação e as regras de
visualização. A validação das fórmulas do Excel depende do pacote `formulas`;
sem ele esses testes são pulados em vez de dar falso positivo.

Os testes da CVM rodam contra **recortes em bytes dos arquivos reais** do portal
(`tests/dados/cvm`), com o `latin-1`, o `;` e o CRLF originais preservados —
não contra planilhas inventadas. São quatro companhias escolhidas por
comportamento: WEG (escala `MIL`), Vivara (escala `UNIDADE`), São Martinho
(exercício fecha em março) e Elektro Redes (só publica individual).

## Estrutura

| Módulo | Responsabilidade |
| --- | --- |
| `premissas.py` | estruturas de entrada e suas validações |
| `importacao/` | leitura de DFs de qualquer origem para o vocabulário canônico |
| `historico.py` | indicadores históricos, DuPont, ROIC e premissas sugeridas |
| `custo_capital.py` | beta, CAPM com risco-país, Kd, WACC |
| `projecao.py` | projeção explícita, FCFF, FCFE e prejuízo fiscal |
| `dcf.py` | desconto, valor terminal, ponte EV → equity |
| `retorno.py` | TIR, TSR e sua decomposição, ponte de valor com desalavancagem |
| `projeto.py` | salvar e retomar um valuation inteiro |
| `multiplos.py` | avaliação relativa por comparáveis |
| `sensibilidade.py` | tabelas, cenários e Monte Carlo |
| `diagnostico.py` | verificações de consistência do modelo |
| `casos_especiais.py` | P&D, ciclicidade e leasing |
| `dados_setoriais.py` | betas e prêmios por setor e país |
| `excel.py` | exportação com fórmulas vivas |
| `app/` | interface Streamlit |

## Aviso

Os números valem o que valem as premissas. O app automatiza a aritmética, a
documentação e a checagem de consistência do modelo — não o julgamento. Revise
as premissas antes de usar qualquer resultado em decisão de investimento.

