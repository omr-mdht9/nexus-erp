"""Baseline the existing NEXUS ERP development schema.

This revision intentionally has no DDL. The application already created the
initial development schema before Alembic was added. Applying this revision
records that known baseline without recreating, changing, or deleting tables.
All later schema changes must use explicit Alembic revisions.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
