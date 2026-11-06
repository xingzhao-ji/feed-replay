PYTHON ?= python3
CXX := clang++
CACHE ?= $(HOME)/.cache/job-apps-runtime/feed-replay
BUILD := $(CACHE)/build
FLAGS := -std=c++20 -O2 -Wall -Wextra -Werror -Iinclude
GUARD := python3 scripts/guard.py
.PHONY: test test-codec test-book test-parity test-session test-cli test-udp test-benchmark sanitize verify benchmark
CORE := src/codec.cpp src/indexed_book.cpp src/scan_book.cpp src/session.cpp
IO := src/capture.cpp src/report.cpp src/udp.cpp
$(BUILD)/probe: $(CORE) tests/probe.cpp $(wildcard include/feed/*.hpp)
	$(GUARD) $(CXX) $(FLAGS) $(CORE) tests/probe.cpp -o $@
$(BUILD)/feed_replay: src/main.cpp $(CORE) $(IO) $(wildcard include/feed/*.hpp)
	$(GUARD) $(CXX) $(FLAGS) $(CORE) $(IO) src/main.cpp -o $@
test-cli: $(BUILD)/feed_replay
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_cli.py
test-codec: $(BUILD)/probe
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_codec.py
test-book: $(BUILD)/probe
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_book.py
test-parity: test-book
test-session: $(BUILD)/probe
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_session.py
test-udp: $(BUILD)/feed_replay
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_udp.py
test: test-codec test-book test-session test-cli test-udp test-benchmark
sanitize:
	$(GUARD) $(CXX) $(FLAGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) tests/probe.cpp -o $(BUILD)/probe_sanitized
	$(GUARD) $(CXX) $(FLAGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) $(IO) src/main.cpp -o $(BUILD)/feed_replay_sanitized
	$(GUARD) $(CXX) $(FLAGS) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $(CORE) $(IO) src/benchmark.cpp -o $(BUILD)/feed_benchmark_sanitized
	FEED_PROBE=$(BUILD)/probe_sanitized FEED_BINARY=$(BUILD)/feed_replay_sanitized FEED_BENCHMARK=$(BUILD)/feed_benchmark_sanitized $(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests
$(BUILD)/feed_benchmark: src/benchmark.cpp $(CORE) $(IO) $(wildcard include/feed/*.hpp)
	$(GUARD) $(CXX) $(FLAGS) $(CORE) $(IO) src/benchmark.cpp -o $@
test-benchmark: $(BUILD)/feed_benchmark
	$(GUARD) $(PYTHON) -m pytest -q -p no:cacheprovider tests/test_benchmark.py

verify: $(BUILD)/probe $(BUILD)/feed_replay $(BUILD)/feed_benchmark
	$(GUARD) $(PYTHON) scripts/verify.py
benchmark: $(BUILD)/feed_benchmark
	$(GUARD) $(PYTHON) scripts/benchmark_report.py
