# Contexto do projeto

App e biblioteca de **valuation de empresas** com foco no mercado brasileiro,
em português. Este arquivo é o que uma sessão nova precisa saber antes de mexer
em qualquer coisa.

## O que é

Um app Streamlit em dez telas, por cima de um motor de valuation em Python.
Importa demonstrações financeiras, analisa o histórico, projeta o futuro, monta
o custo de capital, desconta os fluxos, decompõe o retorno esperado, testa
sensibilidade, critica o próprio modelo e exporta uma planilha Excel com
fórmulas vivas.

Serve dois públicos ao mesmo tempo: o analista experiente, que segue direto
pelas telas, e o analista em formação, que lê os blocos explicativos. **Isso não
é enfeite — é requisito.** Cada tela explica o que calcula, por que aquilo afeta
o valor e qual é o erro comum naquele ponto.

## Como rodar

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,dev]"

streamlit run app/main.py     # o app
pytest                        # 825 testes
valuation dcf exemplos/empresa_exemplo.yaml --excel modelo.xlsx   # a CLI
```

Python 3.11+.

## Arquitetura

```
src/valuation/          motor, sem nenhuma dependência do Streamlit
  premissas.py          estruturas de entrada e suas validações
  importacao/           leitura de DFs de qualquer origem → vocabulário canônico
    esquema.py          contas canônicas, sinônimos e códigos CVM
    leitura.py          números, cabeçalhos de ano, coluna de códigos
    importador.py       orquestra e devolve Demonstracoes
    cvm.py              baixa os Dados Abertos da CVM; formato longo → anos
    template.py         gera o template preenchível
  historico.py          indicadores, DuPont, ROIC, premissas sugeridas
  custo_capital.py      beta, CAPM com risco-país, Kd, WACC
  projecao.py           projeção explícita, FCFF, FCFE, prejuízo fiscal
  dcf.py                desconto, valor terminal, ponte EV → equity
  retorno.py            TIR, TSR e decomposição, ponte com desalavancagem
  multiplos.py          avaliação relativa
  sensibilidade.py      tabelas, cenários, Monte Carlo
  diagnostico.py        verificações de consistência do modelo
  qualidade.py          o lucro vira caixa? veredito com o porquê
  casos_especiais.py    P&D, ciclicidade, leasing
  dados_setoriais.py    betas e prêmios por setor e país
  mercado.py            curva de NTN-B e Focus; risco-país implícito
  margem.py             margem de segurança e DCF reverso
  pares.py              peer group por perfil econômico, e não por rótulo
  referencias.py        onde cada indicador cai na base brasileira, medido
  qualitativo.py        evidência para as perguntas de framework, sem respondê-las
  relatorio.py          o material todo em um markdown diffável
  auditoria.py          de-para da leitura: identidades, contenção e origem
  projeto.py            salvar e retomar um valuation inteiro
  comparacao.py         ponte do que moveu o valor entre duas versoes
  biblioteca.py         pasta local de valuations, desligada por padrão
  excel.py              exportação com fórmulas vivas
  modelo.py             orquestração e substituição de premissas
app/                    interface Streamlit
  paginas/              uma tela por etapa do fluxo
  tema.py graficos.py componentes.py textos.py estado.py
```

**O motor não conhece o Streamlit.** Toda regra de negócio fica em
`src/valuation/`; `app/` só apresenta. Não mova lógica para as telas.

## Convenções que não devem ser quebradas

**Taxas são decimais.** `0.12` é 12%. Na interface o usuário digita pontos
percentuais (12,5) e a tela converte — pedir 0,125 é convite a erro de ordem de
grandeza.

**Premissas são dataclasses `frozen=True`.** Alterações vão por
`substituir_varios(objeto, {"caminho.pontilhado": valor})`, que aplica tudo numa
operação só. Aplicar uma de cada vez passa por estados intermediários inválidos.

**`CombinacaoInviavel` versus `ValueError`.** Premissa economicamente impossível
(g acima do WACC) vira `NaN` na tabela e rodada descartada no Monte Carlo. Nome
de premissa digitado errado **levanta erro** — uma tabela inteira de `NaN` por
causa de um typo é pior que nenhuma tabela, porque parece resultado.

**Nada é descartado em silêncio.** O importador devolve linhas não reconhecidas,
contas derivadas e divergências contábeis como campos do resultado, e a tela
mostra tudo.

**O app não grava nada em disco — exceto quando mandam.** O estado vive na
sessão, e é isso que permite publicar num servidor compartilhado sem revisar o
código inteiro. A única exceção é `biblioteca.py`, que **nasce desligada**: só
existe quando `VALUATION_BIBLIOTECA` aponta para uma pasta, o que é escolha de
quem roda o app na própria máquina. Num deploy a variável não é definida e não
há caminho de código em que o servidor comece a guardar valuations por acidente.
Ao mexer ali, mantenha essa propriedade: o botão não existe quando desligada, em
vez de existir e falhar.

**Os arquivos da CVM têm armadilhas que já custaram caro.** `ORDEM_EXERC` traz
`ÚLTIMO` e `PENÚLTIMO` no mesmo arquivo — o zip de 2024 já contém 2023, e
empilhar anos sem filtrar duplica o ano do meio. `ESCALA_MOEDA` diz se os
valores estão em `MIL` ou em `UNIDADE`, e **varia entre empresas do mesmo
arquivo**; ignorá-lo erra a empresa por mil vezes. Todas estão travadas por
teste em `tests/test_importacao_cvm.py`, contra recorte do arquivo real.

**O código CVM só vale dentro do plano em que foi escrito.** A CVM publica
planos de contas distintos para indústria, bancos e seguradoras, e o mesmo
código muda de conta entre eles: `3.06` é "Resultado Financeiro" em 450
companhias e "IR e CSLL" em 17. O plano é detectado uma vez por companhia pelo
topo da DRE; fora do industrial o reconhecimento passa a ser só pelo rótulo e a
tela avisa. Confiar no código sem isso põe número errado na conta certa, calado.

**A D&A não estava sendo lida, e isso era o maior erro da base.** O rótulo da
CVM vem no plural ("Depreciações e Amortizações") e o vocabulário declarava no
singular; e `reconhecer` escolhia o candidato **antes** de conferir a
demonstração, então a conta da DRE ganhava sempre e `depreciacao_dfc` era
inalcançável — apesar de a maioria das companhias só divulgar D&A no ajuste da
DFC. Resultado medido em 150 companhias de 2024: **8 tinham D&A reconhecida.
Depois da correção, 116.** As outras 142 tinham EBITDA igual ao EBIT, com a
mediana da base tendo D&A valendo 24% do EBIT. Na Raia Drogasil escondia R$ 1,85
bi; na WEG, R$ 812 mi.

Três correções, todas medidas antes de entrar: `singularizar()` reduz plurais
dos dois lados da comparação (1.085 linhas novas reconhecidas na base, 20 linhas
mudando de conta — e essas 20 eram correções); `reconhecer(..., demonstracao=)`
busca dentro da demonstração certa em vez de rejeitar depois; e
`Derivacao.substitui_zero` deixa a derivação passar por cima de uma série que a
DRE publica como zero.

**IFRS 16: as duas leituras não se misturam.** Desde 2019 o aluguel saiu do
resultado e virou depreciação mais juros, então o EBITDA subiu sem nada melhorar.
Medido: Raia Drogasil com margem EBITDA de 10,8% reportada e **6,5% ex-IFRS 16**;
Pague Menos 8,6% → 3,3%; Smart Fit **48,0% → 21,8%**. `ver_ex_ifrs16` monta as
duas visões a partir do desembolso na DFC (`EBITDA_ex = EBITDA − aluguel`,
`EBIT_ex = EBIT − juros`, `dívida_ex = dívida − arrendamento`).

A regra que a tela repete e os testes travam: **ou dívida com arrendamento sobre
EBITDA com aluguel, ou dívida sem sobre EBITDA sem.** Cruzar infla a alavancagem;
ao contrário, esconde. Cobertura: 258 das 467 companhias publicam o principal,
184 os juros — sem os juros o ajuste é declarado como **piso**. A depreciação do
direito de uso viria mais direto, mas só 10% a publicam.

**As duas bases não coincidem no valuation, e a diferença tem nome.** Escrevi
que deveriam, já que IFRS 16 é apresentação. Errado: o balanço reconhece o
aluguel do **prazo contratado**, e quem aluga ponto renova. Medido num caso sem
crescimento, aluguel de 10/ano e passivo de 37,9 — o VP perpétuo do aluguel após
imposto ao WACC é **49,4**. Na Raia Drogasil: passivo de R$ 4,4 bi contra R$ 9,3
bi de aluguel perpétuo. A distância é quanto do valor vem de supor que o aluguel
acaba, e a aba IFRS 16 mostra as duas avaliações lado a lado.

`empresa_ex_ifrs16` converte as quatro pontas de uma vez (margem, depreciação,
adições projetadas, ponte). **O D/E alvo não é convertido** — quem o escolheu
escolheu com a dívida cheia em mente.

**O juro pago é padronizado para o operacional, abaixo do capital de giro.** O
IFRS deixa a companhia escolher onde classificar juro pago, e a base se divide:
**223 companhias no operacional, 121 no financiamento** (13 em ambos). Duas
empresas idênticas com classificações diferentes têm FCO diferente, e todo
indicador que divide por FCO passa a comparar apresentação em vez de negócio.
Pior: a WEG mudou a própria classificação entre 2022 e 2023 — a série dela não
era comparável nem consigo mesma.

`_padronizar_juros_no_fco` traz o juro de 6.03 para o operacional, **abaixo da
variação do capital de giro e junto dos impostos pagos**, que é onde o analista
espera vê-lo: o FCO passa a ser caixa depois de servir a dívida, para todo mundo.
A alternativa — somar de volta o juro de quem já o tem dentro — produziria um
FCO antes de juros que companhia nenhuma publica. A identidade da DFC sobrevive
por construção (o que sai do financiamento entra no operacional); verificado em
175 de 175 companhias mensuráveis, zero quebras. O ajuste vira conta visível
(`juros_pagos_no_financiamento`) e aviso — número que muda sozinho, sem
aparecer, é o pior tipo de correção.

Efeito medido: o impacto sobre o FCO das 121 companhias afetadas tem mediana de
**28%**, e passa de 30% em quase metade delas.

**Dentro do FCO também há coisa no lugar errado.** A seção `6.01.02` é
"variações nos ativos e passivos" — capital de giro. Muita companhia lança ali o
que não é movimento de saldo: medido em 2024, **127 companhias põem imposto de
renda pago dentro do giro (R$ 44,7 bi) e 69 põem juros pagos (R$ 23,4 bi)**. O
FCO não muda com isso, mas o *investimento em giro* que se lê da DFC vira outra
coisa — e ele é premissa de projeção. Na WEG o giro aparentava consumir
R$ 2.310 mi e consome **R$ 774 mi**.

A separação que importa é entre **pagamento e saldo**: "Impostos a recuperar" e
"Tributos a recolher" são giro de verdade e ficam; "Imposto de renda e
contribuição social pagos" desce para junto do juro. Em amostra de 200
companhias, 69 tiveram pagamentos retirados do giro.

**Outorga de concessão é capex e vai para o investimento** — mas o padrão é
estreito **de propósito**. Na DFC a palavra "outorga" aparece sobretudo em
"Opções outorgadas" e "Instrumentos patrimoniais outorgados", que são
remuneração em ações: com padrão largo são 38 companhias e a maioria é plano de
opções; com o padrão de `poder concedente|ônus da outorga|outorga fixa|...`, são
**9 companhias e R$ 3,4 bilhões**, todas concessão. A identidade da DFC se
preserva: o que sai do operacional entra no investimento.

**Três coisas que pareciam juro pago e não eram**, achadas ao examinar as 13
companhias que classificam juro nas duas seções:

- `exceto juros` — "Pagamento de empréstimos e arrendamentos (exceto juros)" é
  amortização de principal. Contava R$ 2,2 bi na Porto Seguro e R$ 2,7 bi na
  Ambev como juro.
- `principal e juros` — linha que mistura os dois não dá para separar, e
  contá-la inteira infla o Kd. São 18 linhas e **R$ 21,5 bi**, com R$ 12,4 bi só
  na Motiva.
- JCP com grafia variante — "Juros sobre capital **prório**" escapava. O padrão
  agora casa por "juros sobre … capital" e não pela grafia de "próprio", para
  não excluir "Juros de instrumento elegível a capital principal", que é juro.

As duas leituras do juro (a conta somada que alimenta o Kd e a reclassificação)
usam **o mesmo padrão de exclusão**, e há teste que quebra se alguém separá-los.

**Os cortes de conversão são os quartis medidos, não convenção.** Medidos de
novo depois das correções de sinal e da D&A da DFC: P25 = **15,0%**, mediana =
**51,4%**, P75 = **75,5%**. Os cortes são 0,15 e 0,76, e o de baixo acusa 25,2%
da base — um quarto, que é o que um corte no quartil deve acusar. O 90%/60% de
convenção não transfere: o FCO
brasileiro é líquido de imposto (34%) e de juro, e o EBITDA é antes dos dois —
90% era referência de um mercado de imposto e juro baixos. Histórico das
calibrações, porque cada uma corrigiu um erro: 0,60 acusava 47,3% da base antes
da correção da D&A; depois dela, ainda 30%; a padronização do juro derrubou a
mediana de 64% para 54%; e trazer a D&A da DFC subiu o EBITDA da cauda, o que
baixou a conversão de 53,9% para 51,4% e o P75 de 77,6% para 75,5%.

**Corte de leitura sem medição vira ruído.** O sinal de juro descolado usava
2 p.p. de diferença entre a despesa financeira da DRE e o juro pago da DFC.
Medido em 368 companhias: **a mediana brasileira descola 8,2 p.p.**, porque a
linha `3.06.02` junta variação cambial e monetária de todo o passivo. O corte
antigo acusava **82,3% da base** — sinal que dispara em quatro de cada cinco não
dirige atenção, gasta. Os cortes agora são o P75 (16,9 p.p.) e o P90 (34,5 p.p.),
e acima de `KD_MAXIMO_PLAUSIVEL` o sinal se recusa a medir: com pouca dívida, a
razão deixa de ser custo de dívida (WEG dá 45%). Ver `referencias.py`.

**O ITR tem uma pegadinha própria, e ela é de período.** Para `DT_REFER` de
30/09, a DRE traz **duas linhas da mesma conta**: o acumulado do exercício
(01/01–30/09, R$ 30,5 bi de receita na WEG) e o trimestre isolado
(01/07–30/09, R$ 10,3 bi). Somar as duas infla um terço; pegar a errada muda o
número pela metade. E no **primeiro** trimestre há uma linha só — então "pegar a
última" acerta em março e erra em setembro. A regra que funciona sempre: o
acumulado é a linha de **período mais longo**. Medidas as durações em 2025, só
existem três faixas (89–91, 180–183, 272–274 dias).

Duas diferenças em relação ao DFP: o `PENÚLTIMO` do ITR **é dado útil** (o mesmo
período do exercício anterior, a metade que falta do ano móvel), e no balanço ele
é o fim do exercício anterior, não o mesmo trimestre — comparar os dois casaria
saldo de setembro com saldo de dezembro.

`importar_ltm` monta o ano móvel: `exercício fechado + acumulado − mesmo período
do ano anterior`, para contas de resultado e de caixa; balanço é o **saldo do
trimestre**, não uma soma. O exercício-base é o anterior ao que o ITR acumula, e
não "o DFP mais recente" — usar o mais recente contava os mesmos meses duas
vezes e inflava a receita da WEG em R$ 2,8 bi. Verificado contra o arquivo: WEG
37.987 + 30.557 − 27.165 = 41.380; São Martinho (exercício fecha em março)
7.162 + 5.188 − 5.424 = 6.926.

**O arrendamento não fica onde o plano diz que fica.** A CVM reserva
`2.01.04.03` e `2.02.01.03` para "Financiamento por Arrendamento", dentro da
subárvore de empréstimos. **190 das 467 companhias de 2024 não usam esse lugar**:
põem o passivo do IFRS 16 em "Outras Obrigações" (`2.01.05`, `2.02.02`), fora da
dívida. São R$ 194,9 bilhões no total — 62,6% do que deveria ser a dívida bruta
da TIM, 55,8% da Claro, R$ 13,2 bi da GOL. Ler só o código fixo devolve dívida
menor que a real, e dívida menor vira equity value maior, **em silêncio**, porque
a árvore publicada continua fechando. `_somar_arrendamento_fora_da_divida` em
`cvm.py` devolve essas linhas à dívida bruta e ao arrendamento, contando só as
mais externas para não somar pai e filha, e avisa que corrigiu.

**Capex, juros pagos e dividendos pagos não existem como linha única.** A CVM
padroniza só os totais de seção da DFC (`6.01`, `6.02`, `6.03`); abaixo é conta
livre. Cada um chega partido em várias rubricas e é remontado por soma em
`REGRAS_SOMADAS`, que declara o que **exclui** — "Dividendos recebidos" aparece
em 80 companhias e não é dividendo pago; venda de imobilizado fala de
imobilizado e não é capex. A direção é o que separa, não o assunto.

**Textos em português acentuado, números no padrão brasileiro** (milhar com
ponto, decimal com vírgula). Use os formatadores existentes; não escreva
`f"{x:.1%}"` em texto de usuário.

**Gráficos** seguem `app/graficos.py`: nenhum eixo secundário, cor por
identidade em ordem fixa, escala sequencial de um tom só, tabela de dados ao
lado de todo gráfico. A paleta em `app/tema.py` foi validada para daltonismo e
contraste em modo claro e escuro — **não troque cor por gosto**.

## Decisões de modelagem

Estas afetam o número final. Não as altere sem entender o porquê.

- **Ke montado em USD nominal** (`rf + β × ERP + λ × risco-país`) e convertido
  para BRL por diferencial de inflação. Somar prêmio americano a taxa brasileira
  contaria risco soberano duas vezes.
- **Perpetuidade com reinvestimento normalizado**: `NOPAT_n × (1+g) × (1 − g/ROIC)`.
- **Retornos sobre capital médio** (abertura + fechamento) / 2, como o CFA manda.
- **Capital de giro é estoque**; a variação é derivada. Só recebíveis, estoques e
  fornecedores — caixa e dívida já estão na ponte.
- **Imposto sobre o EBIT**, porque o FCFF é desalavancado. Prejuízo fiscal segue
  a **trava dos 30%** brasileira.
- **Kd vem do juro pago na DFC, não da despesa financeira da DRE.** A linha
  `3.06.02` da CVM chama-se "Despesas Financeiras" mas junta variação cambial e
  monetária de todo o passivo: na WEG de 2024 dá 48% da dívida, contra 4,5% de
  juro efetivamente pago. Pela DRE, 28% das 467 companhias de 2024 recebiam Kd
  acima de 25% — WACC inflado, valor derrubado, sem aviso. Com o juro pago, zero.
  Acima de `KD_MAXIMO_PLAUSIVEL` o Kd é descartado e montado sinteticamente.
- **Múltiplos de EV e de equity não se misturam** na ponte da dívida.
- **TSR decomposto pela identidade exata**, com o termo cruzado explícito:
  `g_lucro + g_múltiplo + (g_lucro × g_múltiplo) + dividendos`. A regra de bolso
  do mercado omite o termo cruzado.
- **Monte Carlo com semente fixa** — resultado que muda a cada execução é
  indefensável em revisão.

## Como testar

`pytest` roda tudo. As regras que valem:

- **Contas conferidas na mão** onde é possível (trava dos 30%, capitalização de
  P&D, valor presente do leasing, casos isolados do TSR).
- **Identidades que precisam fechar**: DuPont multiplica de volta ao ROE; as
  parcelas do TSR somam a TIR; a ponte EV fecha exatamente; empresa sem dívida
  comprada pelo valor do DCF devolve exatamente o Ke.
- **As fórmulas do Excel são validadas célula a célula** contra o motor Python
  (`tests/test_excel_formulas.py`, usando o pacote `formulas`). Planilha que
  calcula diferente do motor é pior que planilha nenhuma.
- **O app é verificado no navegador**, com Playwright, percorrendo o fluxo real:
  `python tools/navegador.py <porta>`, com o app rodando. Ele importa a WEG pela
  própria interface, percorre as doze telas e todas as abas de cada uma, e acusa
  exceção desenhada na página, markdown cru e rolagem horizontal.

  **Isso não é redundante com o `AppTest`.** O `AppTest` executa a tela em
  processo e pega exceção, widget que não monta e tipo que o Arrow recusa; o que
  ele não vê é o que só existe depois do render. Dois defeitos da aba de DRE
  saíram daí e nenhum teste os pegaria: a unidade repetida em **cada uma das 154
  células** (22 linhas × 7 anos), empurrando o número para fora da largura útil,
  e o rótulo cortado — "(+/−) Equivalência patrimonial" virava "(+/−)
  Equivalência" e "(−) Itens não recorrentes" virava "(−) Itens não reco",
  justamente as duas linhas que precisam ser distinguidas das vizinhas.

  Duas armadilhas do próprio script, custaram tempo: **navegue pelo menu, nunca
  por `goto`** — recarregar a página abre outra sessão do Streamlit e o histórico
  importado se perde, e toda tela aparece vazia; e **`st.dataframe` desenha em
  canvas**, então `inner_text()` não lê o conteúdo da tabela. Para conferir
  número em tabela, tire foto do elemento e olhe. **Rode o app e olhe antes de
  dar por pronto.**

## A auditoria de leitura, e o que ela achou

`auditoria.py` varre a base inteira e pergunta, conta por conta, de onde o
número veio e se ele fecha com os que deveriam limitá-lo. Rodar é
`python -m valuation.auditoria` sobre o cache, ou `auditar_base(...)`. São três
famílias: **identidades** (ativo = passivo, seções da DFC, decomposição do FCO),
**contenção** (conta filha não excede a que a contém) e **origem** — o de-para
de qual código CVM alimentou cada conta canônica, em quantas companhias.

A terceira é a que pega o erro que nenhuma soma denuncia. Conta que vem de
`3.01` em 400 companhias e de outro código em duas não quebra identidade
nenhuma, e está errada.

**Resultado das cinco rodadas: 726 → 230 → 14 → 7 → 2 achados em 467
companhias.** Os 2 que sobraram são companhias que publicam **receita líquida
negativa**, e isso é leitura fiel do que elas publicaram. **Não resta nenhum
defeito de leitura conhecido na base.**

As 5 últimas a cair tinham todas a mesma causa, e a auditoria vinha apontando
para ela sem que ninguém tivesse ligado o fio: eram as únicas onde
`geração + giro` não explicava o FCO, e **todas publicam a DFC pelo método
direto** (ver abaixo).

O que a auditoria corrigiu, medido:

| Achado | Companhias | O que era |
|---|---|---|
| D&A com sinal negativo | 48 → 0 | D&A é magnitude; `EBITDA = EBIT + D&A` não admite negativo. 43 eram industriais |
| D&A não reconhecida | 106 | **R$ 121 bi** invisíveis — cauda de rótulos ("Depreciações, amortizações e desvalorizações") que listar sinônimo a sinônimo não termina |
| D&A partida em várias linhas | 127 | Mais R$ 4 bi: a disputa por confiança ficava com uma linha e descartava o resto |
| `6.01.03` nunca lido | 459 | A decomposição do FCO fechava em 47%; com o termo, **96,8%** |
| Arrendamento longo na conta de curto | 2 | Rótulos idênticos nos dois códigos; nenhuma identidade pegaria |

D&A virou **regra somada** sobre `6.01.01` — na seção de ajustes ao lucro, linha
que fala de depreciação **é** depreciação, sem precisar de verbo. Cobertura de
`depreciacao_amortizacao` foi de 366 para 434 companhias.

**E entre as duas fontes, a da DFC tem prioridade — não é preferência, é
estrutura.** A linha da DRE mora em `3.04.02.x`, **dentro de "Despesas Gerais e
Administrativas"**: ela captura só a depreciação que correu pelo SG&A, e a que
correu pelo CPV — que numa indústria ou concessionária é a maior parte — não está
ali. O ajuste da DFC (`6.01.01.x`) devolve ao lucro **toda** a D&A que o reduziu,
que é exatamente o que `EBITDA = EBIT + D&A` pede.

Medido nas 467 de 2024: 368 já vinham da DFC e 61 da DRE. Entre as **56 que
publicam as duas, a da DFC nunca é menor** — 34 coincidem exatamente e em 22 a da
DFC é maior:

| Companhia | D&A na DRE | D&A na DFC | Razão |
|---|---|---|---|
| Axia Energia Norte | R$ 5,1 mi | R$ 1.568,6 mi | **310x** |
| CPFL Energias Renováveis | R$ 11,0 mi | R$ 690,2 mi | 63x |
| CPFL Energia | R$ 142,0 mi | R$ 2.303,1 mi | 16x |

O efeito na margem EBITDA tem mediana zero — a maioria já vinha da DFC ou coincide
— e **P90 de +11,2 pontos**: CPFL Energias Renováveis vai de 48,8% para 67,5%, a
Eneva de 23,7% para 34,3%. Quando só a DRE tem o número (5 companhias), ela fica.

`_preferir_a_da_do_fluxo_de_caixa` faz a troca, registra em `derivadas` **nomeando
as duas linhas**, e **corrige o de-para**: origem registrada apontando para
`3.04.02.x` num número que veio de `6.01.01.x` é o tipo de erro que soma nenhuma
denuncia, e é o que a auditoria de origem existe para pegar.

**A DFC pelo método direto usa os mesmos códigos para outras contas.** É o mesmo
problema do plano financeiro, num lugar onde ninguém esperava. A CVM publica os
dois métodos em arquivos separados (`DFC_MI` e `DFC_MD`), o app lia os dois no
mesmo grupo `dfc`, e só a numeração do indireto estava mapeada:

| Código | Método indireto | Método direto |
|---|---|---|
| `6.01.01` | Caixa Gerado pelas Operações | **Recebimento de Consumidores** |
| `6.01.02` | Variações nos Ativos e Passivos | **Fornecedores — Materiais e Serviços** |
| `6.01.03` | Outros | **Fornecedores — Energia Elétrica** |

São **16 das 467 companhias de 2024**, e nelas o app punha recebimento de
clientes em `caixa_das_operacoes` e pagamento a fornecedores em
`variacao_capital_giro`. Nenhuma identidade denunciava, porque `6.01` continua
sendo o total do operacional nos dois métodos — mas **as 5 únicas companhias em
que a decomposição do FCO não fechava eram todas do método direto.**

`detectar_metodo_da_dfc` decide **pelo arquivo, não pelo rótulo**: das 16, só 9
abrem com "Recebimento de Consumidores", e uma regra por nome perderia as outras
7. O arquivo é a declaração da própria companhia. Detectado o direto,
`caixa_das_operacoes`, `variacao_capital_giro`, `outros_operacionais` e
`depreciacao_dfc` ficam **em branco** — elas descrevem a reconciliação do lucro
com o caixa, e a DFC direta não reconcilia nada, ela lista recebimentos e
pagamentos. Não há equivalente, e inventar um seria pior que a ausência: é a
mesma decisão tomada para bancos. O total do operacional, o investimento e o
financiamento continuam válidos, e a tela avisa.

**A margem sugerida parte da recorrente, e não da reportada.** Impairment, venda
de ativo e ganho tributário entram na DRE do SG&A para baixo e contaminam EBIT e
EBITDA por igual — a D&A não muda com eles, então a subtração é a mesma nos dois.
`sugerir_premissas` passou a usar `Margem EBITDA recorrente`, e o ajuste vai nos
**dois sentidos**: na Vale a mediana 2020-2024 vai de 38,7% reportada para
**51,9% recorrente** (o item foi impairment, uma perda), e na CESP vai de 72,5%
para **52,9%** (foi ganho). Na WEG, 19,9% → 21,4%; na Raia Drogasil, 11,1% →
10,9%. Diferença de 2 p.p. ou mais vira alerta, porque trocar a base da projeção
sem avisar é mudar o número em silêncio.

**O app abre todas as demonstrações, e o vocabulário é uma camada de nomes.**
Medido na WEG de 2024, o zip traz **574 linhas consolidadas**; DRE, BP e DFC
somam 276. As outras 298 estavam em **DMPL, DVA e DRA**, que não eram abertas —
mais da metade do que a companhia publica. Das que eram abertas, nada se perdia:
a árvore (`detalhe`) tinha as 276, e as ~70 contas canônicas são a camada que o
motor consome, não um filtro.

Agora as seis entram. A DMPL tem uma dimensão a mais (`COLUNA_DF`, o componente
do patrimônio) e entra **somada pelas colunas**: sem isso a árvore repetiria o
mesmo código cinco vezes. Quem precisa da abertura por componente vai ao arquivo,
e o vocabulário não promete tê-la.

**A DVA responde o que a DRE padronizada não abre**, em 450 das 467 companhias:

| Código | O que é | Por que importa |
|---|---|---|
| `7.01.01` | Receita **bruta** | Contra a líquida do `3.01`, a diferença são impostos sobre vendas e devoluções — 9,0% na WEG, 21,2% na Vivara, 5,5% na Raia |
| `7.08.01` | Pessoal | Folha e benefícios; não existe em linha nenhuma da DRE |
| `7.08.02` | Impostos, taxas e contribuições | Tudo que foi ao governo, não só IR e CSLL |
| `7.08.03.02` | Aluguéis | **Não é o aluguel total** — ver abaixo |

**Cuidado com `7.08.03.02`.** Escrevi no vocabulário que ela seria a medida
direta do aluguel, melhor que a aproximação pelo desembolso da DFC. Medi: vale
**0,19x** o desembolso na mediana de 81 companhias. Depois do IFRS 16 quase todo
aluguel saiu dessa linha e virou depreciação mais juros; sobra ali o
arrendamento de curto prazo e de baixo valor, que a norma dispensa. Usá-la na
leitura ex-IFRS 16 subestimaria o aluguel em cerca de 80%. Há teste travando.

**Lucro líquido acima do lucro bruto é contábil, e é um sinal.** Reversão de
impairment, venda de ativo, ganho tributário e ganho judicial entram na DRE **do
SG&A para baixo** e podem levar EBIT, LAIR e lucro líquido acima do lucro bruto.
Não é erro; é resultado que não se repete. A CVM padroniza os códigos, então a
separação não depende de adivinhar rótulo:

```
3.04.03  Perdas pela não recuperabilidade de ativos (impairment)
3.04.04  Outras receitas operacionais
3.04.05  Outras despesas operacionais

EBIT recorrente = EBIT − (3.04.03 + 3.04.04 + 3.04.05)
```

Com o **sinal publicado**, não com magnitude: reversão entra positiva, perda
entra negativa, e a subtração cuida dos dois casos. As três contas não existiam
no vocabulário — somam R$ 511 bi em 2024 e não eram lidas.

Medido: **165 de 172 companhias** têm item não recorrente diferente de zero, com
peso mediano de **17,4% do EBIT** e acima de 20% em quase metade. CESP tem
margem EBIT de 134% reportada e **21,5% recorrente**. E o ajuste vai nos dois
sentidos: na Vale o item foi impairment, então a recorrente (33,8%) é **maior**
que a reportada (26,9%).

A equivalência patrimonial (`3.04.06`) fica **fora da subtração**, de propósito:
para uma holding ela é o negócio, para uma indústria é resultado de coligada que
não gera caixa na controladora. Excluir por padrão acertaria numa e erraria na
outra, então ela aparece separada.

## A DRE gerencial, e os dois erros de sinal que ela revelou

A árvore da CVM serve para fiscalizar; para modelar é preciso outra forma, que
é a do dono do projeto e está em `Demonstracoes.dre_gerencial()`:

```
ROL − custos = LB
LB − SG&A + equivalência + outras receitas/despesas = EBIT
EBIT + D&A = EBITDA
EBITDA + ajustes = EBITDA ajustado
EBIT ± resultado financeiro = LAIR
LAIR − impostos = LL consolidado → controladores
```

São 22 linhas, com o resultado financeiro aberto em receitas, despesas e
derivativos/câmbio, e o imposto aberto em corrente e diferido. Aba **DRE** em
Histórico, em valores ou em percentual da receita.

**Duas coisas saem por subtração, e é decisão e não atalho.** O SG&A vem do
bloco `3.04` menos o que não é SG&A — as contas `3.04.01` e `3.04.02` só existem
em 297 e 454 das 467 companhias, e `3.04` existe em todas. Derivativos e câmbio
vêm do resíduo do resultado financeiro: não há código padronizado para eles, e
quando a companhia abre a linha ela cai num código livre dentro de `3.06`.

**`conferir_dre_gerencial()` anda junto e aparece na tela.** Ponte montada por
subtração com sinal trocado produz uma DRE que parece certa e não fecha; foi
exatamente o que aconteceu **três** vezes, e nenhuma outra verificação da
auditoria pegava:

- **`imposto_corrente` estava guardado como magnitude.** Na WEG de 2023 o
  diferido foi **crédito** de R$ 404,8 mi; somado como despesa, a ponte dava
  R$ 1.532,7 mi de imposto contra os R$ 723,2 mi publicados. `sinal_invertido`
  saiu da conta.
- **O bloco `3.04` também.** Numa holding ele é **positivo** — na Itaúsa,
  +R$ 14 bi, porque a equivalência supera as despesas —, e a magnitude jogava
  essa ordem de grandeza no SG&A. O bloco passa a vir de `EBIT − lucro bruto`,
  que é identidade e não depende de sinal publicado.
- **E `impostos` (`3.08`) também, com o alcance maior dos três.** Medido: **118
  das 467 companhias publicam `3.08` positivo**, R$ 71 bi de crédito lidos como
  despesa. Na DRE isso quase não aparecia, porque a ponte prefere `3.08.01` e
  `3.08.02`; onde doía era na **alíquota efetiva**, que é `impostos / LAIR`
  clipada em [0, 1] — crédito lido como despesa sobe a alíquota em vez de zerá-la,
  e com R$ 6,1 bi de crédito sobre LAIR de R$ 328,9 mi a razão passa de 1, é
  clipada em 100% e **zera o NOPAT**.

**O sinal do imposto não se decide por convenção de fonte, se mede.** `3.08` foi
mantido com magnitude porque planilhas de terminal publicam despesa positiva e a
CVM publica negativa. Mas a identidade que a própria companhia publica desempata:
**432 das 467 fecham `LAIR + 3.08 = 3.09` com o sinal publicado, e nenhuma fecha
com a convenção invertida.** `_corrigir_sinal_dos_impostos` passa a tirar o sinal
dali — da companhia, não da fonte —, mantendo a convenção de despesa positiva que
a derivação e a alíquota efetiva já usavam. Corrige **só o sinal**: quando as
magnitudes divergem a conta fica como foi lida, porque plug que absorve diferença
esconde erro de leitura, que é o que a ponte existe para achar. A correção entra
em `derivadas` e aparece na tela.

**Corrente e diferido não são duas metades do mesmo sinal.** Cada um pode ser
crédito por conta própria, e discordar é o caso comum. Medido no DFP consolidado
de 2024:

| | Companhias |
|---|---|
| Crédito no **diferido** (`3.08.02` > 0) | **221** de 467 |
| Crédito no corrente (`3.08.01` > 0) | 16 |
| Crédito nos dois | 8 |
| **Sinais opostos entre corrente e diferido** | **204** |
| `3.08.01 + 3.08.02 = 3.08` com o sinal publicado | **440 de 440** |
| … com magnitude | 0 |

Conferido conta a conta contra o arquivo bruto: **449 das 467 batem com sinal**
nas duas contas. As 18 que divergem são banco ou seguradora — Itaú, BTG, Pine, BB
Seguridade —, que publicam em outro plano e já eram detectadas e avisadas.

**O template mandava o usuário fazer errado.** A instrução dizia "custos,
despesas, **impostos** e capex podem ser positivos ou negativos: o app usa a
magnitude e padroniza o sinal sozinho" — verdade para custo, falsa para IR desde
que corrente e diferido passaram a guardar o sinal publicado. Quem seguisse
transformaria em despesa o crédito de 47% da base. O texto agora abre a exceção
com o número medido, e `_corrigir_sinal_do_ir_aberto` recupera o caso em que a
soma tem a magnitude do total e o sinal oposto. Quando corrente e diferido têm
sinais opostos e vieram como magnitude, **a informação se perdeu na origem e o app
não a inventa** — `_conferir` avisa que os dois não reconstroem o total.

Medido na base inteira depois das três correções, passo a passo:

| Passo da ponte | Fecha exato | Fecha até 1% | Não fecha |
|---|---|---|---|
| `ROL − custos = LB` | **467** | **467** | **0** |
| `LB − SG&A + equiv. + outros = EBIT` | **467** | **467** | **0** |
| `EBIT + D&A = EBITDA` | **467** | **467** | **0** |
| `EBITDA − não recorrentes = EBITDA aj.` | **467** | **467** | **0** |
| `EBIT ± resultado financeiro = LAIR` | 465 | 465 | 2 |
| `LAIR − IR = continuadas` | **467** | **467** | **0** |
| `continuadas + descontinuadas = LL` | 463 | 463 | 4 |
| `LL − não controladores = controladores` | 444 | 459 | 8 |
| **Cadeia inteira** | **440** | **455** | **12** |

Não há mais nenhum "sem dado": **identidade que fecha exatamente é aprovação, e
não ausência**, mesmo quando o subtotal é zero e não há denominador para o desvio
relativo. Eram 9 no lucro bruto — holdings e seguradoras sem linha de receita,
onde `0 − 0 = 0` é a resposta certa — e 2 nos controladores. Reportar `NaN` ali
dava impressão de cobertura faltando onde havia identidade trivialmente
verdadeira.

Duas leituras da mesma coisa: **440 fecham na aritmética exata** e 455 admitindo
1% (a diferença é arredondamento de demonstração publicada). Das 455, duas não
têm subtotal mensurável nenhum — então **453 são verificadas fechando**, contra
413 antes das correções de sinal.

**Os seis primeiros passos não falham em ninguém.** Tudo que sobra está nas duas
últimas linhas, e nenhuma é defeito de leitura:

- **8 publicam `3.11.01 + 3.11.02 ≠ 3.11`** — a árvore da própria companhia não
  fecha. A Azul publica R$ 9.190 mi de lucro aos controladores com consolidado de
  −R$ 9.151 mi; Cyrela, R$ 1.649 + (−R$ 272) contra R$ 1.921; Tupy e RCI zeram
  `3.11.02` com `3.11.01` diferente de `3.11`.
- **3 são banco ou seguradora** (Daycoval, BB Seguridade, IRB), onde `3.06` não é
  resultado financeiro. Já eram detectadas e avisadas antes desta ponte.
- **1 não está no cadastro** pelo nome, e não foi identificada.

**A tela acusa e não conserta**: consertar esconderia do analista que a companhia
publicou algo inconsistente.

**O passo dos controladores tinha 107 companhias sem denominador, e era bug.**
O valor apurado dava zero, e a conferência não tinha como dar desvio relativo.
Medida a causa: **102 das 467 publicam `3.11.01 = 0` e `3.11.02 = 0` com `3.11`
diferente de zero.** Não é que os controladores não tenham ganhado nada — é que a
companhia não tem minoritário e não repete o total na filha. Lido ao pé da letra,
o lucro dos controladores da CESP era **zero em vez dos R$ 1.077,9 mi** que ela
ganhou; na Axia Energia Nordeste, R$ 2.914,6 mi.

É o mesmo caso da D&A: **zero publicado que quer dizer "não abri", não "não
tem"** — e a correção é a mesma peça, uma `Derivacao` com `substitui_zero`.
Depois dela o passo vai de 337 para **442 fechando exato** e os 107 sem
denominador viram 2 (Rio Paranapanema e TIM S.A., que publicam `3.11` zerado — ali
zero é zero mesmo). A cadeia inteira não muda, porque conta que não fecha por
falta de denominador nunca era contada como falha; o que muda é que **102
companhias passam a ter lucro dos controladores correto** onde antes tinham zero.

**Duas verificações minhas estavam erradas, e a auditoria mostrou.** "Lucro
líquido não supera o bruto" acusou 29 companhias e as 29 estavam certas — Itaúsa
tem lucro líquido de R$ 14 bi sobre lucro bruto de R$ 2,4 bi porque vive de
equivalência patrimonial. E a decomposição do FCO acusava 126 companhias porque
eu não descontava o juro trazido do financiamento: em Panatlântica a diferença
era exatamente os R$ 59,75 mi reclassificados. Verificação que acusa o legítimo
não é verificação.

**O que sobrou, e por quê:** 2 companhias que publicam receita líquida negativa
— leitura fiel do que a companhia publicou, não defeito do app. Um caso do de-para que parece erro e não
é: `caixa_equivalentes` vindo de `1.01` em 20 companhias são **bancos**, onde
`1.01` é caixa mesmo e não ativo circulante.

## Estado atual

825 testes passando. Verificado de verdade: contas financeiras, identidades,
equivalência Excel/Python, as origens de importação, fluxo completo no
navegador.

O leitor da CVM foi construído **a partir dos arquivos baixados**, não de
memória: encoding, separador, colunas e domínios foram conferidos no arquivo
real antes de existir código. Os testes rodam contra recortes em bytes desses
mesmos arquivos (`tests/dados/cvm`), e o fluxo foi percorrido no navegador
importando a WEG de 2019 a 2025 pela tela nova.

**A importação foi rodada em lote nas 467 companhias com DFP consolidada de
2024**, e as identidades fecham em 100% delas: ativo = passivo; operacional +
investimento + financiamento + câmbio = variação de caixa; arrendamento e
debênture nunca excedem a dívida de que são parte. São 62 contas canônicas por
companhia, ante 26 antes.

**Não verificado, e é honesto dizer:**

1. A planilha nunca foi aberta no Excel de verdade (validada com o pacote
   `formulas`, que é independente mas não é o Excel).
2. Betas e prêmios de risco-país embarcados são **valores de referência de ordem
   de grandeza**, não a base oficial do Damodaran. O app rotula isso na tela.
3. Do ITR, só o **consolidado** é lido, e o ano móvel exige o exercício anterior
   fechado — companhia que abriu capital há menos de um ano não o tem.
4. Bancos e seguradoras (19 das 467) são detectados e avisados, mas o
   reconhecimento só por rótulo cobre bem menos contas, e o FCFF/WACC não se
   aplica a eles de qualquer forma.
5. As contas somadas por regra — capex, juros pagos, dividendos pagos — cobrem
   88%, 80% e 74% das companhias. O resto usa rótulo que nenhuma regra alcança
   e cai na lista de não reconhecidas, para mapeamento manual.

## Estressar macro, e o efeito que eu previ errado

Prática do dono do projeto, hoje representada no modelo: **IPCA de 5%** e **PIB
real de 1,5%** como base, com o **g perpétuo ancorado em IPCA ou em PIB
nominal** — `(1,05 × 1,015) − 1 = 6,58%`, composto e não somado.

Implementado: `PremissasMacro.pib_real` e `pib_nominal`;
`PremissasPerpetuidade.ancora` (`livre` / `ipca` / `pib_nominal`), resolvida em
`Empresa.__post_init__` porque é ali que macro e perpetuidade se encontram; o
teto do diagnóstico passou a sair de `macro.pib_nominal` em vez de
`inflacao_brl + 0.02` fixos; eixos e cenários macro na tela de Sensibilidade.

**Duas regras que existem para não criar armadilha silenciosa:**

1. Mexer no `g` por caminho pontilhado **solta a âncora**
   (`modelo.substituir_varios`). Sem isso, uma tabela de sensibilidade sobre o
   `g` ancorado sairia inteira igual — sem erro, sem aviso, sem nada na tela.
2. `macro.pib_real` **não altera o valuation** a menos que a âncora seja
   `pib_nominal`; fora disso ele só desloca o teto do diagnóstico. O eixo avisa.

### O que eu escrevi antes, e por que estava errado

Registrei aqui que estressar inflação seria "quase neutro em valor", e que o
pouco de efeito viria do spread `WACC − g` **abrindo**. Medido no modelo, com
choque de +2 p.p. de IPCA e `g` ancorado em PIB nominal:

| | g livre | g ancorado, sem ROIC | g ancorado, com ROIC 15% |
|---|---|---|---|
| Equity value | −56,5% | −3,2% | −47,5% |
| EV | −20,6% | −1,8% | −18,8% |

Dois erros no que eu tinha escrito:

- **O spread não abre, fecha.** `(1+g)` escala pelo fator cheio de inflação;
  `(1+WACC)` escala por menos, porque o Kd entra no WACC depois do benefício
  fiscal e o `(1−t)` não acompanha a inflação. No caso medido: WACC +1,92 p.p.
  contra g +2,03 p.p.
- **"Quase neutro" vale só sem normalização de reinvestimento.** Ligado o
  `roic_perpetuidade`, o fluxo perpétuo é `NOPAT × (1+g) × (1 − g/ROIC)`. Subir
  o `g` nominal sobe `g/ROIC` — de 37,1% para 50,6% do NOPAT no caso medido —
  enquanto o ROIC fica parado. O reinvestimento come mais do que o spread
  devolve, e o valor terminal cai 22,7%.

Não é defeito da âncora: é o modelo cobrando capital para sustentar crescimento
nominal maior. Mas **o padrão do app tem `roic_perpetuidade` ligado**, então o
caso "quase neutro" é a exceção, não a regra. A tela lê o modelo que está na
frente do usuário em vez de repetir a teoria — `_leitura_do_estresse` em
`app/paginas/sensibilidade.py`.

### Não há regra geral de sinal, e é por isso que a tela mede

Tentei salvar a conclusão dizendo "então ancorar amortece o choque". Também não
se sustenta. Medido com choque de +2 p.p. de IPCA, ROIC 15% ligado nos dois:

| | fixture (dívida líquida 650 sobre equity 487) | WEG 2024 (caixa líquido) |
|---|---|---|
| g livre | −56,5% | −17,9% |
| g ancorado em PIB nominal | −47,5% | −19,9% |

Ancorar **melhora** na empresa alavancada e **piora** na de caixa líquido. Na
WEG o choque de IPCA chega a bater mais forte que +2 p.p. de risco-país
(−17,9% contra −17,0% com g livre) — o oposto do que eu tinha registrado.

O que sobrevive como afirmação é só o mecanismo, e os testes em
`tests/test_macro.py` pinam ele e não as magnitudes: **risco-país entra só no
desconto; a inflação, ancorada, entra no desconto e no fluxo.** Qual dói mais é
propriedade da empresa, não do modelo. Nenhum texto de tela deve afirmar o sinal
— eles reportam o número medido.

**Ainda em aberto:** se o `g` é indexado à inflação, o ROIC marginal deveria ser
também — capital novo é comprado a preços novos. Deixar o ROIC nominal fixo
enquanto o `g` sobe embute uma piora real de intensidade de capital que ninguém
pediu. Não foi mexido: seria inventar uma premissa que o dono do projeto não
pediu, e o efeito é grande demais para entrar sem decisão dele.

Consequência prática que sobrevive: **prêmio de risco é o estresse macro mais
duro**, porque sobe o desconto sem contrapartida nenhuma no fluxo.

## Fontes de mercado já verificadas em campo (não implementadas)

Três APIs públicas foram confirmadas contra o endpoint real, com formato e
nomes exatos. Falta o módulo; a parte que costuma custar mais já está feita.

- **Focus / Expectativas de Mercado** (`olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata`):
  IPCA, Selic, PIB e Câmbio por ano de referência, com mediana, desvio e nº de
  respondentes. Nomes dos indicadores acentuados: `"PIB Total"`, `"Câmbio"`.
- **SGS do BCB** (`api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados`):
  série 432 Selic meta, 13522 IPCA 12 meses. Aceita `/ultimos/N`.
- **Tesouro Transparente** — preço e taxa diários de todos os títulos, incluindo
  a curva NTN-B. Latin-1, `;`, decimal com vírgula: **as mesmas convenções da
  CVM**, então o tratamento existente serve.

**O uso mais valioso da NTN-B não é virar `rf`, é calibrar `risco_pais`.** O Ke
é montado em USD por decisão documentada acima, e trocar isso pela curva local
esbarra num ERP local que a série brasileira não sustenta. Mas a curva permite
medir o parâmetro que hoje é chutado: NTN-B 2035 a 8,0% real, nominalizada pelo
IPCA longo do Focus (3,5%), dá `rf` BRL de 11,8%; o `rf_usd` de 4,5% convertido
por diferencial de inflação dá 6,2%. A diferença — perto de 5,5 pontos — é o que
o mercado cobra de risco Brasil, contra os **2,5% embarcados** como padrão.

Não é risco soberano puro: carrega o descasamento entre a inflação assumida no
app e a do Focus, mais prêmio de liquidez do título. A ordem de grandeza é
informativa; o número exige separar essas parcelas. Antes de mudar o padrão,
medir o efeito nas 467 companhias — taxa de desconto errada só aparece no
número final.

## Para onde isto vai

O objetivo declarado pelo dono do projeto é automatizar **a primeira camada da
análise de empresas** — a parte braçal: do dado bruto da CVM a um **relatório
estruturado**, aplicando os frameworks de sempre (Porter, Damodaran, qualidade
de earnings, margem de segurança), e que se atualiza quando sai balanço novo.
A decisão de investir continua humana; o que sai da mão é a transcrição.

Isso reordena as lacunas. Medido contra esse objetivo:

- **Ler a CVM** — feito, e conferido conta a conta contra a linha publicada.
  Desde agora inclui o **ITR trimestral**, com o ano móvel plugando na mesma
  série anual que o motor já consome.
- **Montar valuation** — o motor já fazia.
- **Atualizar quando sai resultado** — existe, detecta exercício novo.
- **Comparar com pares** — feito em `pares.py`. `SETOR_ATIV` é classificação de
  registro; o critério agora é o do Damodaran — comparável é a empresa com
  risco, crescimento e fluxo de caixa parecidos —, medido em seis dimensões com
  z-score robusto (mediana e IQR, não média e desvio: a base tem margem de 300%
  e um único extremo definiria a escala inteira). Exige 4 das 6 dimensões, senão
  companhia sem dado aparece no topo por falta de dado. Universo de 447
  companhias em `~/.cache/valuation/universo`, construído por
  `python -m valuation.pares`.

  Medido: os pares da WEG passaram a ser Intelbras (0,28), Mahle Metal Leve
  (0,34) e Solar Bebidas (0,41) — indústrias com ROIC alto. Intelbras está
  registrada como "Comércio" e o filtro por setor nunca a encontraria.
- **Qualidade dos lucros** — feito. `qualidade.py` transforma os indicadores
  dispersos em veredito, e o veredito é o **pior** sinal, não a média deles:
  média é como um alerta some. Aba própria em Histórico.
- **Relatório estruturado** — feito. `relatorio.py` monta em markdown o que a
  empresa entregou, o que o modelo assume, quanto vale, o que o preço embute e
  o que pode dar errado. Markdown de propósito: rodar de novo em três meses e
  comparar com um diff mostra o que mudou no raciocínio; um PDF novo só mostra
  que mudou alguma coisa. **A seção final lista o que ele não verifica**, e as
  seções ausentes aparecem escritas — quem lê precisa distinguir "verificado e
  está bem" de "não foi verificado".
- **Margem de segurança** — feito, em `margem.py` e tela própria. Junto veio o
  **DCF reverso**: para cada premissa, o valor que faria o modelo dar exatamente
  o preço pedido. É o que troca "acho caro" por uma afirmação conferível.
- **Risco-país observado** — a medição pela curva de NTN-B ganhou tela (aba em
  Custo de capital). Não busca nada sem o usuário pedir, e o padrão continua sem
  mudar sozinho.

## Lacunas conhecidas

Em ordem de valor:

1. **Capitalização de P&D e de leasing sem tela** — existem e são testados em
   `casos_especiais.py`, mas só a normalização cíclica chegou à interface. Agora
   que o arrendamento é lido do balanço (`2.01.04.03`, `2.02.01.03`) e o direito
   de uso também (`1.02.03.02`), a tela tem de onde partir.
2. **FCFE sem editor de cronograma de dívida** — o motor suporta, a tela de Valor
   oferece a opção, mas não há onde informar a dívida ano a ano.
3. **Arrendamento fechado nas três pontas.** O estoque é lido certo (inclusive
   fora da subárvore de dívida), a leitura ex-IFRS 16 existe, e a projeção agora
   faz o passivo crescer: `arrendamento_pct_receita` em `PremissasOperacionais`
   transforma a adição anual em saída de caixa, porque contrato novo de aluguel
   não passa pelo capex. Nasce desligado e `sugerir_premissas` só o propõe
   quando o arrendamento passa de 2% da receita. Medido: Raia Drogasil perde
   10,2% de equity value com a linha ligada; Smart Fit, 48,7%.

   O que ainda **não** está fechado: a perpetuidade cresce o FCFF já líquido da
   adição, o que assume implicitamente que a razão arrendamento/receita fica
   constante para sempre. É defensável e não foi verificado contra alternativa.
4. **Bancos e seguradoras** — FCFF/WACC não se aplica; precisaria de lucro
   residual ou FCFE com capital regulatório.
5. **Comparar duas versões do mesmo valuation** — diff de premissas com ponte
   mostrando o que moveu o valor.
6. **O ROIC indexado é opcional e nasce desligado.** Marcar a caixa não muda o
   valor de hoje — só a resposta ao estresse de inflação —, mas ligar por padrão
   mudaria o resultado de todo estresse já salvo. O diagnóstico avisa quando a
   combinação que exagera (g ancorado + ROIC nominal fixo) está montada.
7. **Os cortes de leitura agora têm as duas leituras** — absoluta e percentil.
   `referencias.py` guarda a distribuição medida em 447 companhias, e a
   qualidade dos lucros cita onde o número cai. `ALAVANCAGEM_ALTA = 3.5` era o
   corte não verificado, e **agora foi**: com a leitura corrigida, o P75 da base
   é 3,45 e o corte dispara em **24,0% das companhias**. Ele é o quartil, e o
   ~40% que eu tinha registrado vinha de números pré-correção. Os demais cortes
   do app ainda não têm a leitura de percentil.
8. **A seção qualitativa reúne evidência, não responde.** `qualitativo.py` traz
   as cinco forças mais a pergunta do fosso, cada uma com o que foi medido, o
   que os dados não alcançam e o campo do analista em branco. Ameaça de
   substitutos aparece **sem nenhum número** — omiti-la faria parecer que a
   pergunta não existe.
9. **A projeção não modela adições de arrendamento** (ver acima), e o universo
   de pares precisa ser reconstruído quando sai DFP nova — não há detecção
   automática.

## Como trabalhar neste projeto

- **Teste contra dado real antes de dar por pronto.** Os piores bugs desta base
  vieram de código de importação que nunca tinha visto o arquivo de verdade.
- **Diga o que não verificou.** Vale mais que parecer confiante.
- **Comentários explicam o porquê, não o quê.** O código diz o que faz.
- Commits em português, descrevendo a decisão e não só a mudança.
