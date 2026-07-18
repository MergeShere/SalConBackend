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
    # users — add missing columns not in initial migration
    # ------------------------------------------------------------------
    op.add_column('users', sa.Column('kyc_verified', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.add_column('users', sa.Column('subscription_plan', sa.String(length=50), nullable=True, server_default='free'))
    op.add_column('users', sa.Column('subscription_expires_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('trial_start_date', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('ghana_card_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_users_ghana_card_hash'), 'users', ['ghana_card_hash'], unique=True)

    # ------------------------------------------------------------------
    # vendor_kyc — create table (includes MetaMap fields from the start)
    # ------------------------------------------------------------------
    op.create_table(
        'vendor_kyc',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vendor_id', sa.Integer(), nullable=False),
        # Document info
        sa.Column('id_type', sa.String(length=50), nullable=True),
        sa.Column('id_number', sa.String(length=100), nullable=True),
        sa.Column('full_name', sa.String(length=200), nullable=True),
        sa.Column('date_of_birth', sa.DateTime(), nullable=True),
        # Document URLs
        sa.Column('id_front_url', sa.String(length=500), nullable=True),
        sa.Column('id_back_url', sa.String(length=500), nullable=True),
        sa.Column('selfie_url', sa.String(length=500), nullable=True),
        # Legacy DeepFace verification results
        sa.Column('face_match_score', sa.Float(), nullable=True),
        sa.Column('face_match_status', sa.String(length=20), nullable=True),
        sa.Column('document_verification_status', sa.String(length=20), nullable=True),
        sa.Column('ocr_extracted_data', sa.JSON(), nullable=True),
        sa.Column('is_document_valid', sa.Boolean(), nullable=True),
        sa.Column('is_live_selfie', sa.Boolean(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('ai_analysis', sa.JSON(), nullable=True),
        # MetaMap fields
        sa.Column('metamap_verification_id', sa.String(length=200), nullable=True),
        sa.Column('metamap_identity_id', sa.String(length=200), nullable=True),
        sa.Column('metamap_flow_id', sa.String(length=200), nullable=True),
        sa.Column('metamap_status', sa.String(length=50), nullable=True),
        sa.Column('metamap_metadata', sa.JSON(), nullable=True),
        sa.Column('metamap_verified_at', sa.DateTime(), nullable=True),
        # Ghana card dedup + trial
        sa.Column('ghana_card_hash', sa.String(length=64), nullable=True),
        sa.Column('trial_activated_at', sa.DateTime(), nullable=True),
        # Status & review
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['vendor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vendor_id'),
    )
    op.create_index(op.f('ix_vendor_kyc_id'), 'vendor_kyc', ['id'], unique=False)
    op.create_index(op.f('ix_vendor_kyc_metamap_verification_id'), 'vendor_kyc', ['metamap_verification_id'], unique=False)
    op.create_index(op.f('ix_vendor_kyc_ghana_card_hash'), 'vendor_kyc', ['ghana_card_hash'], unique=False)

    # ------------------------------------------------------------------
    # kyc_audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        'kyc_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kyc_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=True),
        sa.Column('performed_by', sa.Integer(), nullable=True),
        sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['kyc_id'], ['vendor_kyc.id']),
        sa.ForeignKeyConstraint(['performed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_kyc_audit_logs_id'), 'kyc_audit_logs', ['id'], unique=False)

    # ------------------------------------------------------------------
    # vendor_business_info
    # ------------------------------------------------------------------
    op.create_table(
        'vendor_business_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('business_name', sa.String(length=255), nullable=False),
        sa.Column('business_phone', sa.String(length=20), nullable=False),
        sa.Column('business_address', sa.Text(), nullable=False),
        sa.Column('business_city', sa.String(length=100), nullable=False),
        sa.Column('business_state', sa.String(length=100), nullable=False),
        sa.Column('business_country', sa.String(length=100), nullable=False),
        sa.Column('business_description', sa.Text(), nullable=True),
        sa.Column('business_website', sa.String(length=500), nullable=True),
        sa.Column('tax_id', sa.String(length=100), nullable=True),
        sa.Column('business_registration_number', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_vendor_business_info_id'), 'vendor_business_info', ['id'], unique=False)
    op.create_index(op.f('ix_vendor_business_info_email'), 'vendor_business_info', ['email'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_vendor_business_info_email'), table_name='vendor_business_info')
    op.drop_index(op.f('ix_vendor_business_info_id'), table_name='vendor_business_info')
    op.drop_table('vendor_business_info')

    op.drop_index(op.f('ix_kyc_audit_logs_id'), table_name='kyc_audit_logs')
    op.drop_table('kyc_audit_logs')

    op.drop_index(op.f('ix_vendor_kyc_ghana_card_hash'), table_name='vendor_kyc')
    op.drop_index(op.f('ix_vendor_kyc_metamap_verification_id'), table_name='vendor_kyc')
    op.drop_index(op.f('ix_vendor_kyc_id'), table_name='vendor_kyc')
    op.drop_table('vendor_kyc')

    op.drop_index(op.f('ix_users_ghana_card_hash'), table_name='users')
    op.drop_column('users', 'ghana_card_hash')
    op.drop_column('users', 'trial_start_date')
    op.drop_column('users', 'subscription_expires_at')
    op.drop_column('users', 'subscription_plan')
    op.drop_column('users', 'kyc_verified')
