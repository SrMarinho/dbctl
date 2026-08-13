<!-- docs/specs/01-problema.md — parte do SPEC do dbctl, seções 1–2.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 1. Problema

Num projeto Odoo, todas as branches compartilham o mesmo banco Postgres. O Odoo aplica mudanças de
schema no banco quando roda com `-u` (upgrade de módulo), mas **não reverte nada** quando você faz
`git checkout` para outra branch. O banco fica com o schema da última branch que subiu.

Ao voltar para outra branch, o código espera campos/views/ações que o banco não tem — ou convive com
colunas e registros de `ir.model.data` deixados por uma feature que não existe mais no código atual.
O resultado é erro na subida do Odoo ou comportamento inconsistente.

Exemplo real no projeto que motivou isto (`credsus`): a branch `GC-629` adicionou o campo `url_sei` ao
model `faturamento.fatura` e criou dois registros `mail.template`. Qualquer outra branch passa a
carregar esse resíduo.

**Solução:** um banco (e um filestore) por branch, criado por clone de um banco template. Trocar de
branch passa a ser `git checkout` + apontar o Odoo para o banco daquela branch.

**Decisão registrada — por que não git worktrees:** worktree resolve ter vários *códigos* checkoutados
simultaneamente; não resolve drift de schema (várias worktrees apontando ao mesmo banco reproduzem o
erro idêntico). Só valeria para rodar duas branches ao mesmo tempo, o que não é requisito, e custaria
container, porta e filestore por worktree. **Não implementar worktrees.**

---

## 2. Glossário

| Termo | Significado |
|---|---|
| **tool** | O `dbctl` em si, em `~/projects/dbctl`. Agnóstico, não conhece nenhum projeto. |
| **projeto injetado** | Qualquer projeto Odoo (repositório git) que tenha um `.dbctl.toml` em algum lugar da árvore. |
| **template DB** | Banco de origem do clone (ex.: `greencompras_local`). Nunca é modificado. |
| **branch DB** | Banco derivado, pertencente a uma branch. Sempre começa com o `db_prefix`. |
| **filestore** | Diretório de anexos do Odoo, um por banco, dentro do container (`<data_dir>/filestore/<db>`). |
| **seed** | Arquivo Python com uma função `run(env)` que popula dados via ORM do Odoo. |
| **slug** | Nome da branch normalizado para caber em identificador Postgres. |

---
