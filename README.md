# dbctl

**Um banco Odoo por branch, agnóstico de projeto.**

Num projeto Odoo, todas as branches compartilham o mesmo banco Postgres. O Odoo
aplica mudanças de schema com `-u`, mas **não reverte nada** no `git checkout`:
o banco fica com o schema da última branch que subiu. `dbctl` resolve isso com
um banco (e filestore) por branch, criado por clone de um banco template.

Trocar de branch passa a ser: `git checkout <branch>` + `dbctl use`.

## Instalação

Requisitos: Python >= 3.11, Docker + Docker Compose v2, git. O tool **não**
precisa de `psql` no host nem de acesso direto à porta do Postgres — toda
operação de banco roda via `docker exec` no container do Postgres.

```bash
git clone <seu-repo-do-dbctl> ~/projects/dbctl
cd ~/projects/dbctl
python3 -m venv .venv
.venv/bin/pip install -e .
# (ou com uv: uv venv .venv && uv pip install -e .)
```

Use `.venv/bin/dbctl` (ou adicione ao PATH / crie um alias).

## Injetar um projeto novo (Caso 1)

O projeto precisa: ser um repo git; rodar Postgres e Odoo em containers Docker
com nomes estáveis; ter um `docker-compose.yml` com o serviço do Odoo (o
`command` do serviço deve ser apenas `odoo` — o override do dbctl substitui o
command ao trocar de banco, então flags extras seriam perdidas); e ter um banco
template existente.

1. Copie o exemplo e preencha:

   ```bash
   cp .dbctl.example.toml <projeto>/.dbctl.toml
   # edite: containers, credenciais, template_db, default_modules, seeds
   ```

   O `.dbctl.toml` pode viver **na raiz do repositório** ou **em qualquer
   subpasta** — inclusive numa pasta já ignorada pelo git (ex.: `temp/`), o que
   evita tocar num `.gitignore` versionado. Os caminhos relativos do config
   (`seeds.path`, `compose_file`, `override_file`) são sempre resolvidos a
   partir da **raiz do repositório git**, não da pasta do arquivo.

2. Se colocou na raiz, adicione `.dbctl.toml` (e a pasta de seeds) ao
   `.gitignore` do projeto. Se usou uma pasta já ignorada, este passo some.

3. Confirme:

   ```bash
   cd <projeto>
   dbctl status
   ```

**Descoberta do config (spec 5.0)** — a primeira que resolver vence:

1. `--config PATH` ou `DBCTL_CONFIG` (explícito, ignora a busca);
2. subindo da cwd até o topo do repositório git (`git rev-parse
   --show-toplevel`);
3. descendo do topo, profundidade máxima 3 (podando `.git`, `.venv`,
   `node_modules`, `__pycache__` e diretórios começando com ponto).

Zero resultados → erro 2; **mais de um** → erro 3 listando todos os caminhos
(ambiguidade nunca é resolvida em silêncio — use `--config`). Fora de um
repositório git → erro 4. `-p/--project` força a raiz do projeto quando a
descoberta automática não basta, e pode ser combinado com `--config`.

Todas as chaves do `.dbctl.toml` aceitam override por env var no padrão
`DBCTL_<SEÇÃO>_<CHAVE>` (ex.: `DBCTL_POSTGRES_PASSWORD`). Precedência:
**env var > arquivo > default**.

## Fluxo de trabalho diário

```bash
git checkout -b GC-700-nova-feature
dbctl create --use        # clona o template, copia filestore, sanitiza, roda seeds, serve
dbctl upgrade -m modulo   # aplica -u SÓ no banco desta branch

# alternar entre branches:
git checkout GC-629-...   # o código troca (montado ao vivo no container)
dbctl use                 # o Odoo passa a servir o banco da branch

# banco sujou? recomece:
dbctl reset               # dropa e recria a partir do template (confirmação)

# limpeza:
dbctl list                # bancos do prefixo com tamanho
dbctl drop                # remove banco + filestore (confirmação)
dbctl unuse               # remove o override; o projeto volta à config base
```

## Hook post-checkout (opcional, Caso 3.1)

Quer trocar de branch sem digitar `dbctl use`? Instale o hook uma vez:

```bash
dbctl hook install        # instala .git/hooks/post-checkout (chmod 0755)
dbctl hook status         # path, dono (dbctl/terceiro), enabled
dbctl hook uninstall      # remove SÓ se foi o dbctl que gerou
```

A partir daí, todo `git checkout <branch>` com banco existente roda o `use`
sozinho (`dbctl: serving <db>` no output do git). **Regra de ouro:** o hook
nunca faz o checkout falhar — config ausente, Docker fora do ar, banco
inexistente e HEAD destacado viram avisos `dbctl:` e o checkout sempre
conclui com exit 0.

Para desligar temporariamente sem desinstalar: `[hooks] enabled = false` no
`.dbctl.toml` (ou `DBCTL_HOOKS_ENABLED=0` na sessão). Se já existir um
`post-checkout` de terceiros, o `install` recusa com a linha `exec` para colar
manualmente; `install --force` faz backup como `post-checkout.bak` e sobrescreve.

| Comando | O que faz |
|---|---|
| `status` | Relatório somente-leitura: branch, banco alvo, servido, seed da branch |
| `create [--from T] [--no-seed] [--use]` | Clone do template + filestore + sanitize + seeds |
| `use` | Aponta o serviço para o banco da branch (`-d` + `--db-filter` no override) |
| `unuse` | Remove o `docker-compose.override.yaml` (reversível) |
| `upgrade [-m mod1,mod2] [--all]` | `-u` apenas no banco da branch (default: `odoo.default_modules`) |
| `seed` | Roda `base.py` e `branches/<slug>.py`, se existir |
| `list` | Lista só os bancos com o `db_prefix`, com tamanho e marcações |
| `drop [--yes] [--db NAME]` | Remove banco + filestore; **recusa** nome sem o prefixo |
| `reset [--yes]` | Drop + create com seeds; uma única confirmação |
| `hook install/uninstall/status` | Gerencia o post-checkout (ver seção acima) |

Flags globais: `--verbose` (traceback completo), `--project <caminho>` e
`--config <caminho>`.
`DBCTL_DRY_RUN=1` imprime os comandos sem executar.

## Como o banco da branch é escolhido

`dbctl use` escreve um `docker-compose.override.yaml` na raiz do projeto
(arquivo gitignored, **único** arquivo que o tool escreve no projeto):

```yaml
# GENERATED BY dbctl - DO NOT EDIT
services:
  web:
    command: ["odoo", "-d", "dev_gc_700_abc123", "--db-filter=^dev_gc_700_abc123$"]
```

O `command` substitui o do compose base; o `--db-filter` elimina a tela de
seleção de banco. Apagar o arquivo (ou `dbctl unuse`) devolve o projeto ao
comportamento original. O tool **nunca** edita `odoo.conf` nem `docker-compose.yml`.

## Nomes de banco

`dev_<slug da branch>_<6 hex do sha1 da branch inteira>` — sempre <= 63 chars,
determinístico, começa com o `db_prefix`, e duas branches diferentes nunca
colidem (o digest usa o nome completo, não o slug truncado).

## Seeds

A pasta de seeds (definida em `[seeds].path`) contém **arquivos soltos**, sem
`__init__.py`, que recebem apenas `env` do Odoo — **não importam o dbctl**:

```python
# temp/seeds/base.py — roda sempre
def run(env):
    item = env["meu.modelo"]
    if not item.search_count([("name", "=", "x")]):
        item.create({"name": "x"})   # idempotente!
```

- `base.py` roda em toda branch; `branches/<slug>.py` só na branch correspondente.
- Um seed deve ser **idempotente** (verificar existência antes de criar).
- `dbctl seed` pode rodar quantas vezes quiser.
- A pasta é montada no container efêmero via `-v` explícito — não depende do
  override do compose.

## Sanitize pós-clone

Todo banco clonado passa por `odoo shell` que: gera um `database.uuid` novo e
desativa todos os `ir.mail_server` (um banco de dev nunca deve enviar e-mail
real). `ir.cron` **não** é desativado — decisão deliberada: testar crons é caso
de uso legítimo de dev.

## Segurança

- `db_prefix` (default `dev_`) é a proteção contra dropar banco alheio: o drop
  recusa qualquer nome fora do prefixo, na camada de comando **e** dentro do
  próprio `drop_database` (última linha de defesa).
- O banco template nunca é modificado pelo tool (só clonado).
- A senha do Postgres trafega por env do `docker exec` (API do Docker), nunca
  pela linha de comando do host.

## Resolução de problemas

- **`database 'dev_x_...' already exists`** — o banco da branch já existe; rode
  `dbctl reset` para recriar do template.
- **`database 'dev_x_...' does not exist`** — rode `dbctl create` primeiro.
- **`refusing to drop ...`** — o nome não começa com o `db_prefix`; o tool não
  mexe em bancos que não criou.
- **Clone falhou com "being accessed by other users"** — o Odoo mantinha pool
  aberto no template. O `create` já para o serviço e encerra conexões antes de
  clonar; se persistir, confira se outro processo está conectado ao template.
- **`odoo shell failed ... (seeds)`** — o seed quebrou; a mensagem traz o
  traceback do Odoo e nada foi commitado (sem commit parcial).
- **O serviço subiu com o banco errado** — confira o `docker-compose.override.yaml`
  (`dbctl status` mostra o banco servido) e rode `dbctl use`.
- **Quero voltar ao comportamento original** — `dbctl unuse` remove o override.
