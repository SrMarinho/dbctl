<!-- docs/specs/06-casos-de-uso.md — parte do SPEC do dbctl, seções 7.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 7. Casos de uso e fluxos

### Caso 1 — Injetar um projeto novo
**Ator:** desenvolvedor com um projeto Odoo ainda não gerenciado.
1. Copia `.dbctl.example.toml` como `.dbctl.toml`, na raiz do projeto **ou** dentro de uma pasta já
   ignorada pelo git (ver [arquitetura](03-arquitetura.md) e [configuração](04-configuracao.md)) — a segunda opção evita mexer em `.gitignore` versionado.
2. Preenche containers, credenciais e — **opcionalmente** — o template DB. Sem template, o
   `create` faz bancos novos (vazios) por branch.
3. Se optou pela raiz, adiciona `.dbctl.toml` e a pasta de seeds ao `.gitignore` do projeto (o exemplo
   deve trazer essa instrução comentada no topo). Se colocou numa pasta já ignorada, este passo some.
4. `dbctl status` → confirma que o projeto foi detectado, mostra qual `.dbctl.toml` foi usado
   (`config:`) e o banco alvo da branch atual.

**Critério:** nenhum arquivo versionado do projeto precisou ser alterado — nem o `.gitignore`, se o
config foi colocado numa pasta já ignorada.

### Caso 2 — Começar a trabalhar numa branch nova
1. `git checkout -b GC-700-nova-feature`
2. `dbctl create` — sem template no config: cria um banco **novo** (vazio) e inicializa com
   `base` + `default_modules` + módulos alterados da branch; com `template_db`/`--from`: clona,
   copia filestore, sanitiza. Nos dois casos roda seeds.
3. `dbctl use` — o Odoo passa a servir o banco dessa branch.
4. `dbctl upgrade -m modulo_alterado` — aplica mudanças de schema **só nesse banco**.

### Caso 3 — Alternar entre branches (o fluxo que resolve o problema)
1. `git checkout GC-629-...` → `dbctl use`
2. Trabalha, roda `dbctl upgrade` quando muda model.
3. `git checkout GC-723-hotfix...` → `dbctl use`
4. O Odoo sobe **sem erro**, porque o banco dessa branch nunca viu as mudanças da GC-629.
5. Voltar para a GC-629 → `dbctl use` → o banco anterior está intacto.

### Caso 3.1 — Alternar entre branches sem lembrar do `dbctl use`
1. `dbctl hook install` — uma vez só, instala o `post-checkout`.
2. `git checkout GC-629-...` — o hook chama `dbctl use` sozinho; Odoo já sobe no banco certo.
3. `git checkout GC-723-hotfix...` — idem, sem digitar `dbctl use`.
4. Se a branch nova ainda não tem banco, o hook só avisa (`dbctl create --use` primeiro) — o checkout
   nunca é bloqueado nem o tool cria banco sozinho durante um checkout.
5. Para desligar temporariamente sem desinstalar: `[hooks] enabled = false` no `.dbctl.toml`, ou
   `DBCTL_HOOKS_ENABLED=0` na sessão do shell.

### Caso 4 — Banco sujou, recomeçar
`dbctl reset` — dropa e recria a partir do template, quando configurado; sem template, recria do
zero (banco novo vazio). Com seeds. Uma confirmação, a não ser com `--yes`.

### Caso 5 — Dados específicos da branch
1. Cria `<seeds_path>/branches/<slug>.py` com uma função `run(env)` idempotente.
2. `dbctl seed` — roda `base.py` e depois o arquivo da branch.
3. `dbctl status` mostra qual arquivo de seed foi detectado para a branch atual.

### Caso 6 — Limpeza
1. `dbctl list` — mostra todos os bancos do prefixo com tamanho.
2. `dbctl drop` na branch já mergeada — remove banco e filestore, com confirmação.

### 7.1 Especificação comando a comando

Para cada comando: pré-condições verificadas **antes** de qualquer efeito colateral, passos, saída e
falhas esperadas.

#### `dbctl status`
- **Pré:** projeto encontrado, config válida, repo git.
- **Passos:** resolve branch → nome do banco → checa existência → lê `current_database()` da estratégia
  → detecta se há seed de branch → lê `hook.info(cfg)`.
- **Saída:** projeto (caminho da raiz), **config (caminho do `.dbctl.toml` em uso)**, branch, banco
  alvo, existe (sim/não), banco servido agora, template (ou "none (fresh create)" quando não
  configurado), seed da branch detectado (caminho ou "nenhum"), **hook** (`installed, enabled` /
  `installed, disabled` / `not installed`).
- **Aviso opcional:** se `git status --porcelain` do projeto não estiver vazio, uma linha `warning:
  working tree has uncommitted changes` — o banco da branch pode não ter o schema do código ainda não
  commitado. Só aviso, nunca bloqueia.
- **Efeito colateral:** nenhum. Este comando é sempre seguro.

#### `dbctl create [--from TEMPLATE] [--no-seed] [--use] [--no-upgrade]`
- **Pré:** banco alvo **não** existe (senão erro sugerindo `reset`); se houver template (config ou
  `--from`), ele existe; containers Postgres e do serviço Odoo conhecidos.
- **Dois caminhos, um fluxo:**
  - **Clone (template configurado ou `--from`):** `strategy.stop()` (o Postgres exige **zero
    conexões** no template para clonar, e o Odoo mantém pool aberto) → `terminate_connections(template)`
    → `clone_database(template → alvo)` → `filestore.copy` → `sanitize(alvo)`.
  - **Fresh (sem template):** `strategy.stop()` → `create_database(alvo)` — `CREATE DATABASE` vazio,
    sem `TEMPLATE`; **não** há filestore para copiar nem o que sanitizar.
- Depois, nos dois casos:
  1. schema da branch — no clone, `-u`/`-i` dos módulos detectados; no fresh, `-i
     base[,default_modules][,detectados]` (um banco vazio não tem nada para `-u`);
  2. `run_seeds(alvo)`, salvo `--no-seed` — roda **depois** do schema (seeds precisam das tabelas do
     Odoo; no clone o schema já existe); monta a pasta de seeds via `-v` explícito, sem depender do
     override (que só é escrito no passo 3);
  3. se `--use`, `strategy.start(alvo)`; senão, restaura o serviço no banco em que estava antes.
- **Falhas:** se a criação/clone falhar no meio, o comando deve tentar remover o banco parcial antes
  de propagar o erro, para não deixar estado sujo.

#### `dbctl use`
- **Pré:** banco da branch existe (senão erro sugerindo `create`).
- **Passos:** `strategy.start(db)`.
- **Saída:** banco servido e URL de acesso.

#### `dbctl unuse`
- **Pré:** nenhum.
- **Passos:** remove o `override_file`, se existir.
- **Saída:** confirma a remoção e avisa que o próximo `docker compose up` usa a config base do projeto
  (comportamento original). Não derruba o serviço: se o container estiver no ar com o banco da branch,
  ele continua servindo até ser recriado sem o override.
- **Efeito colateral:** apenas a remoção do arquivo gitignored. É o contraponto explícito do `use` e o
  caminho sancionado para a reversibilidade (critério 9).

#### `dbctl upgrade [-m mod1,mod2] [--all]`
- **Pré:** banco existe. Sem `-m`, usa `odoo.default_modules`; se este estiver vazio, erro pedindo
  `-m`. `--all` usa `-u all`.
- **Passos:** `strategy.upgrade(db, modules)` (stop → run efêmero com `--stop-after-init` → start).

#### `dbctl seed`
- **Pré:** banco existe; `seeds.path` configurado e existente (senão, aviso e saída 0).
- **Passos:** `run_seeds(db, branch)`.
- **Saída:** quais arquivos rodaram.

#### `dbctl list`
- **Saída:** tabela com nome, tamanho e marcação de qual é o da branch atual e qual está sendo servido.
- Lista **apenas** bancos com o `db_prefix`.

#### `dbctl drop [--yes] [--db NAME]`
- **Pré:** nome começa com o prefixo (recusa qualquer outro, inclusive via `--db`).
- **Passos:** confirmação interativa (a menos de `--yes`) → `stop()` se o banco estiver sendo servido →
  `drop_database` → `filestore.remove`.

#### `dbctl reset [--yes]`
- Equivale a `drop --yes` (se existir) seguido de `create`. Uma única confirmação no início.

#### `dbctl hook install [--force]`
- **Pré:** projeto é um repo git (sempre é, ver [pré-requisitos](02-pre-requisitos.md)).
- **Passos:** `hook.install(cfg, force=...)`.
- **Saída:** caminho do hook instalado, ou erro explicando `--force` e mostrando a linha `exec` para
  colar manualmente, se já existir um `post-checkout` de terceiros.

#### `dbctl hook uninstall`
- **Passos:** `hook.uninstall(cfg)`.
- **Saída:** confirma a remoção, ou avisa que não havia hook nosso instalado. Nunca remove hook de
  terceiros.

#### `dbctl hook status`
- **Efeito colateral:** nenhum.
- **Saída:** caminho do hook, se está instalado, se é nosso (`ours`) e se está habilitado
  (`hooks.enabled`).

#### `dbctl hook post-checkout <prev> <new> <branch_flag>` (oculto, chamado pelo git)
- **Não é para uso manual** — é o comando que o script gerado por `hook install` invoca a cada
  `post-checkout`. Recebe os três argumentos padrão do hook do git.
- **Passos:** `hook.on_checkout(cfg, prev, new, branch_flag)` — ordem de decisão:
  1. `branch_flag != "1"` → nada (checkout de arquivo);
  2. `hooks.enabled = false` → nada;
  3. HEAD destacado → aviso `dbctl: detached HEAD ...` (rebase/bisect) e para — **nunca stasheia**;
  4. `hooks.stash_dirty` (default true) e working tree sujo → `git stash push -u -m "dbctl-wip <prev> <data>"`
     e avisa `dbctl: working tree sujo ... guardadas em stash ...` — a rede de segurança contra perda
     de código; o tree chega limpo na branch nova;
  5. já servindo o alvo → aviso `already serving <db>`;
  6. banco do alvo inexistente → aviso sugerindo `dbctl create --use`;
  7. senão → delega ao `use` (nunca reimplementa o override).
- **Saída:** as linhas retornadas, prefixadas com `dbctl:`, em stderr.
- **Sempre sai 0** — ver a regra de ouro em `commands/hook.py` ([módulos](05-modulos.md)). Nenhum cenário de erro pode
  fazer o `git checkout` do usuário falhar.

---
