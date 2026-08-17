<!-- docs/specs/11-auto-detect-modules.md — parte do SPEC do dbctl, seções 13.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 13. Detecção automática de módulos alterados (plano: `docs/specs/auto-detect-changed-modules.md`)

### 13.1 Problema

Hoje `dbctl upgrade` sem `-m` cai em `odoo.default_modules`; se a lista estiver vazia,
`ConfigError`. Esquecer um módulo deixa o banco da branch com schema desatualizado. O banco
da branch nasce de um clone do template (que reflete a branch base), então **o que a branch
mudou desde a base é exatamente o que precisa de `-u`**.

Referência do diff: `merge-base` com a branch base (commitado **e** não commitado), sem estado
persistido. Módulo detectado mas não instalado → `-i` em vez de `-u` (consulta
`ir_module_module`). A detecção age em `upgrade` (sem `-m`), `status` (preview, sem executar) e
`create` (banco nasce com o schema da branch). **Não** age no hook `post-checkout` (upgrade
travaria o checkout).

### 13.2 Config — `[modules]`

```toml
[modules]
detect      = true                 # default true; false volta ao comportamento antigo
base_ref    = "origin/main"        # opcional; default = origin/HEAD, depois main/master/develop
manifest    = "__manifest__.py"    # opcional; o que marca a raiz de um módulo
install_new = true                 # opcional; módulo novo -> -i, não -u
ignore      = ["**/static/**"]     # opcional; globs que nunca disparam upgrade
exclude     = ["modulo_quebrado"]  # opcional; nomes de módulo que o dbctl nunca
                                    # aplica sozinho (detecção, --all, default_modules)
```

`exclude` é o escape hatch para um módulo com bug pré-existente e sem relação com a branch
atual (xmlid duplicado, dependência ausente no manifest, view SQL lendo tabela de módulo não
declarado em `depends`, etc.): sem ele, esse módulo trava `upgrade`/`create` de **qualquer**
branch sempre que entra via detecção, `--all` ou `odoo.default_modules`. Um `-m` explícito com
o nome do módulo sempre ignora a exclusão — é escape hatch de projeto, não trava definitiva.

Overrides `DBCTL_MODULES_*` saem de graça pelo padrão `DBCTL_<SEÇÃO>_<CHAVE>`. Booleanos usam o
mesmo parser estrito do `[hooks].enabled` (arquivo: TOML `true`/`false`; env: `1/true/yes/on` e
`0/false/no/off`). Valor não reconhecido → erro apontando a chave.

### 13.3 Módulos

- `project.py` — plumbing de git (via `docker.run`, regra de camadas intacta):
  - `default_base_ref(root, configured=None) -> str` — `[modules].base_ref` → `origin/HEAD` (lido
    com `git for-each-ref --format=%(symref)`, silencioso quando o ref não existe) → primeira entre
    `main`/`master`/`develop`. Nenhuma →
    `ConfigError` pedindo `base_ref`.
  - `merge_base(root, ref) -> str` — `git merge-base HEAD <ref>`. Falha (clone shallow/ref
    inexistente) → `GitError` sugerindo `-m` ou `--no-detect`.
  - `changed_paths(root, since) -> list[str]` — união de `git diff --name-only <since>`
    (commitado + working tree) e `git ls-files --others --exclude-standard` (novos não
    rastreados — como um módulo novo aparece antes do primeiro commit).
- `modules.py` (novo) — mapeamento caminho → módulo:
  - `module_of(path, root, manifest) -> str | None` — sobe dos ancestrais até achar o manifesto;
    o nome do diretório é o módulo. Para no `project_root`. Agnóstico de layout.
  - `detect(cfg) -> dict` — `{base_ref, base_sha, modules, excluded, changed_paths, unmatched}`.
    Aplica os globs de `[modules].ignore` antes do mapeamento; módulo em `[modules].exclude` sai
    de `modules` e entra em `excluded` (nunca aplicado, mas reportado); `unmatched` só aparece
    com `--verbose`.
- `postgres.py` — `_psql_db(cfg, db, sql)` (conecta em `-d <db>`) e
  `installed_modules(cfg, db) -> set[str] | None` (`state = 'installed'`). Tabela ausente →
  `None` = "não sei" → o chamador trata tudo como `-u`. Nunca levanta por causa disso.
- `strategies/` — `upgrade(db, modules, install=None)`; novo método `apply_schema(db, modules,
  install=None)` (roda `odoo -d <db> [-u a,b] [-i c,d] --stop-after-init` **sem** tocar o estado
  do serviço — usado pelo `create`, que já está com o serviço parado). `compose_override` omite a
  flag vazia; `custom` ganha o placeholder `{install}`.
- `commands/upgrade.py` — precedência: `-m` explícito > `--all` > detecção (se `[modules].detect`)
  > `odoo.default_modules` > **nada a fazer, exit 0** ("nenhum módulo mudou" é estado válido).
  Cruza o detectado com `installed_modules` para partir em `-u`/`-i`. `[modules].exclude` é
  subtraído de tudo que o dbctl monta sozinho — inclusive de `default_modules` e de `--all`
  (que vira uma lista explícita via `installed_modules(cfg, db)` minus `exclude`, já que `-u all`
  não tem como pular módulo nenhum; sem tabela `ir_module_module` para consultar, `--all` +
  `exclude` não configurado juntos é `ConfigError`). Nunca se aplica a `-m` explícito.
- `commands/status.py` — campo `changed_modules` (preview; **não** executa nada; falha de detecção
  vira `error` no campo, sem quebrar o status). Inclui `excluded` para transparência.
- `commands/create.py` — depois dos seeds e antes do start final, aplica os módulos detectados
  (`apply_schema`), já descontado `[modules].exclude` tanto da detecção quanto de
  `odoo.default_modules` no caminho fresh. Novo parâmetro `no_upgrade`.
- `cli.py` — `upgrade` ganha `--detect/--no-detect` e imprime o que detectou e por quê
  (`base_ref` + sha) antes de agir; `create` ganha `--no-upgrade`; `status` imprime a linha
  `modules:`.

### 13.4 Casos de borda

| Situação | Comportamento |
|---|---|
| Estou **na** branch base (merge-base == HEAD) | Nada detectado → cai em `default_modules` → no-op com aviso |
| `origin/HEAD` não configurado e sem `main`/`master`/`develop` | `ConfigError` pedindo `[modules].base_ref` |
| Clone shallow (merge-base falha) | `GitError` explicando que falta histórico; sugere `--no-detect` ou `-m` |
| Módulo **deletado** na branch | Caminho não tem mais manifesto → ignorado |
| Arquivo fora de qualquer módulo (`docker-compose.yml`) | Vai para `unmatched`, visível só com `--verbose` |
| Banco sem tabela `ir_module_module` | `installed_modules` devolve `None` → tudo tratado como `-u` |
| HEAD destacado | `GitError` já existente, sem mudança |
| Módulo em `[modules].exclude` mudou nesta branch | Some de `modules`, aparece em `excluded`; nunca upgradado/instalado |
| `odoo.default_modules` inteiramente coberto por `exclude` | `ConfigError` nomeando os módulos, sugerindo `-m` ou editar uma das duas listas |
| `--all` combinado com `[modules].exclude` sem `ir_module_module` no banco | `ConfigError` — não há como enumerar o que existe pra subtrair a exclusão |
| `-m modulo_excluido` | `-m` explícito sempre vence; exclusão não se aplica |

### 13.5 Validação (M1–M13)

| # | Passo | Esperado |
|---|---|---|
| M1 | Na `feature-a` (altera `sandbox_demo`), `dbctl status` | Linha de módulos detectados mostra `sandbox_demo` |
| M2 | `dbctl upgrade` sem `-m` | Detecta e upgrada `sandbox_demo`; imprime base_ref e sha |
| M3 | `dbctl upgrade -m outro_modulo` | `-m` vence a detecção (nenhuma auto-detecção) |
| M4 | `dbctl upgrade --no-detect` sem `default_modules` | Volta a errar como hoje, exit 3 |
| M5 | Editar só `README.md` e rodar `dbctl upgrade` | "nada a atualizar", exit 0, serviço intocado |
| M6 | Criar módulo novo (pasta com `__manifest__.py`) **sem commitar** | Detectado via `ls-files --others`; entra como `-i` |
| M7 | Commitar o módulo e rodar de novo | Continua detectado (diff contra merge-base, não HEAD) |
| M8 | Conferir no banco: módulo novo instalado | `ir_module_module.state = 'installed'` |
| M9 | Estando na `main`, `dbctl upgrade` | Nada detectado; no-op com aviso |
| M10 | `[modules] ignore = ["**/static/**"]`, mexer só em `static/` | Nada detectado |
| M11 | `[modules] detect = false` | Comportamento idêntico ao de hoje |
| M12 | `dbctl create` numa branch com módulo alterado | Banco nasce já com o `-u` aplicado; `--no-upgrade` pula |
| M13 | `DBCTL_DRY_RUN=1 dbctl upgrade` | Imprime os comandos git e docker, sem efeito |
| M14 | `[modules] exclude = ["quebrado"]`, alterar `quebrado` e outro módulo na branch, `dbctl upgrade` | Upgrada só o outro módulo; `excluded: quebrado` na saída |
| M15 | `dbctl upgrade -m quebrado` com o `exclude` de M14 ativo | `-m` explícito vence; `quebrado` é upgradado normalmente |
| M16 | `--all` com `exclude` configurado e banco com `ir_module_module` | Upgrada todos os instalados **exceto** os excluídos (lista explícita, não mais `-u all`) |
| M17 | `--all` com `exclude` configurado num banco fresh (sem `ir_module_module`) | `ConfigError` explicando a falta da tabela |
| M18 | `odoo.default_modules` com todos os módulos também em `exclude`, `dbctl upgrade --no-detect` | `ConfigError` nomeando os módulos cobertos |

Revalidar as invariantes: `grep -rl subprocess dbctl/` devolve **apenas `docker.py`**; dependências
seguem só o Typer.
