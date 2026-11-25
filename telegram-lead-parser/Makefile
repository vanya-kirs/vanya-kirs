.PHONY: install up down migrate migrate-rollback generate-session check \
        test worker beat test-parser parse clean

# Install all dependencies (including dev extras)
install:
	pip install -e ".[dev]"

# Start infrastructure (postgres + redis only)
up:
	docker compose up -d --wait postgres redis
	@docker compose ps

# Stop and remove containers (keeps volumes)
down:
	docker compose down

# Apply Alembic migrations
migrate:
	alembic upgrade head

# Roll back the last migration
migrate-rollback:
	alembic downgrade -1

# Generate a new Telethon StringSession interactively
generate-session:
	python scripts/generate_session.py

# Verify all connections
check:
	python scripts/check_connections.py

# Run tests
test:
	pytest -v

# Start Celery worker locally (requires redis running)
worker:
	celery -A app.core.celery:celery_app worker --loglevel=info --concurrency=2

# Start Celery beat locally (requires redis running)
beat:
	celery -A app.core.celery:celery_app beat --loglevel=info

# Parse messages from a Telegram URL without DB (url= required)
# Usage: make test-parser url=@somegroup
test-parser:
ifndef url
	$(error url is required. Usage: make test-parser url=@somegroup)
endif
	python scripts/test_parser.py --url $(url) --limit 50

# Run full parse cycle for a DB source (source_id= required)
# Usage: make parse source_id=1
parse:
ifndef source_id
	$(error source_id is required. Usage: make parse source_id=1)
endif
	python scripts/test_parser_db.py --source-id $(source_id)

# Remove Python bytecode caches
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
