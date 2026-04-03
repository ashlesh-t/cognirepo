# CogniRepo — common development targets
# Usage: make proto | make test | make lint

.PHONY: proto test lint

proto:
	python -m grpc_tools.protoc \
		-I rpc/proto \
		--python_out=rpc/proto \
		--grpc_python_out=rpc/proto \
		rpc/proto/cognirepo.proto
	@echo "Proto files regenerated in rpc/proto/."
	@echo "If you see diffs, commit the updated _pb2.py and _pb2_grpc.py files."

test:
	pytest tests/ -v --tb=short --ignore=tests/test_api.py

lint:
	pylint $$(git ls-files '*.py' | grep -v 'venv/' | grep -v '_pb2') \
		--disable=C,R,import-error \
		--fail-under=8.0
