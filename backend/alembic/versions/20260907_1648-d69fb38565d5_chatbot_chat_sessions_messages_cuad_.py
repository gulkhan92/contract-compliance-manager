"""chatbot: chat sessions/messages, CUAD reference corpus, chunk search_vector

Revision ID: d69fb38565d5
Revises: 59edc992cefd
Create Date: 2026-09-07 16:48:55.302969

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd69fb38565d5'
down_revision: str | Sequence[str] | None = '59edc992cefd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# See the initial_schema migration's module docstring for why every native
# ENUM is declared once here with create_type=False and created/dropped
# explicitly, rather than left to op.create_table()'s implicit behavior.
chat_session_scope_enum = postgresql.ENUM(
    'organization', 'contract', name='chat_session_scope', create_type=False
)
chat_role_enum = postgresql.ENUM('user', 'assistant', 'system', name='chat_role', create_type=False)
chat_confidence_enum = postgresql.ENUM(
    'high', 'medium', 'low', 'insufficient_information', name='chat_confidence', create_type=False
)
chat_intent_enum = postgresql.ENUM(
    'domain_question', 'clause_benchmark', 'calendar_query', 'out_of_scope',
    name='chat_intent', create_type=False,
)
chat_feedback_enum = postgresql.ENUM('none', 'up', 'down', name='chat_feedback', create_type=False)

ALL_ENUMS = (
    chat_session_scope_enum,
    chat_role_enum,
    chat_confidence_enum,
    chat_intent_enum,
    chat_feedback_enum,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table('cuad_reference_clauses',
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('source_contract_title', sa.String(length=500), nullable=False),
    sa.Column('clause_text', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(768), nullable=True),
    sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', clause_text)", persisted=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cuad_reference_clauses_category'), 'cuad_reference_clauses', ['category'], unique=False)
    op.create_index('ix_cuad_reference_clauses_embedding_hnsw', 'cuad_reference_clauses', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_cuad_reference_clauses_search_vector_gin', 'cuad_reference_clauses', ['search_vector'], unique=False, postgresql_using='gin')
    op.create_table('chat_sessions',
    sa.Column('org_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('scope', chat_session_scope_enum, nullable=False),
    sa.Column('contract_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['contract_id'], ['contracts.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_sessions_org_id'), 'chat_sessions', ['org_id'], unique=False)
    op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)
    op.create_table('chat_messages',
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('role', chat_role_enum, nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('confidence', chat_confidence_enum, nullable=True),
    sa.Column('intent', chat_intent_enum, nullable=True),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('feedback', chat_feedback_enum, nullable=False),
    sa.Column('langfuse_trace_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_messages_session_id'), 'chat_messages', ['session_id'], unique=False)
    op.add_column('contract_chunks', sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', raw_text)", persisted=True), nullable=False))
    op.create_index('ix_contract_chunks_search_vector_gin', 'contract_chunks', ['search_vector'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_contract_chunks_search_vector_gin', table_name='contract_chunks', postgresql_using='gin')
    op.drop_column('contract_chunks', 'search_vector')
    op.drop_index(op.f('ix_chat_messages_session_id'), table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index(op.f('ix_chat_sessions_user_id'), table_name='chat_sessions')
    op.drop_index(op.f('ix_chat_sessions_org_id'), table_name='chat_sessions')
    op.drop_table('chat_sessions')
    op.drop_index('ix_cuad_reference_clauses_search_vector_gin', table_name='cuad_reference_clauses', postgresql_using='gin')
    op.drop_index('ix_cuad_reference_clauses_embedding_hnsw', table_name='cuad_reference_clauses', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_cuad_reference_clauses_category'), table_name='cuad_reference_clauses')
    op.drop_table('cuad_reference_clauses')

    bind = op.get_bind()
    for enum_type in ALL_ENUMS:
        enum_type.drop(bind, checkfirst=True)
