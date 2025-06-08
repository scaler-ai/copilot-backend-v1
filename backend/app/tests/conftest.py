from collections.abc import Generator
import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, create_engine

from app.core.config import settings
from app.core.db import init_db
from app.main import app
from app.models import Item, User
from app.tests.utils.user import authentication_token_from_email
from app.tests.utils.utils import get_superuser_token_headers

# Use test database if available
test_db_url = os.getenv("TEST_DATABASE_URL")
if test_db_url:
    engine = create_engine(test_db_url, pool_pre_ping=True)
else:
    from app.core.db import engine


@pytest.fixture(scope="session")
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        statement = delete(Item)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
