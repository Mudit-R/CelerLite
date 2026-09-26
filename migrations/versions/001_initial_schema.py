"""Initial schema for tasks, workers, and dlq_entries

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tasks table
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('args_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('kwargs_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('queue', sa.String(length=100), nullable=False, server_default='default'),
        sa.Column('priority', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('worker_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('eta', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timeout', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_task_name', 'tasks', ['task_name'])
    op.create_index('ix_tasks_created_at', 'tasks', ['created_at'])
    op.create_index('ix_tasks_queue_status', 'tasks', ['queue', 'status'])

    # workers table
    op.create_table(
        'workers',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=True),
        sa.Column('hostname', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ONLINE'),
        sa.Column('tasks_processed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('tasks_failed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_task_id', sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # dlq_entries table
    op.create_table(
        'dlq_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=False),
        sa.Column('task_name', sa.String(length=255), nullable=False),
        sa.Column('args_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('kwargs_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('original_queue', sa.String(length=100), nullable=False),
        sa.Column('dead_lettered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('replayed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('replayed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_dlq_replayed', 'dlq_entries', ['replayed'])
    op.create_index('ix_dlq_dead_lettered_at', 'dlq_entries', ['dead_lettered_at'])


def downgrade() -> None:
    op.drop_table('dlq_entries')
    op.drop_table('workers')
    op.drop_table('tasks')
