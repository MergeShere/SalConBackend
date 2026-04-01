"""Add MetaMap KYC fields, ghana_card_hash, and subscription trial fields

Revision ID: a1b2c3d4e5f6
Revises: b6cf6633c7eb
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b6cf6633c7eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # users — trial fields and Ghana card dedup hash
    # ------------------------------------------------------------------
    op.add_column('users', sa.Column('trial_start_date', sa.DateTime(), nullable=True))
    op.add_column(
        'users',
        sa.Column('ghana_card_hash', sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f('ix_users_ghana_card_hash'), 'users', ['ghana_card_hash'], unique=True
    )

    # ------------------------------------------------------------------
    # vendor_kyc — MetaMap integration + dedup hash + trial timestamp
    # ------------------------------------------------------------------
    op.add_column('vendor_kyc', sa.Column('metamap_verification_id', sa.String(length=200), nullable=True))
    op.add_column('vendor_kyc', sa.Column('metamap_identity_id', sa.String(length=200), nullable=True))
    op.add_column('vendor_kyc', sa.Column('metamap_flow_id', sa.String(length=200), nullable=True))
    op.add_column('vendor_kyc', sa.Column('metamap_status', sa.String(length=50), nullable=True))
    op.add_column('vendor_kyc', sa.Column('metamap_metadata', sa.JSON(), nullable=True))
    op.add_column('vendor_kyc', sa.Column('metamap_verified_at', sa.DateTime(), nullable=True))
    op.add_column(
        'vendor_kyc',
        sa.Column('ghana_card_hash', sa.String(length=64), nullable=True),
    )
    op.add_column('vendor_kyc', sa.Column('trial_activated_at', sa.DateTime(), nullable=True))

    op.create_index(
        op.f('ix_vendor_kyc_metamap_verification_id'),
        'vendor_kyc',
        ['metamap_verification_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_vendor_kyc_ghana_card_hash'),
        'vendor_kyc',
        ['ghana_card_hash'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_vendor_kyc_ghana_card_hash'), table_name='vendor_kyc')
    op.drop_index(op.f('ix_vendor_kyc_metamap_verification_id'), table_name='vendor_kyc')
    op.drop_column('vendor_kyc', 'trial_activated_at')
    op.drop_column('vendor_kyc', 'ghana_card_hash')
    op.drop_column('vendor_kyc', 'metamap_verified_at')
    op.drop_column('vendor_kyc', 'metamap_metadata')
    op.drop_column('vendor_kyc', 'metamap_status')
    op.drop_column('vendor_kyc', 'metamap_flow_id')
    op.drop_column('vendor_kyc', 'metamap_identity_id')
    op.drop_column('vendor_kyc', 'metamap_verification_id')

    op.drop_index(op.f('ix_users_ghana_card_hash'), table_name='users')
    op.drop_column('users', 'ghana_card_hash')
    op.drop_column('users', 'trial_start_date')
