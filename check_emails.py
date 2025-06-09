#!/usr/bin/env python3
from sqlmodel import create_engine, Session, select, func
from backend.app.models import GitHubContributor
from backend.app.core.config import settings

# Create engine
engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))

# Query database
with Session(engine) as session:
    # Total contributors
    total = session.exec(select(func.count()).select_from(GitHubContributor)).one()
    print(f'Total contributors: {total}')
    
    # Contributors with email
    with_email = session.exec(
        select(func.count()).select_from(GitHubContributor)
        .where(GitHubContributor.email != None)
    ).one()
    print(f'Contributors with email: {with_email}')
    
    # Percentage
    if total > 0:
        percentage = (with_email / total) * 100
        print(f'Percentage with email: {percentage:.2f}%')
    else:
        print('No contributors in database')
    
    # Sample some contributors with emails
    print('\nSample contributors with emails:')
    contributors_with_email = session.exec(
        select(GitHubContributor)
        .where(GitHubContributor.email != None)
        .limit(5)
    ).all()
    
    for contrib in contributors_with_email:
        print(f'- {contrib.login}: {contrib.email}')
    
    # Sample some contributors without emails
    print('\nSample contributors without emails:')
    contributors_without_email = session.exec(
        select(GitHubContributor)
        .where(GitHubContributor.email == None)
        .limit(5)
    ).all()
    
    for contrib in contributors_without_email:
        print(f'- {contrib.login}: No email')
    
    # Check organizations
    print('\n\nOrganizations with contributor counts:')
    from backend.app.models import GitHubOrganization
    orgs = session.exec(select(GitHubOrganization)).all()
    for org in orgs:
        contrib_count = session.exec(
            select(func.count()).select_from(GitHubContributor)
            .where(GitHubContributor.organization_id == org.id)
        ).one()
        email_count = session.exec(
            select(func.count()).select_from(GitHubContributor)
            .where(GitHubContributor.organization_id == org.id)
            .where(GitHubContributor.email != None)
        ).one()
        print(f'- {org.name}: {contrib_count} contributors, {email_count} with emails ({(email_count/contrib_count*100 if contrib_count > 0 else 0):.1f}%)')