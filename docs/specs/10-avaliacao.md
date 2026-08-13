<!-- docs/specs/10-avaliacao.md — parte do SPEC do dbctl, seções 11–12.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 11. Critérios de avaliação

Usados para validar o trabalho entregue. Um item não atendido é uma correção obrigatória.

### Bloqueantes (reprovam a entrega)
1. **Isolamento comprovado:** V20–V24 passam integralmente.
2. **Nenhum dado perdido:** nenhum comando é capaz de dropar banco sem o prefixo (V18) nem tocar no
   template. `drop_database` valida o prefixo internamente, além da checagem na camada de comando.
3. **Agnosticismo:** V35 retorna zero ocorrências e V36 passa.
4. **Seeds desacoplados:** seeds não importam o `dbctl` e funcionam como arquivos soltos (V30).
5. **Sem edição de arquivo versionado do projeto injetado:** o tool só escreve o `override_file`
   (gitignored) e o `post-checkout` (não versionado — vive em `.git/hooks/` ou no `core.hooksPath`
   customizado). Em particular, **jamais** edita `config/odoo.conf` ou `docker-compose.yml`.
6. **Erros tratados:** todo erro esperado sai com mensagem legível e exit code da tabela de `errors.py`
   — nunca traceback cru (V2, V3, V4, V6, V12).

### Qualidade (avaliados, mas não bloqueiam)
7. **Fronteiras de módulo:** `cli.py` sem regra de negócio; nenhum módulo além de `docker.py` chama
   `subprocess`; camadas de baixo não importam de cima.
8. **Idempotência:** `seed` repetido não duplica dados; `use` repetido é inofensivo.
9. **Reversibilidade:** apagar o `override_file` devolve o projeto ao comportamento original.
10. **Legibilidade do output:** `status` e `list` são compreensíveis sem consultar a documentação.
11. **README suficiente:** um colega consegue instalar, injetar um projeto e rodar o fluxo diário só
    com o README, sem ler o código.
12. **Sem dependências além do Typer:** biblioteca padrão para o resto (`tomllib` já está no Python
    ≥ 3.11).

### Verificação rápida para o revisor
```
# agnosticismo
grep -riE "credsus|greencompras|foo-user|green-compras" ~/projects/dbctl/dbctl/ ; echo "esperado: vazio"

# subprocess concentrado
grep -rl "subprocess" ~/projects/dbctl/dbctl/ ; echo "esperado: apenas docker.py"

# dependências
grep -A5 "dependencies" ~/projects/dbctl/pyproject.toml ; echo "esperado: apenas typer"
```

---

## 12. Fora de escopo (não implementar)

- Git worktrees, ou rodar duas branches simultaneamente.
- Drivers adicionais de estratégia além de `compose-override` e do escape hatch `custom`.
- Migração/backfill de dados entre bancos de branches diferentes.
- Interface web, TUI ou empacotamento para PyPI.
- Suporte a Postgres fora de container.
- Testes automatizados do tool (a validação do MVP é o plano manual da [validação](09-validacao.md)) — se sobrar tempo,
  testes unitários de `naming.py` e `config.py` são o melhor investimento, por serem lógica pura.

---
