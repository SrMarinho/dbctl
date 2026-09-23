"""Auto-seed generator - runs INSIDE `odoo shell`, never imported by dbctl.

seeding.py reads this file as text, appends a `run_auto(env, ...)` call and
pipes it to the ephemeral shell. It only needs stdlib + the Odoo `env`.

For every concrete model defined by one of the repo's modules it tops the
table up to ``count`` records, filling each writable field with a trivial
value derived from its type. Each model runs in its own savepoint: a
constraint that rejects the fake values skips only that model.
"""

import datetime
from typing import Any

MARK_OK = "DBCTL_AUTOSEED:"
MARK_SKIP = "DBCTL_AUTOSEED_SKIP:"

# ponytail: sequential dummy values; format constraints (tax ids, regexes)
# make the model skip - cover it with a manual seed or [seeds].auto_exclude.
_MAGIC = {"id", "display_name", "create_uid", "create_date", "write_uid", "write_date"}
_SKIP_TYPES = {
    "one2many",
    "many2many",
    "binary",
    "reference",
    "properties",
    "json",
    "many2one_reference",
}


def _value(env: Any, field: Any, i: int, pick: Any) -> Any:
    kind = field.type
    if kind in ("char", "text", "html"):
        return f"{field.string} {i}"
    if kind == "integer":
        return i
    if kind in ("float", "monetary"):
        return i * 1.5
    if kind == "boolean":
        return i % 2 == 0
    if kind == "date":
        return datetime.date.today() + datetime.timedelta(days=i)
    if kind == "datetime":
        return datetime.datetime.now().replace(microsecond=0) + datetime.timedelta(days=i)
    if kind == "selection":
        options = field.get_values(env)
        return options[i % len(options)] if options else None
    if kind == "many2one":
        return pick(field.comodel_name, i)
    return None


def run_auto(env: Any, modules: list[str], count: int, exclude: list[str]) -> None:
    env = env(
        context=dict(env.context, tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
    )
    wanted = set(modules)
    targets: set[str] = set()
    for name in env.registry:
        model = env[name]
        if (
            getattr(model, "_original_module", None) in wanted
            and not model._abstract
            and not model._transient
            and model._auto
            and name not in exclude
        ):
            targets.add(name)

    done: set[str] = set()
    visiting: set[str] = set()

    def pick(comodel: str, i: int) -> int | None:
        if comodel in targets:
            seed(comodel)
        records = env[comodel].search([], limit=count)
        return records[i % len(records)].id if records else None

    def seed(name: str) -> None:
        if name in done or name in visiting:
            return
        visiting.add(name)
        model = env[name]
        existing = model.search_count([])
        missing = count - existing
        if missing <= 0:
            visiting.discard(name)
            done.add(name)
            return
        fields: dict[str, Any] = {}
        for fname, field in model._fields.items():
            inherited = getattr(field, "inherited", False)
            if fname in _MAGIC or field.type in _SKIP_TYPES or getattr(field, "delegate", False):
                continue
            if not inherited and (not field.store or field.compute or field.related):
                continue
            if field.readonly and not field.required:
                continue
            fields[fname] = field
        # A field with a working default keeps it; one whose default crashes
        # outside a UI context (e.g. needs active_id) gets a generated value.
        defaults: set[str] = set()
        for fname in fields:
            try:
                if model.default_get([fname]):
                    defaults.add(fname)
            except Exception:
                pass
        try:
            with env.cr.savepoint():
                for n in range(missing):
                    i = existing + n + 1
                    # one by one: custom computes/constraints often assume a singleton
                    model.create(
                        {
                            fname: value
                            for fname, field in fields.items()
                            if fname not in defaults
                            and (value := _value(env, field, i, pick)) is not None
                        }
                    )
            print(f"{MARK_OK}{name}:{missing}")
        except Exception as exc:
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
            print(f"{MARK_SKIP}{name}:{type(exc).__name__}: {first}")
        visiting.discard(name)
        done.add(name)

    for name in sorted(targets):
        seed(name)
