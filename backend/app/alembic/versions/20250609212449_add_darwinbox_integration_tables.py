"""Add DarwinBox integration tables

Revision ID: 20250609212449
Revises: d1d7cd79c407
Create Date: 2025-06-09 21:24:49

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250609212449'
down_revision = 'd1d7cd79c407'
branch_labels = None
depends_on = None


def upgrade():
    # Create darwinboxemployee table
    op.create_table(
        'darwinboxemployee',
        sa.Column('darwinbox_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('employee_code', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('full_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('designation', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('department', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('location', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('reporting_manager_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('reporting_manager_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('date_of_joining', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('employment_status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column('phone_number', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('grade', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('business_unit', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('cost_center', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('is_manager', sa.Boolean(), nullable=False),
        sa.Column('employee_type', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_sync_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('synced_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['synced_by_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_darwinboxemployee_darwinbox_id'), 'darwinboxemployee', ['darwinbox_id'], unique=True)
    op.create_index(op.f('ix_darwinboxemployee_email'), 'darwinboxemployee', ['email'], unique=False)
    
    # Create employeegithubmapping table
    op.create_table(
        'employeegithubmapping',
        sa.Column('github_username', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('github_id', sa.Integer(), nullable=True),
        sa.Column('mapping_verified', sa.Boolean(), nullable=False),
        sa.Column('verification_method', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column('verification_notes', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('darwinbox_employee_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mapped_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['darwinbox_employee_id'], ['darwinboxemployee.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mapped_by_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('darwinbox_employee_id')
    )
    op.create_index(op.f('ix_employeegithubmapping_github_id'), 'employeegithubmapping', ['github_id'], unique=False)
    op.create_index(op.f('ix_employeegithubmapping_github_username'), 'employeegithubmapping', ['github_username'], unique=False)
    
    # Create teamstructure table
    op.create_table(
        'teamstructure',
        sa.Column('team_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('team_level', sa.Integer(), nullable=False),
        sa.Column('parent_team_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('manager_darwinbox_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('total_members', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('team_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_teamstructure_team_id'), 'teamstructure', ['team_id'], unique=True)


def downgrade():
    # Drop tables in reverse order
    op.drop_index(op.f('ix_teamstructure_team_id'), table_name='teamstructure')
    op.drop_table('teamstructure')
    
    op.drop_index(op.f('ix_employeegithubmapping_github_username'), table_name='employeegithubmapping')
    op.drop_index(op.f('ix_employeegithubmapping_github_id'), table_name='employeegithubmapping')
    op.drop_table('employeegithubmapping')
    
    op.drop_index(op.f('ix_darwinboxemployee_email'), table_name='darwinboxemployee')
    op.drop_index(op.f('ix_darwinboxemployee_darwinbox_id'), table_name='darwinboxemployee')
    op.drop_table('darwinboxemployee')