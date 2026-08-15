"""Excecoes do projeto.

A distincao que importa aqui e entre dois tipos de erro que o Python trataria
igual:

* ``CombinacaoInviavel`` -- as premissas sao validas individualmente, mas juntas
  descrevem uma empresa impossivel (crescer para sempre acima da taxa de
  desconto, por exemplo). Em sensibilidade e Monte Carlo isso e esperado: a
  celula vira vazia, a rodada e descartada.
* Qualquer outro ``ValueError`` -- o modelo esta mal configurado (nome de
  premissa digitado errado, metrica inexistente). Isso **nao** pode virar celula
  vazia: uma tabela inteira de ``NaN`` por causa de um typo e o pior desfecho
  possivel, porque parece resultado.
"""

from __future__ import annotations


class CombinacaoInviavel(ValueError):
    """Premissas validas isoladamente, mas economicamente impossiveis juntas."""
