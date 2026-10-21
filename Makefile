.PHONY: help clean clean-temp clean-cache test lint

help:
	@echo "Available commands:"
	@echo "  make clean       - Clean all temporary files and cache"
	@echo "  make clean-temp  - Clean temporary directories only"
	@echo "  make clean-cache - Clean .cache directory"
	@echo "  make test        - Run tests with automatic temp cleanup"
	@echo "  make lint        - Run linters"

clean: clean-temp clean-cache
	@echo "All temporary files cleaned"

clean-temp:
	@echo "Cleaning temporary directories..."
	@python scripts/cleanup_temp.py --keep-cache

clean-cache:
	@echo "Cleaning cache directory..."
	@python scripts/cleanup_temp.py

test: clean-temp
	@echo "Running tests..."
	@pytest tests/ -v
	@echo "Cleaning up after tests..."
	@python scripts/cleanup_temp.py --keep-cache

lint:
	@echo "Running ruff..."
	@ruff check src/ scripts/
