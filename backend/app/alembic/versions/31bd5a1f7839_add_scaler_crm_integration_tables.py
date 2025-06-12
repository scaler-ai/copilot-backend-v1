"""add_scaler_crm_integration_tables

Revision ID: 31bd5a1f7839
Revises: 20250609212449
Create Date: 2025-06-10 02:32:43.885672

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '31bd5a1f7839'
down_revision = '20250609212449'
branch_labels = None
depends_on = None


def upgrade():
    # Create scalercrmauth table
    op.create_table(
        'scalercrmauth',
        sa.Column('crm_user_email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('crm_user_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('crm_user_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_sync_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('sync_status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('encrypted_access_token', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=False),
        sa.Column('encrypted_refresh_token', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('token_expires_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id')
    )
    op.create_index(op.f('ix_scalercrmauth_crm_user_email'), 'scalercrmauth', ['crm_user_email'], unique=False)
    
    # Create scalerlead table
    op.create_table(
        'scalerlead',
        sa.Column('lead_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('lead_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('company', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('designation', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('lead_source', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('lead_status', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('lead_stage', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('lead_score', sa.Integer(), nullable=True),
        sa.Column('created_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('last_activity_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('assigned_to', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('assigned_to_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('crm_auth_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['crm_auth_id'], ['scalercrmauth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scalerlead_lead_id'), 'scalerlead', ['lead_id'], unique=False)
    
    # Create scaleractivity table
    op.create_table(
        'scaleractivity',
        sa.Column('activity_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('activity_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('activity_subject', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('activity_description', sqlmodel.sql.sqltypes.AutoString(length=5000), nullable=True),
        sa.Column('activity_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('outcome', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('next_action', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('sentiment', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('engagement_score', sa.Integer(), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('crm_auth_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['crm_auth_id'], ['scalercrmauth.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['scalerlead.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scaleractivity_activity_id'), 'scaleractivity', ['activity_id'], unique=False)
    op.create_index(op.f('ix_scaleractivity_activity_date'), 'scaleractivity', ['activity_date'], unique=False)
    
    # Create scalerconversation table
    op.create_table(
        'scalerconversation',
        sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('conversation_type', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('conversation_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('transcript_available', sa.Boolean(), nullable=False),
        sa.Column('recording_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('analysis_status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('transcript_text', sqlmodel.sql.sqltypes.AutoString(length=50000), nullable=True),
        sa.Column('transcript_summary', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('analyzed_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('crm_auth_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['crm_auth_id'], ['scalercrmauth.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['scalerlead.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scalerconversation_conversation_id'), 'scalerconversation', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_scalerconversation_conversation_date'), 'scalerconversation', ['conversation_date'], unique=False)
    
    # Create conversationfeedback table
    op.create_table(
        'conversationfeedback',
        sa.Column('feedback_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('feedback_category', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('feedback_text', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False),
        sa.Column('specific_moment', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('suggested_response', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('impact_level', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('confidence_score', sa.Integer(), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['scalerconversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create salesperformanceanalysis table
    op.create_table(
        'salesperformanceanalysis',
        sa.Column('analysis_period_start', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('analysis_period_end', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('total_leads', sa.Integer(), nullable=False),
        sa.Column('total_activities', sa.Integer(), nullable=False),
        sa.Column('total_conversations', sa.Integer(), nullable=False),
        sa.Column('conversion_rate', sa.Float(), nullable=False),
        sa.Column('average_response_time_hours', sa.Float(), nullable=True),
        sa.Column('average_deal_size', sa.Float(), nullable=True),
        sa.Column('activity_breakdown', sa.JSON(), nullable=True),
        sa.Column('lead_stage_distribution', sa.JSON(), nullable=True),
        sa.Column('performance_summary', sqlmodel.sql.sqltypes.AutoString(length=5000), nullable=False),
        sa.Column('strengths_identified', sa.JSON(), nullable=True),
        sa.Column('improvement_areas', sa.JSON(), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('crm_auth_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['crm_auth_id'], ['scalercrmauth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_salesperformanceanalysis_analysis_period_start'), 'salesperformanceanalysis', ['analysis_period_start'], unique=False)
    op.create_index(op.f('ix_salesperformanceanalysis_analysis_period_end'), 'salesperformanceanalysis', ['analysis_period_end'], unique=False)
    
    # Create salesskillrating table
    op.create_table(
        'salesskillrating',
        sa.Column('skill_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('skill_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('skill_category', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('inferred_level', sa.Integer(), nullable=False),
        sa.Column('confidence_score', sa.Integer(), nullable=False),
        sa.Column('evidence_summary', sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False),
        sa.Column('evidence_count', sa.Integer(), nullable=False),
        sa.Column('improvement_suggestions', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('generated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('analysis_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['salesperformanceanalysis.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_salesskillrating_skill_id'), 'salesskillrating', ['skill_id'], unique=False)


def downgrade():
    # Drop tables in reverse order
    op.drop_index(op.f('ix_salesskillrating_skill_id'), table_name='salesskillrating')
    op.drop_table('salesskillrating')
    
    op.drop_index(op.f('ix_salesperformanceanalysis_analysis_period_end'), table_name='salesperformanceanalysis')
    op.drop_index(op.f('ix_salesperformanceanalysis_analysis_period_start'), table_name='salesperformanceanalysis')
    op.drop_table('salesperformanceanalysis')
    
    op.drop_table('conversationfeedback')
    
    op.drop_index(op.f('ix_scalerconversation_conversation_date'), table_name='scalerconversation')
    op.drop_index(op.f('ix_scalerconversation_conversation_id'), table_name='scalerconversation')
    op.drop_table('scalerconversation')
    
    op.drop_index(op.f('ix_scaleractivity_activity_date'), table_name='scaleractivity')
    op.drop_index(op.f('ix_scaleractivity_activity_id'), table_name='scaleractivity')
    op.drop_table('scaleractivity')
    
    op.drop_index(op.f('ix_scalerlead_lead_id'), table_name='scalerlead')
    op.drop_table('scalerlead')
    
    op.drop_index(op.f('ix_scalercrmauth_crm_user_email'), table_name='scalercrmauth')
    op.drop_table('scalercrmauth')