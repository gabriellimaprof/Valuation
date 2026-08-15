"""Conteudo explicativo do app.

O app precisa servir a duas pessoas ao mesmo tempo: o analista experiente, que
quer chegar ao numero rapido, e o estagiario, que precisa entender por que o
numero e aquele. A solucao adotada e a mesma em todas as telas -- o caminho
principal e direto, e a explicacao fica em blocos e expansores ao lado, sempre
disponivel e nunca obrigatoria.

Cada texto responde tres perguntas na mesma ordem: *o que e*, *por que importa
para o valor* e *o erro comum*. Explicacao que so define o termo nao ajuda
ninguem a decidir nada.
"""

from __future__ import annotations

CONCEITOS: dict[str, str] = {
    "fcff": (
        "**FCFF (fluxo de caixa livre para a firma)** é o caixa que a operação gera "
        "depois de pagar impostos e de fazer os investimentos necessários, e **antes** "
        "de pagar juros. Como ele ignora a estrutura de capital, é descontado pelo "
        "WACC e chega ao valor da empresa inteira (*Enterprise Value*). "
        "**Erro comum:** descontar o FCFF pelo custo do capital próprio — isso mistura "
        "um fluxo de todos os financiadores com a taxa exigida por apenas um deles."
    ),
    "fcfe": (
        "**FCFE (fluxo de caixa livre para o acionista)** é o que sobra depois de pagar "
        "juros e movimentar dívida. Desconta-se pelo Ke e o resultado já é o valor do "
        "equity, sem ponte. **Erro comum:** aplicar a ponte da dívida sobre um valuation "
        "por FCFE — a dívida já foi descontada no caminho, e subtraí-la de novo a conta "
        "duas vezes."
    ),
    "wacc": (
        "**WACC** é a média do custo de cada fonte de financiamento, ponderada pela "
        "participação de cada uma. A dívida entra **depois do imposto**, porque juros "
        "são dedutíveis e o governo banca parte da conta. "
        "**Erro comum:** usar a estrutura de capital contábil de hoje em vez da "
        "estrutura-alvo — o WACC deve refletir como a empresa vai se financiar ao longo "
        "da projeção, não como se financiou no passado."
    ),
    "capm": (
        "O **CAPM** diz que o retorno exigido pelo acionista é a taxa livre de risco mais "
        "um prêmio proporcional ao risco não diversificável (o beta). Para empresas em "
        "mercados emergentes soma-se o **prêmio de risco-país**. "
        "**Erro comum:** somar o prêmio de risco americano a uma taxa livre de risco "
        "brasileira — a taxa local já embute inflação e risco soberano, e o resultado "
        "conta risco-país duas vezes."
    ),
    "beta": (
        "O **beta** mede a sensibilidade da ação ao mercado. Beta 1,0 significa que ela "
        "oscila como o índice; 1,5, que amplifica em 50%. Usa-se o beta do **setor** "
        "desalavancado (risco do negócio) e realavanca-se pela estrutura de capital da "
        "**empresa** (risco do acionista). "
        "**Erro comum:** usar o beta de regressão da própria ação — é instável, sensível "
        "à janela escolhida e, em ações pouco líquidas, praticamente ruído."
    ),
    "perpetuidade": (
        "A **perpetuidade** captura todo o valor gerado depois do último ano projetado. "
        "Como costuma responder pela maior parte do valor, ela merece mais atenção do "
        "que a planilha inteira de projeção. O crescimento perpétuo não pode superar o "
        "crescimento nominal da economia: uma empresa que cresce mais que o PIB para "
        "sempre acabaria virando o PIB. "
        "**Erro comum:** crescer para sempre sem reinvestir — crescimento exige capital, "
        "e ignorar isso infla o valor terminal."
    ),
    "roic": (
        "**ROIC** é o retorno que a empresa obtém sobre todo o capital que emprega, "
        "próprio e de terceiros. É a métrica central do valuation porque, comparada ao "
        "WACC, responde a pergunta que importa: **crescer cria ou destrói valor?** Com "
        "ROIC acima do WACC, cada real reinvestido vale mais do que custou. Com ROIC "
        "abaixo, crescer piora a situação — a empresa vale mais distribuindo caixa."
    ),
    "dupont": (
        "A **decomposição de DuPont** abre o ROE em três fontes: **margem** (ganhar por "
        "venda), **giro** (vender muitas vezes sobre o mesmo ativo) e **alavancagem** "
        "(usar dinheiro de terceiros). Duas empresas com ROE idêntico e composição "
        "diferente são negócios diferentes: um varejo vive de giro, um software vive de "
        "margem, e ROE alto vindo só de alavancagem é risco, não qualidade."
    ),
    "reinvestimento": (
        "A **taxa de reinvestimento** é quanto do lucro operacional volta para o negócio "
        "como capex líquido e capital de giro. Ela liga crescimento e retorno pela "
        "relação fundamental **g = taxa de reinvestimento × ROIC**. Se a projeção cresce "
        "sem reinvestir na proporção correta, o modelo está criando valor do nada."
    ),
    "capital_giro": (
        "O **capital de giro** operacional é recebíveis mais estoques menos fornecedores: "
        "o dinheiro preso no ciclo do negócio. Quando a receita cresce, ele cresce junto e "
        "consome caixa — por isso entra como saída no fluxo. "
        "**Erro comum:** incluir caixa e dívida de curto prazo na conta; ambos já estão na "
        "ponte de valor e seriam contados duas vezes."
    ),
    "ponte": (
        "A **ponte** liga o valor da empresa (*Enterprise Value*) ao valor do acionista "
        "(*Equity Value*): tira a dívida, devolve o caixa e ajusta minoritários, "
        "contingências e ativos não operacionais. É onde mora boa parte dos erros de "
        "valuation na prática, porque cada item tem sinal próprio e é fácil trocar."
    ),
    "multiplos": (
        "**Múltiplos** avaliam por comparação: se empresas parecidas valem 8x EBITDA, "
        "esta deveria valer algo próximo. Rápido e ancorado em preço real de mercado, mas "
        "herda o otimismo ou o pessimismo do momento. Múltiplos de **EV** (EV/EBITDA, "
        "EV/Receita) precisam da ponte da dívida; múltiplos de **equity** (P/L, P/VPA) "
        "não. Trocar isso é o erro mais frequente da avaliação relativa."
    ),
    "sensibilidade": (
        "A **tabela de sensibilidade** mostra o valor sob combinações de duas premissas. "
        "Ela existe para uma constatação desconfortável e saudável: o valuation não é um "
        "número, é uma faixa. Quando a tabela abre demais, a resposta honesta ao cliente "
        "é a faixa, não o ponto médio dela."
    ),
    "monte_carlo": (
        "O **Monte Carlo** sorteia milhares de combinações de premissas segundo "
        "distribuições que você declara, e mostra a distribuição do valor. Responde "
        "perguntas que a tabela de sensibilidade não responde, como *qual a chance de o "
        "valor superar o preço pedido*. **Cuidado:** a simulação não cria informação — se "
        "as distribuições forem chutes, a distribuição do resultado também será."
    ),
    "prejuizo_fiscal": (
        "**Prejuízo fiscal acumulado** abate lucro tributável futuro, o que vale dinheiro "
        "real. No Brasil vale indefinidamente no tempo, mas com a **trava dos 30%**: em "
        "cada ano, a compensação não pode reduzir mais que 30% do lucro. Ignorar a trava "
        "superestima o caixa dos primeiros anos — justamente os que mais pesam no valor "
        "presente."
    ),
    "ciclicidade": (
        "Em setores **cíclicos** — commodities, siderurgia, construção — a margem do "
        "último ano diz mais sobre o momento do ciclo do que sobre a empresa. Projetar a "
        "partir dela é apostar que o momento atual é permanente. A normalização substitui "
        "essa margem pela mediana do ciclo observado."
    ),
    "pesquisa_desenvolvimento": (
        "A norma contábil manda lançar **P&D** como despesa, mas economicamente é "
        "investimento: gera benefício por anos. Sem o ajuste, empresas de tecnologia e "
        "farmacêuticas aparecem com lucro e capital investido subestimados — e com ROIC "
        "artificialmente alto, o que distorce justamente a comparação com o WACC."
    ),
}


PASSOS: tuple[tuple[str, str, str], ...] = (
    (
        "Dados",
        "Importe as demonstrações ou preencha à mão",
        "Tudo começa no histórico. Sem ele, as premissas ficam sem âncora.",
    ),
    (
        "Histórico",
        "Entenda o que a empresa entregou",
        "Margens, retorno sobre o capital e reinvestimento dos últimos anos.",
    ),
    (
        "Premissas",
        "Projete o futuro a partir do passado",
        "Crescimento, margem e intensidade de capital, ano a ano.",
    ),
    (
        "Custo de capital",
        "Defina a taxa de desconto",
        "Beta do setor, risco-país e estrutura de capital alvo.",
    ),
    (
        "Valor",
        "Veja o resultado e de onde ele vem",
        "Fluxos descontados, perpetuidade e a ponte até o acionista.",
    ),
    (
        "Sensibilidade",
        "Descubra a faixa, não o ponto",
        "Como o valor reage quando as premissas mudam.",
    ),
    (
        "Múltiplos",
        "Confronte com o mercado",
        "O que empresas comparáveis sugerem para esta.",
    ),
    (
        "Diagnóstico",
        "Deixe o app criticar seu modelo",
        "Verificações de consistência antes de defender o número.",
    ),
    (
        "Exportar",
        "Leve para o Excel",
        "Modelo com fórmulas vivas, pronto para revisão.",
    ),
)


BOAS_VINDAS = """
Este app faz valuation de empresas do começo ao fim: importa as demonstrações
financeiras, analisa o histórico, projeta o futuro, monta o custo de capital,
desconta os fluxos, testa a sensibilidade das premissas e exporta um modelo em
Excel com fórmulas vivas.

Ele foi construído para ser usado de duas formas. Se você já faz valuation,
siga direto pelas telas e use o diagnóstico como checklist final. Se está
aprendendo, leia os blocos azuis: cada tela explica o que está calculando, por
que aquilo afeta o valor e qual é o erro comum naquele ponto.
"""


AVISO_FINAL = (
    "Os números valem o que valem as premissas. Este app automatiza a aritmética, "
    "a documentação e a checagem de consistência do modelo — não o julgamento. "
    "Revise as premissas antes de usar qualquer resultado em decisão de investimento."
)
