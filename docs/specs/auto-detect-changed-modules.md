# Detecção automática de módulos alterados no `dbctl upgrade`

## Contexto

Hoje, para aplicar mudanças de schema o usuário precisa saber e digitar quais módulos mudaram:
`dbctl upgrade -m faturamento`. Sem `-m`, o comando cai em `odoo.default_modules` e, se essa lista
estiver vazia, morre com `ConfigError` (`commands/upgrade.py:24-32`). Isso é fricção diária e é
propenso a erro: esquecer um módulo deixa o banco da branch com schema desatualizado — exatamente o
tipo de drift que o dbctl existe para eliminar.

A ideia é derivar a lista de módulos do próprio git: o banco da branch nasceu de um clone do
`template_db` (que reflete a branch base), então **o que esta branch mudou desde a base é exatamente
o que precisa de `-u`**.

### Decisões tomadas com o usuário
- **Referência do diff:** `merge-base` com a branch base — pega commitado **e** não commitado. Sem
  estado persistido; previsível, ao custo de re-upgradar os mesmos módulos a cada chamada.
- **Módulo detectado mas não instalado** (pasta nova na branch): consulta `ir_module_module` no banco
  da branch e usa `-i` em vez de `-u`. Hoje um `-u` em módulo não instalado é no-op silencioso.
- **Onde a detecção age:** `dbctl upgrade` sem `-m`, `dbctl status` (preview, sem executar) e
  `dbctl create` (banco nasce com o schema da branch). **Não** no hook `post-checkout` — upgrade
  para o serviço e roda container efêmero; travaria todo checkout por dezenas de segundos.

---

## Desenho

Respeita a regra de camadas da spec (§4.1) e a de subprocess concentrado em `docker.py` (§11.7):
o plumbing de git entra em `project.py` (que já é o dono dos helpers de git e já chama `docker.run`),
e o mapeamento caminho → módulo vira um módulo de serviço novo, testável.

### 1. `dbctl/project.py` — plumbing de git (reusa `docker.run`, como as funções atuais)

- `default_base_ref(root) -> str` — cadeia de fallback, agnóstica de projeto:
  `[modules].base_ref` da config → `git symbolic-ref --short refs/remotes/origin/HEAD` → primeira que
  existir entre `main`, `master`, `develop`. Nenhuma encontrada → `ConfigError` pedindo
  `[modules].base_ref` explicitamente.
- `merge_base(root, ref) -> str` — `git merge-base HEAD <ref>`. Falha (clone shallow, ref inexistente)
  → `GitError` com mensagem explicando que a detecção precisa do histórico da base.
- `changed_paths(root, since) -> list[str]` — união de:
  - `git diff --name-only <since>` — commitado na branch **e** working tree (o `git diff <commit>`
    sem segundo argumento já compara contra a árvore de trabalho, incluindo o que está staged);
  - `git ls-files --others --exclude-standard` — arquivos novos não rastreados, que é como um
    **módulo novo** aparece antes do primeiro commit.

### 2. `dbctl/modules.py` — novo, mapeamento caminho → módulo

- `module_of(path, root, manifest) -> str | None` — sobe dos ancestrais do arquivo até achar um
  diretório que contenha o arquivo de manifesto; o nome desse diretório é o módulo. Para no
  `project_root`. É o que torna a detecção agnóstica de layout: funciona com `addons/`,
  `odoo-cotacao/`, monorepo ou qualquer estrutura, sem config de `addons_path`.
- `detect(cfg) -> dict` — orquestra: `default_base_ref` → `merge_base` → `changed_paths` →
  `module_of` de cada um → dedup ordenado. Retorna
  `{base_ref, base_sha, modules, changed_paths, unmatched}` (`unmatched` = arquivos fora de qualquer
  módulo, ex.: `docker-compose.yml` — úteis no `--verbose`, ignorados no resto).
- Aplica os globs de `[modules].ignore` antes do mapeamento.

O manifesto ser **configurável** (`[modules].manifest`, default `__manifest__.py`) é o que deixa a
porta aberta para outras stacks sem código novo — conversa direto com a extensão para além do Odoo
que já discutimos.

### 3. `dbctl/postgres.py` — saber o que está instalado

- `_psql_db(cfg, db, sql)` — variante do `_psql` atual (`postgres.py:31`) que conecta em `-d <db>` em
  vez de `-d postgres`.
- `installed_modules(cfg, db) -> set[str] | None` —
  `SELECT name FROM ir_module_module WHERE state = 'installed'`. Tabela ausente (banco que não é
  Odoo) → retorna `None` = "não sei", e o chamador degrada para tratar tudo como `-u`. Nunca levanta
  por causa disso.

### 4. `dbctl/strategies/` — `-u` e `-i` na mesma passada

- `base.py`: assinatura vira `upgrade(self, db, modules, install=None)`.
- `compose_override.py`: monta `odoo -d <db> [-u a,b] [-i c,d] --stop-after-init`, omitindo a flag
  vazia. Mantém a sequência obrigatória atual (`stop()` → `run --rm` → `start(db)`).
- `custom.py`: novo placeholder `{install}` em `[strategy.commands].upgrade`, ao lado de `{modules}`.

### 5. `dbctl/config.py` — seção `[modules]`

```toml
[modules]
detect      = true                 # default true; false volta ao comportamento atual
base_ref    = "origin/main"        # opcional; default = detecção automática
manifest    = "__manifest__.py"    # opcional; o que marca a raiz de um módulo
install_new = true                 # opcional; módulo detectado e não instalado -> -i
ignore      = ["**/static/**"]     # opcional; globs que não disparam upgrade
```
Novo dataclass `ModulesConfig` + campo em `Config`, seguindo o padrão dos blocos existentes
(overrides `DBCTL_MODULES_*` saem de graça pelo `_env`). Reusar o parser de booleano introduzido
para `[hooks].enabled`.

### 6. Camada de comandos e CLI

- `commands/upgrade.py` — nova precedência, substituindo o `ConfigError` de hoje:
  `-m` explícito > `--all` > detecção (se `[modules].detect`) > `odoo.default_modules` >
  **nada a fazer, exit 0** (não é erro: "nenhum módulo mudou" é um estado válido e comum).
  Cruza o detectado com `installed_modules` para partir em `-u` e `-i`.
- `commands/status.py` — campo novo `changed_modules` (preview; **não** executa nada, preservando
  a garantia de `status` ser sempre livre de efeito colateral).
- `commands/create.py` — depois dos seeds e antes do `start` final, aplica os módulos detectados.
  Novo parâmetro `no_upgrade` para pular.
- `cli.py` — `upgrade` ganha `--detect/--no-detect` e imprime o que detectou e por quê (`base_ref` +
  sha) antes de agir; `create` ganha `--no-upgrade`; `status` imprime a linha nova.

**Arquivos tocados:** `dbctl/project.py`, `dbctl/modules.py` (novo), `dbctl/postgres.py`,
`dbctl/config.py`, `dbctl/strategies/{base,compose_override,custom}.py`,
`dbctl/commands/{upgrade,status,create}.py`, `dbctl/cli.py`, `.dbctl.example.toml`, `README.md`,
`docs/specs/` (arquitetura, configuração, módulos, casos de uso, validação).

---

## Casos de borda a tratar explicitamente

| Situação | Comportamento |
|---|---|
| Estou **na** branch base (merge-base == HEAD) | Nada detectado → cai em `default_modules` → no-op com aviso |
| `origin/HEAD` não configurado e sem `main`/`master`/`develop` | `ConfigError` pedindo `[modules].base_ref` |
| Clone shallow (merge-base falha) | `GitError` explicando que falta histórico; sugere `--no-detect` ou `-m` |
| Módulo **deletado** na branch | Caminho não tem mais manifesto → ignorado (não dá para upgradar o que não existe) |
| Arquivo fora de qualquer módulo (`docker-compose.yml`) | Vai para `unmatched`, visível só com `--verbose` |
| Banco sem tabela `ir_module_module` | `installed_modules` devolve `None` → tudo tratado como `-u` |
| HEAD destacado | `GitError` já existente, sem mudança |

---

## Verificação (manual, no sandbox da [validação](09-validacao.md) da spec)

| # | Passo | Esperado |
|---|---|---|
| M1 | Na `feature-a` (que altera `sandbox_demo`), `dbctl status` | Linha de módulos detectados mostra `sandbox_demo` |
| M2 | `dbctl upgrade` sem `-m` | Detecta e upgrada `sandbox_demo`; imprime base_ref e sha usados |
| M3 | `dbctl upgrade -m outro_modulo` | `-m` vence a detecção (nenhuma auto-detecção acontece) |
| M4 | `dbctl upgrade --no-detect` sem `default_modules` | Volta a errar como hoje, exit 3 |
| M5 | Editar só `README.md` do sandbox e rodar `dbctl upgrade` | "nada a atualizar", exit 0, serviço intocado |
| M6 | Criar módulo novo (pasta com `__manifest__.py`) **sem commitar** | Detectado via `ls-files --others`; entra como `-i`, não `-u` |
| M7 | Commitar esse módulo e rodar de novo | Continua detectado (o diff é contra merge-base, não contra HEAD) |
| M8 | Conferir no banco: módulo novo instalado | `ir_module_module.state = 'installed'` |
| M9 | Estando na `main`, `dbctl upgrade` | Nada detectado; no-op com aviso |
| M10 | `[modules] ignore = ["**/static/**"]`, mexer só em `static/` | Nada detectado |
| M11 | `[modules] detect = false` | Comportamento idêntico ao de hoje |
| M12 | `dbctl create` numa branch com módulo alterado | Banco nasce já com o `-u` aplicado; `--no-upgrade` pula |
| M13 | `DBCTL_DRY_RUN=1 dbctl upgrade` | Imprime os comandos git e docker, sem efeito |

Revalidar as invariantes da [avaliação](10-avaliacao.md) da spec: `grep -rl subprocess dbctl/` continua devolvendo **apenas
`docker.py`**, e as dependências seguem só o Typer.

> `docs/specs/` (arquitetura, configuração, módulos, casos de uso, validação) e `README.md` entram junto, no mesmo padrão das outras
> features. Se você preferir specar primeiro e implementar depois — como fizemos com o hook — é só
> dizer que eu escrevo só a spec.
