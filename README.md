# Stock Exchange Trading Platform

A stock exchange trading platform that allows users to trade stocks, view order books, and manage their portfolios.

## Features

- User registration and authentication
- Trading functionality (market and limit orders)
- Order book visualization
- Portfolio management
- Admin panel for instrument and user management

## Tech Stack

- Python 3.12+
- FastAPI
- SQLAlchemy
- PostgreSQL
- Docker
- UV (Fast Python package installer)
- Ruff (Fast Python linter)

## Development Setup

### Prerequisites

1. Install Python 3.12
2. Install Docker and Docker Compose
3. Install UV package manager

### Installing UV (Recommended)

UV is a fast Python package installer and resolver, written in Rust.

#### macOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Windows:
```bash
pip install uv
```

### Project Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/stock-exchange.git
cd stock-exchange
```

2. Create and activate a virtual environment:
```bash
# Using UV
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

```

3. Install dependencies:
```bash
# Using UV
uv pip install -e .
```

4. Install pre-commit hooks:
```bash
# Using UV
uv pip install pre-commit
pre-commit install

# Or using pip
pip install pre-commit
pre-commit install
```

5. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Development with Docker

The project is configured for development with Docker, supporting hot-reloading of code changes.

1. Start the development environment:
```bash
docker-compose up --build
```

2. The application will be available at:
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

3. Make changes to your code - they will be automatically reloaded in the container.

### Code Quality Tools

#### Ruff (Linter and Formatter)

Ruff is configured in the project. It runs automatically on pre-commit, but you can also run it manually:

```bash
# Check for errors
ruff check .

# Fix errors automatically
ruff check --fix .

# Format code
ruff format .
```

#### Pre-commit Hooks

Pre-commit hooks are configured to run:
- Ruff linting and formatting
- Trailing whitespace removal
- YAML validation
- Large file checks

### Running Tests

```bash
# Using UV
uv pip install pytest pytest-cov
pytest

# Or using pip
pip install pytest pytest-cov
pytest
```

### Database Migrations

When you need to create or apply database migrations:

```bash
# Using UV
uv pip install alembic
alembic upgrade head

# Or using pip
pip install alembic
alembic upgrade head
```

## Production Deployment

For production deployment, use the Dockerfile without the `--reload` flag:

```bash
docker build -t stock-exchange .
docker run -p 8000:8000 stock-exchange
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

MIT 