# Contributing to APIWeaver

Thank you for your interest in contributing to APIWeaver! This guide outlines our development workflow, coding standards, and submission guidelines.

---

## Code of Conduct

We expect all contributors to adhere to standard open source community standards: be respectful, constructive, and collaborative.

---

## Getting Started

### Prerequisites
- **Python 3.12+** and **Poetry**
- **Node.js 20+** and **npm**
- **Docker & Docker Desktop** (for supporting services like Postgres, Redis, Qdrant, MinIO, Vault)
- **Git**

### 1. Fork & Clone
```bash
git clone https://github.com/AJambla/APIWeaver-Autonomous-Multi-Agent-API-Integration-Platform.git
cd APIWeaver
```

### 2. Environment Setup
```bash
# Copy template environment file
cp .env.example .env

# Start local supporting data stores (PostgreSQL & Redis)
docker compose -f infra/docker/docker-compose.dev.yml up -d
```

### 3. Backend Setup
```bash
cd backend
poetry install --with dev
poetry run alembic upgrade head
```

### 4. Frontend Setup
```bash
cd ../frontend
npm ci --legacy-peer-deps
```

---

## Development Workflow & Standards

### Python (Backend & Workers)
- **Linter & Formatter:** We use [Ruff](https://docs.astral.sh/ruff/) with standard line-length conventions.
  ```bash
  cd backend
  poetry run ruff check .
  ```
- **Type Checking:** Strict type hints with Python 3.12 syntax:
  ```bash
  cd backend
  poetry run mypy app/
  ```
- **Database Migrations:** Never modify existing Alembic migrations that have been applied. Create new sequential migration scripts using:
  ```bash
  poetry run alembic revision -m "description_of_change"
  ```

### TypeScript / React (Frontend)
- **Framework:** React 18 SPA bundled via Vite with React Router v6 and Tailwind CSS.
- **Linting & Code Quality:**
  ```bash
  cd frontend
  npm run lint
  ```
- **Production Build Validation:**
  ```bash
  cd frontend
  npm run build
  ```

---

## Testing Guidelines

We enforce **100% hermetic testing**. Tests must never depend on live external networks, LLM provider API keys, or unmanaged external services.

### Running Backend Tests
```bash
cd backend
poetry run pytest -v
```
- Mock all LLM calls using `LLMClient.generate_json` or `LLMClient.generate_embedding` mock side effects.
- Use `FakeVaultClient`, `FakeQdrantClient`, and `InMemoryObjectStorage` for service dependencies.

### Running Frontend Tests
```bash
cd frontend
npm test
```
- Component tests use `@testing-library/react` and Vitest.
- Mock network calls and server-sent event hooks (`useWorkflowEvents`).

---

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) convention:

```
<type>(<scope>): <short description>
```

**Common types:**
- `feat`: A new user-facing feature
- `fix`: A bug fix
- `docs`: Documentation updates
- `test`: Adding or refactoring tests
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `ci`: Changes to CI/CD workflows and deployment configurations
- `chore`: Tooling, dependency, or configuration updates

**Examples:**
- `feat(export): add support for OpenAPI 3.1 JSON schema generation`
- `fix(security): sanitize file upload keys against directory traversal`
- `test(backend): add hermetic tests for planner agent DAG resolution`

---

## Pull Request Process

1. Create a feature branch off `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Commit your changes following commit standards.
3. Verify that all quality gates pass locally before opening a PR:
   ```bash
   # In backend/
   poetry run ruff check .
   poetry run pytest -q

   # In frontend/
   npm run lint
   npm test
   npm run build
   ```
4. Push your branch and open a Pull Request against `main`.
5. Ensure all CI/CD pipeline checks pass. Reviewers will provide feedback and merge upon approval.
