# dbctl — Specs

Especificação do `dbctl` dividida por tópico (antes: um único documento na
raiz do repositório). A numeração das seções foi preservada — cada arquivo
mantém os cabeçalhos `## N.` do documento original, então referências
internas antigas (`seção 5.0`, `§10`, ...) continuam rastreáveis.

## Ordem de leitura

1. [01-problema.md](01-problema.md) — Problema + Glossário (seções 1–2)
2. [02-pre-requisitos.md](02-pre-requisitos.md) — Pré-requisitos (seção 3)
3. [03-arquitetura.md](03-arquitetura.md) — Arquitetura e estrutura de arquivos (seção 4)
4. [04-configuracao.md](04-configuracao.md) — `.dbctl.toml`, localização e validação (seção 5)
5. [05-modulos.md](05-modulos.md) — Especificação de cada arquivo/módulo do tool (seção 6)
6. [06-casos-de-uso.md](06-casos-de-uso.md) — Casos de uso e fluxos, comando a comando (seção 7)
7. [07-sandbox.md](07-sandbox.md) — Entregável 2: projeto sandbox (seção 8)
8. [08-execucao.md](08-execucao.md) — Plano de execução E1–E5 (seção 9)
9. [09-validacao.md](09-validacao.md) — Plano de validação V/C/H/M (seção 10)
10. [10-avaliacao.md](10-avaliacao.md) — Critérios de avaliação + fora de escopo (seções 11–12)
11. [11-auto-detect-modules.md](11-auto-detect-modules.md) — Detecção automática de módulos (seção 13)
12. [auto-detect-changed-modules.md](auto-detect-changed-modules.md) — Plano de design da detecção (histórico de decisões)

## Convenções

- **Idioma:** prosa em português; código, nomes de arquivo, funções,
  variáveis, comandos de CLI e mensagens de log em inglês.
- **Escopo:** MVP — só o essencial e funcional. O que estiver em
  [fora de escopo](10-avaliacao.md) não deve ser feito.
- **Invariantes verificáveis:** `subprocess` apenas em `docker.py`; dependência
  apenas Typer; zero menção a projetos reais no código do tool.
