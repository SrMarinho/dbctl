"""Post-clone neutralization, run right after the template clone.

Executed through the same `odoo shell` channel as seeds (seeding.run_python),
so it works before the compose override exists.
"""

from __future__ import annotations

from dbctl.config import Config
from dbctl.seeding import run_python

_SANITIZE_CODE = """import uuid

env["ir.config_parameter"].set_param("database.uuid", str(uuid.uuid4()))
mail_servers = env["ir.mail_server"].search([])
if mail_servers:
    mail_servers.write({"active": False})

# Deliberate decision: ir.cron is NOT deactivated.
# Testing crons is a legitimate dev use case; branch databases keep the
# template's crons active so they behave like the real instance. Only the
# mail servers are disabled (a dev database must never send real email).
env.cr.commit()
print("DBCTL_SANITIZED")
"""


def sanitize(cfg: Config, db: str) -> None:
    """Regenerate the instance uuid and disable mail servers on ``db``."""
    run_python(cfg, db, _SANITIZE_CODE, purpose="sanitize")
