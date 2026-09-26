# CelerLite Makefile

.PHONY: install dev api worker demo test lint docker-up docker-down

install:
	pip install -r requirements.txt

dev: docker-up
	@echo "Stack ready. Open http://localhost:8000"

api:
	python scripts/run_api.py

worker:
	python scripts/run_worker.py

demo:
	python scripts/submit_demo_tasks.py

test:
	pytest tests/ -v --tb=short

bench-throughput:
	python benchmarks/throughput_benchmark.py

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down -v

docker-logs:
	docker-compose logs -f

lint:
	python -m py_compile celerlite/**/*.py && echo "OK"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true
	rm -f test_celerlite.db
