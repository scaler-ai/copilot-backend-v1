# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a full-stack FastAPI template project with a React frontend. It's built using the FastAPI Full Stack Template and includes:
- FastAPI backend with SQLModel ORM and PostgreSQL database
- React frontend with Vite, TypeScript, and Chakra UI
- Docker Compose for orchestration
- JWT authentication with secure password hashing
- Automated API client generation for frontend

## Architecture

### Backend
- **Framework**: FastAPI with automatic OpenAPI documentation
- **Database**: PostgreSQL with SQLModel ORM (combining SQLAlchemy + Pydantic)
- **Migrations**: Alembic for database schema management
- **Authentication**: JWT tokens with password hashing
- **Email**: MJML templates with MailCatcher for development
- **Package Manager**: UV (modern Python package manager)

### Frontend
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite for fast development and building
- **UI Library**: Chakra UI v3 for component library
- **State Management**: TanStack Query for server state
- **Routing**: TanStack Router for type-safe routing
- **API Client**: Auto-generated from OpenAPI schema
- **Testing**: Playwright for E2E tests

### Infrastructure
- **Containerization**: Docker and Docker Compose
- **Reverse Proxy**: Traefik for routing and load balancing
- **Database Admin**: Adminer for database UI
- **Email Testing**: MailCatcher for development

## Development Commands

### Quick Start
```bash
# Start the full development stack with hot reload
docker compose watch
```

### Backend Development

```bash
# Install dependencies
cd backend
uv sync

# Activate virtual environment
source .venv/bin/activate

# Run development server (outside Docker)
fastapi dev app/main.py

# Run tests
./scripts/test.sh

# Format code with Ruff
./scripts/format.sh

# Lint code
./scripts/lint.sh

# Run tests inside Docker
docker compose exec backend bash scripts/tests-start.sh

# Access backend container
docker compose exec backend bash
```

### Database Operations

```bash
# Create a new migration
docker compose exec backend alembic revision --autogenerate -m "migration message"

# Apply migrations
docker compose exec backend alembic upgrade head

# Rollback migration
docker compose exec backend alembic downgrade -1

# Check database status
docker compose exec backend alembic current
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Run linter (Biome)
npm run lint

# Regenerate API client from OpenAPI
npm run generate-client

# Run E2E tests
npx playwright test

# Run E2E tests with UI
npx playwright test --ui
```

### Utility Scripts

```bash
# Generate frontend API client from backend OpenAPI
./scripts/generate-client.sh

# Build Docker images
./scripts/build.sh

# Build and push Docker images
./scripts/build-push.sh

# Deploy to production
./scripts/deploy.sh
```

## Development URLs

When running `docker compose watch`:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Alternative API Docs**: http://localhost:8000/redoc
- **Adminer (DB Admin)**: http://localhost:8080
- **Traefik Dashboard**: http://localhost:8090
- **MailCatcher**: http://localhost:1080

## Key Development Patterns

### API Client Generation
The frontend TypeScript client is auto-generated from the backend's OpenAPI schema:
1. Backend changes are made to models/endpoints
2. Run `./scripts/generate-client.sh` to update the frontend client
3. Frontend automatically has type-safe API access

### Database Migrations
Always use Alembic for database schema changes:
1. Modify SQLModel models in `backend/app/models.py`
2. Create migration: `docker compose exec backend alembic revision --autogenerate -m "description"`
3. Apply migration: `docker compose exec backend alembic upgrade head`
4. Commit the generated migration files

### Testing Strategy
- **Backend**: Pytest with coverage reporting (`./scripts/test.sh`)
- **Frontend**: Playwright for E2E tests (`npx playwright test`)
- Tests run automatically in CI/CD via GitHub Actions

### Code Quality
- **Pre-commit hooks**: Automatically format and lint code before commits
- **Backend**: Ruff for Python linting and formatting
- **Frontend**: Biome for JavaScript/TypeScript linting
- **Conventional commits**: Follow conventional commit format

## Project Structure

```
.
├── backend/              # FastAPI backend application
│   ├── app/             # Application code
│   │   ├── api/         # API endpoints
│   │   ├── core/        # Core configurations
│   │   ├── crud.py      # CRUD operations
│   │   ├── models.py    # SQLModel database models
│   │   └── tests/       # Backend tests
│   ├── alembic/         # Database migrations
│   └── scripts/         # Utility scripts
├── frontend/            # React frontend application
│   ├── src/
│   │   ├── client/      # Auto-generated API client
│   │   ├── components/  # React components
│   │   ├── routes/      # Page components and routing
│   │   └── hooks/       # Custom React hooks
│   └── tests/           # E2E tests
├── docker-compose.yml   # Production Docker configuration
└── docker-compose.override.yml  # Development overrides
```

## Environment Configuration

Key environment variables (in `.env`):
- `SECRET_KEY`: JWT secret key (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- `FIRST_SUPERUSER_EMAIL`: Initial admin email
- `FIRST_SUPERUSER_PASSWORD`: Initial admin password  
- `POSTGRES_PASSWORD`: Database password
- `DATABASE_URL`: PostgreSQL connection string
- `SMTP_*`: Email server configuration
- `SENTRY_DSN`: Error tracking (optional)

## Common Tasks

### Adding a New API Endpoint
1. Add endpoint to `backend/app/api/routes/`
2. Add any new models to `backend/app/models.py`
3. Add CRUD operations to `backend/app/crud.py`
4. Create and apply database migration if needed
5. Regenerate frontend client: `./scripts/generate-client.sh`

### Modifying Database Schema
1. Update SQLModel models in `backend/app/models.py`
2. Create migration: `docker compose exec backend alembic revision --autogenerate -m "description"`
3. Review generated migration in `backend/app/alembic/versions/`
4. Apply migration: `docker compose exec backend alembic upgrade head`

### Running a Single Test
```bash
# Backend
docker compose exec backend pytest app/tests/test_file.py::test_function -v

# Frontend
npx playwright test test-file.spec.ts
```

### Debugging
- Backend: Use VS Code debugger (configurations included) or add `breakpoint()` in code
- Frontend: Use browser DevTools and React Developer Tools
- View logs: `docker compose logs [service-name]`