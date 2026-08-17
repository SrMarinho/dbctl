<!-- docs/specs/04-configuracao.md — parte do SPEC do dbctl, seções 5.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 5. Especificação de configuração

### 5.0 Localização do arquivo `.dbctl.toml`

O `.dbctl.toml` **não** precisa estar na raiz do projeto. A raiz do projeto (`project_root`) e o
arquivo de config (`path`) são dois conceitos distintos:

- **`project_root`** = topo do repositório git, via `git rev-parse --show-toplevel`. É a base de todo
  caminho relativo do config (`seeds.path`, `odoo.compose_file`, `strategy.override_file`) e a cwd do
  `docker compose`. Fora de um repo git → `GitError` (exit 4).
- **`path`** = o arquivo `.dbctl.toml` em si, em qualquer lugar dentro do repositório.

Ordem de descoberta (a primeira que resolver vence):

1. **`--config PATH`** (flag global) ou **`DBCTL_CONFIG`** (env var). Explícito, ignora toda busca;
   caminho inexistente → `ConfigError`.
2. **Subindo da cwd** até o topo do repositório, procurando `.dbctl.toml` — comportamento de sempre,
   preservado como caso comum (arquivo na raiz ou numa pasta acima da cwd).
3. **Descendo do topo do repositório**, com profundidade máxima 3 e poda de `.git`, `.venv`,
   `node_modules`, `__pycache__` e diretórios começando com ponto.
   - Nenhum `.dbctl.toml` encontrado → `ProjectNotFoundError` (exit 2), mencionando `--config` /
     `DBCTL_CONFIG` como alternativas.
   - **Mais de um encontrado → `ConfigError` (exit 3)** listando todos os caminhos e pedindo para
     escolher com `--config`. Ambiguidade nunca é resolvida em silêncio — o banco que o Odoo serve
     depende de qual arquivo é lido.

A flag `-p/--project` continua existindo e passa a significar "raiz do projeto" (para quando a
descoberta automática do repo git não é suficiente); pode ser combinada com `--config`.

### 5.1 Arquivo `.dbctl.toml`

```toml
[postgres]
container   = "db-green-compras-local"   # obrigatório
user        = "foo-user"                 # obrigatório
password    = "foo-pass"                 # opcional se DBCTL_PG_PASSWORD estiver setado
# template_db = "greencompras_local"     # OPCIONAL: clona um banco existente no
                                        # `create`; ausente = cria banco NOVO (vazio)
                                        # por branch, inicializado com base +
                                        # default_modules + módulos da branch
db_prefix   = "dev_"                     # opcional, default "dev_"

[odoo]
container       = "green-compras-local"  # obrigatório
compose_service = "web"                  # obrigatório
compose_file    = "docker-compose.yml"   # opcional, default "docker-compose.yml"
data_dir        = "/var/lib/odoo"         # opcional, default "/var/lib/odoo"
default_modules = ["faturamento"]         # opcional, usado pelo `upgrade` sem -m

[seeds]
path  = "temp/seeds"                     # opcional; se ausente, comando `seed` é no-op avisando
mount = "/mnt/dbctl-seeds"               # opcional, default "/mnt/dbctl-seeds"

[strategy]
kind          = "compose-override"       # "compose-override" | "custom"
override_file = "docker-compose.override.yaml"   # só para compose-override

[hooks]
enabled = true                           # opcional, default true; false desliga o post-checkout
                                          # sem desinstalá-lo (ver [casos de uso](06-casos-de-uso.md), `dbctl hook`)
stash_dirty = true                       # opcional, default true; no checkout com working tree sujo,
                                          # guarda as mudanças num stash 'dbctl-wip <prev> <data>'
                                          # (recuperar com `git stash pop`); false deixa o tree como está

# Escape hatch — só quando kind = "custom".
# Placeholders disponíveis: {db}, {modules}, {project_root}
# [strategy.commands]
# start   = "..."
# stop    = "..."
# upgrade = "..."
# shell   = "..."
```

### 5.2 Regras de validação da config

O `config.py` deve falhar **antes** de qualquer efeito colateral, com mensagem apontando a chave
problemática e o caminho do arquivo:

1. Chaves obrigatórias ausentes → erro listando todas de uma vez (não uma por vez).
2. `strategy.kind` fora do conjunto permitido → erro listando os valores válidos.
3. `strategy.kind = "custom"` sem `[strategy.commands].start`/`stop` → erro.
4. `postgres.password` ausente **e** `DBCTL_PG_PASSWORD` ausente → erro.
5. `seeds.path` apontando para diretório inexistente → **aviso**, não erro (o projeto pode ainda não
   ter seeds).
6. `db_prefix` vazio ou que não case com `^[a-z][a-z0-9_]*$` → erro (o prefixo é a proteção contra
   dropar banco alheio).
7. `seeds.path` é resolvido para **caminho absoluto** no carregamento (base: a raiz do **repositório
   git**, não a pasta onde o `.dbctl.toml` está — ver [configuração](04-configuracao.md)). É esse caminho absoluto que vai no `-v` do
   `compose run` do seed — `compose run -v` exige caminho absoluto do host.
8. `hooks.enabled` aceita apenas os literais booleanos reconhecidos (arquivo: `true`/`false` do TOML;
   env var: `1/true/yes/on` e `0/false/no/off`, case-insensitive). Valor não reconhecido → erro
   apontando a chave. Bloco `[hooks]` ausente é equivalente a `enabled = true`.
9. `hooks.stash_dirty` segue as mesmas regras booleanas (default `true`). Quando ativo, o
   `post-checkout` guarda num stash nomeado (`dbctl-wip <prev> <data>`, com `-u`) qualquer mudança
   não commitada do working tree — a rede de segurança contra perda de código ao trocar de branch.
   Nunca roda com HEAD destacado (rebase/bisect).
10. `postgres.template_db` é **opcional**. Ausente (ou vazio), `create`/`reset` criam um banco
    **novo** (vazio), inicializado com `base` + `odoo.default_modules` + módulos alterados da branch;
    presente (ou `--from` no `create`), o banco é clonado do template (filestore + sanitize + seeds).
    O clone é sempre opt-in — nunca obrigatório.

### 5.3 Overrides por variável de ambiente

Todas as chaves aceitam override por env var no padrão `DBCTL_<SEÇÃO>_<CHAVE>` em maiúsculas
(ex.: `DBCTL_POSTGRES_PASSWORD`, `DBCTL_ODOO_CONTAINER`, `DBCTL_HOOKS_ENABLED`). Precedência:
**env var > arquivo > default**.

Duas variáveis adicionais, fora do padrão `DBCTL_<SEÇÃO>_<CHAVE>` por não pertencerem a nenhuma seção
do TOML — controlam a própria descoberta do arquivo (ver [configuração](04-configuracao.md)):
- `DBCTL_CONFIG` — caminho explícito do `.dbctl.toml`, equivalente à flag `--config`.
- `DBCTL_DRY_RUN` — já documentado em `docker.py` ([módulos](05-modulos.md)).

---
