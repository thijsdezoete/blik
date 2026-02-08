"""
Registry of one-time upgrade steps.

Each entry is a (name, callable) tuple. The callable receives a stdout
write-stream for logging. Steps are run in order; only steps not yet
recorded as success=True in the UpgradeStep table will execute.

Old steps should stay in this list forever. If the underlying code is
removed later, replace the callable body with a no-op.
"""
from questionnaires.management.commands.apply_dreyfus_mappings import Command as DreyfusCommand


def _apply_dreyfus_mappings(stdout):
    cmd = DreyfusCommand(stdout=stdout)
    cmd.handle(dry_run=False)


STEPS = [
    ('0001_apply_dreyfus_mappings', _apply_dreyfus_mappings),
]
