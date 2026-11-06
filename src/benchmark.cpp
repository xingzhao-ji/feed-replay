#include "feed/io.hpp"
#include <charconv>
#include <chrono>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>

namespace {
using namespace feed;
constexpr size_t preload_count = 2056;
constexpr size_t update_count = 50000;
constexpr uint64_t buffer_cap = 64 * 1024 * 1024;
const SessionId benchmark_session{std::byte{'B'}, std::byte{'E'}, std::byte{'N'}, std::byte{'C'},
                                  std::byte{'H'}, std::byte{'0'}, std::byte{'0'}, std::byte{'0'},
                                  std::byte{'0'}, std::byte{'1'}};
using Clock = std::chrono::steady_clock;

uint64_t elapsed(Clock::time_point start) {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count());
}
uint64_t number(const std::string &text) {
    uint64_t value = 0;
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} || end != text.data() + text.size())
        throw std::runtime_error("invalid oracle integer");
    return value;
}
struct Observation {
    size_t update_index;
    Locate locate;
    Quote quote;
    bool live_fresh = false, quote_usable = false;
    bool operator==(const Observation &) const = default;
};
struct Sample {
    size_t frequency, pair, position;
    bool measured;
    std::string engine;
    uint64_t elapsed_ns;
};

std::vector<CapturedDatagram> read_capture(const std::filesystem::path &path) {
    CaptureReader reader(path);
    std::vector<CapturedDatagram> records;
    uint64_t bytes = 0;
    while (true) {
        auto next = reader.next();
        if (auto error = std::get_if<Error>(&next))
            throw IoFailure(*error);
        auto &record = std::get<std::optional<CapturedDatagram>>(next);
        if (!record)
            break;
        bytes += record->data.size();
        // This benchmark has its own per-experiment bounds, not a live receive counter.
        if (record->truncated || bytes > buffer_cap || records.size() >= 100000)
            throw std::runtime_error("benchmark capture bound/truncation");
        records.push_back(std::move(*record));
    }
    return records;
}
std::vector<Event> decode(const std::vector<CapturedDatagram> &records) {
    std::vector<Event> events;
    events.reserve(preload_count + update_count);
    Sequence expected = 1;
    bool ended = false;
    for (const auto &record : records) {
        auto parsed = decode_frame(record.data);
        if (auto error = std::get_if<Error>(&parsed))
            throw IoFailure(*error);
        const auto &frame = std::get<Frame>(parsed);
        if (ended || frame.session != benchmark_session || frame.first != expected)
            throw std::runtime_error("benchmark requires a contiguous fixed session");
        if (frame.kind == FrameKind::end) {
            ended = true;
            continue;
        }
        if (frame.kind != FrameKind::data)
            throw std::runtime_error("unexpected benchmark marker");
        for (const auto span : frame.messages) {
            auto event = decode_itch(Bytes(record.data).subspan(span.offset, span.length));
            if (auto error = std::get_if<Error>(&event))
                throw IoFailure(*error);
            if (events.size() >= preload_count + 100000)
                throw std::runtime_error("benchmark update cap");
            events.push_back(std::get<Event>(std::move(event)));
        }
        expected += frame.count; // decode_frame checked the exclusive end's uint64 range.
    }
    if (!ended || events.size() != preload_count + update_count)
        throw std::runtime_error("benchmark shape differs from frozen study");
    return events;
}
std::vector<Observation> read_oracle(const std::filesystem::path &path) {
    if (std::filesystem::file_size(path) > buffer_cap)
        throw std::runtime_error("oracle byte cap");
    std::ifstream input(path);
    if (!input)
        throw std::runtime_error("cannot read oracle");
    std::vector<Observation> out;
    out.reserve(update_count);
    std::string line;
    while (std::getline(input, line)) {
        if (line.size() > 256 || out.size() >= update_count)
            throw std::runtime_error("oracle row cap");
        std::istringstream row(line);
        std::array<std::string, 8> fields;
        for (auto &field : fields)
            if (!(row >> field))
                throw std::runtime_error("short oracle row");
        std::string extra;
        if (row >> extra)
            throw std::runtime_error("extra oracle field");
        const auto index = number(fields[0]), locate = number(fields[1]);
        if (index != out.size() || locate != index % 8 + 1 || fields[6] != "0" || fields[7] != "0")
            throw std::runtime_error("oracle schedule/currentness differs");
        auto level = [&](size_t offset) -> std::optional<Level> {
            if (fields[offset] == "-" && fields[offset + 1] == "-")
                return {};
            const auto price = number(fields[offset]), quantity = number(fields[offset + 1]);
            if (price > 2000000000 || quantity == 0 || quantity > 100000ULL * UINT32_MAX)
                throw std::runtime_error("oracle level domain");
            return Level{static_cast<Price>(price), quantity};
        };
        out.push_back({index, static_cast<Locate>(locate), {level(2), level(4)}});
    }
    if (!input.eof() || out.size() != update_count)
        throw std::runtime_error("oracle row count");
    return out;
}

// Setup, allocations, reference comparison and final snapshots stay outside the timed region.
uint64_t run(const std::string &engine, const std::vector<Event> &events, size_t frequency,
             const std::vector<Observation> &expected, std::vector<Observation> &observations,
             std::string &final_book) {
    std::unique_ptr<IBook> book;
    if (engine == "indexed")
        book = std::make_unique<IndexedBook>();
    else
        book = std::make_unique<ScanBook>();
    for (size_t index = 0; index < preload_count; ++index)
        if (auto error = book->apply(events[index]))
            throw IoFailure(*error);
    observations.clear();
    observations.reserve((update_count + frequency - 1) / frequency);
    const auto start = Clock::now();
    for (size_t index = 0; index < update_count; ++index) {
        if (auto error = book->apply(events[preload_count + index]))
            throw IoFailure(*error);
        if (index % frequency == 0) {
            const auto locate = static_cast<Locate>(index % 8 + 1);
            auto quote = book->quote(locate);
            if (auto error = std::get_if<Error>(&quote))
                throw IoFailure(*error);
            observations.push_back({index, locate, std::get<Quote>(quote)});
        }
    }
    const auto duration = elapsed(start);
    size_t position = 0;
    for (size_t index = 0; index < update_count; index += frequency) {
        if (position >= observations.size() || observations[position] != expected[index])
            throw std::runtime_error("exact independent quote mismatch at update " +
                                     std::to_string(index));
        ++position;
    }
    if (position != observations.size())
        throw std::runtime_error("extra quote observations");
    final_book = book_json(book->snapshot(0, true));
    return duration;
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 3 || (std::string(argv[1]) != "--check" && std::string(argv[1]) != "--measure"))
            throw std::runtime_error(
                "usage: feed_benchmark --check|--measure FROZEN_WORKLOAD_DIRECTORY");
        const bool measure = std::string(argv[1]) == "--measure";
        const std::filesystem::path directory = argv[2];
        const auto records = read_capture(directory / "workload.frcp");
        const auto events = decode(records);
        const auto oracle = read_oracle(directory / "oracle-quotes.tsv");
        if (3 * update_count * sizeof(Observation) > buffer_cap)
            throw std::runtime_error("combined oracle/two-result buffers exceed cap");
        std::vector<Observation> indexed, scan;
        std::vector<Sample> samples;
        std::vector<uint64_t> parser_samples;
        std::string final_book;
        if (measure) {
            // One parser warmup followed by all eight measurements; raw packets already in memory.
            for (size_t pair = 0; pair < 9; ++pair) {
                const auto start = Clock::now();
                const auto decoded = decode(records);
                parser_samples.push_back(elapsed(start));
                if (decoded.size() != events.size())
                    throw std::runtime_error("parser result count differs");
            }
        }
        for (size_t frequency : {1, 32, 256}) {
            const size_t pairs = measure ? 9 : 1;
            for (size_t pair = 0; pair < pairs; ++pair) {
                std::string indexed_final, scan_final;
                for (size_t position = 0; position < 2; ++position) {
                    const bool indexed_first = pair == 0 || pair % 2 == 1;
                    const bool use_indexed = position == 0 ? indexed_first : !indexed_first;
                    const std::string engine = use_indexed ? "indexed" : "scan";
                    const auto duration =
                        run(engine, events, frequency, oracle, use_indexed ? indexed : scan,
                            use_indexed ? indexed_final : scan_final);
                    if (measure)
                        samples.push_back({frequency, pair, position, pair != 0, engine, duration});
                }
                // Compare every stored observation and full final state, not just hashes/counts.
                if (indexed != scan || indexed_final != scan_final)
                    throw std::runtime_error("engine output sequences/final books differ");
                if (!final_book.empty() && final_book != indexed_final)
                    throw std::runtime_error("final state changed with query frequency");
                final_book = std::move(indexed_final);
            }
        }
        std::cout << "{\"schema_version\":1,\"preload_events\":" << preload_count
                  << ",\"updates\":" << update_count << ",\"checks\":[";
        bool first = true;
        for (size_t frequency : {1, 32, 256}) {
            if (!first)
                std::cout << ',';
            first = false;
            std::cout << "{\"frequency\":" << frequency
                      << ",\"queries\":" << (update_count + frequency - 1) / frequency << '}';
        }
        std::cout << "],\"samples\":[";
        first = true;
        for (const auto &sample : samples) {
            if (!first)
                std::cout << ',';
            first = false;
            std::cout << "{\"frequency\":" << sample.frequency << ",\"pair\":" << sample.pair
                      << ",\"position\":" << sample.position
                      << ",\"measured\":" << (sample.measured ? "true" : "false")
                      << ",\"engine\":\"" << sample.engine << "\",\"elapsed_ns\":\""
                      << sample.elapsed_ns << "\"}";
        }
        std::cout << "],\"parser_samples\":[";
        for (size_t index = 0; index < parser_samples.size(); ++index) {
            if (index)
                std::cout << ',';
            std::cout << "{\"measured\":" << (index ? "true" : "false") << ",\"elapsed_ns\":\""
                      << parser_samples[index] << "\"}";
        }
        std::cout << "],\"final_book\":" << final_book << "}\n";
    } catch (const std::exception &error) {
        std::cerr << "benchmark failed: " << error.what() << '\n';
        return 1;
    }
}
