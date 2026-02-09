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


def _reapply_dreyfus_mappings(stdout):
    """Re-run dreyfus mappings to catch any records missed by 0001.

    The fixtures were updated in the same commit as this step, so fresh
    installs get the right data.  For existing deployments the idempotent
    apply_dreyfus_mappings command ensures every DB record is up to date.
    """
    _apply_dreyfus_mappings(stdout)


STEPS = [
    ('0001_apply_dreyfus_mappings', _apply_dreyfus_mappings),
    ('0002_reapply_dreyfus_mappings', _reapply_dreyfus_mappings),
]
