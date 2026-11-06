#include "feed/io.hpp"
#include <charconv>
#include <iostream>
#include <map>
#include <memory>
using namespace feed;
namespace {
uint64_t number(const std::string &text) {
    uint64_t value = 0;
    auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} || end != text.data() + text.size())
        throw std::invalid_argument("invalid unsigned integer");
    return value;
}
uint64_t bounded(const std::string &text, uint64_t low, uint64_t high) {
    const auto value = number(text);
    if (value < low || value > high)
        throw std::invalid_argument("option outside allowed range");
    return value;
}
SessionId session_id(const std::string &text) {
    if (text.size() != 10)
        throw std::invalid_argument("session must contain ten ASCII alphanumeric bytes");
    SessionId session;
    for (size_t index = 0; index < session.size(); ++index) {
        const char character = text[index];
        if (!((character >= 'A' && character <= 'Z') || (character >= 'a' && character <= 'z') ||
              (character >= '0' && character <= '9')))
            throw std::invalid_argument("session must be ASCII alphanumeric");
        session[index] = static_cast<std::byte>(character);
    }
    return session;
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc < 2 || (argc - 2) % 2 != 0)
            throw std::invalid_argument("usage: feed_replay replay|listen --capture FILE --session "
                                        "TENBYTES --output NEWDIR [options]");
        const std::string mode = argv[1];
        if (mode != "replay" && mode != "listen")
            throw std::invalid_argument("unknown mode");
        std::map<std::string, std::string> options;
        for (int index = 2; index < argc; index += 2)
            if (!options.emplace(argv[index], argv[index + 1]).second)
                throw std::invalid_argument("duplicate option");
        std::filesystem::path capture, output;
        LiveConfig config{};
        bool have_session = false;
        std::string engine = "indexed";
        for (const auto &[key, value] : options) {
            if (key == "--capture")
                capture = value;
            else if (key == "--output")
                output = value;
            else if (key == "--session") {
                config.session.session = session_id(value);
                have_session = true;
            } else if (key == "--depth")
                config.depth = bounded(value, 0, 20);
            else if (key == "--include-orders")
                config.include_orders = bounded(value, 0, 1) == 1;
            else if (key == "--engine") {
                if (value != "indexed" && value != "scan")
                    throw std::invalid_argument("unknown engine");
                engine = value;
            } else if (mode == "listen" && key == "--listen-port")
                config.listen_port = bounded(value, 1, 65535);
            else if (mode == "listen" && key == "--source-port")
                config.source_port = bounded(value, 1, 65535);
            else if (mode == "listen" && key == "--recovery-port")
                config.recovery_port = bounded(value, 1, 65535);
            else if (mode == "listen" && key == "--recv-buffer")
                config.receive_buffer = bounded(value, 20, 65507);
            else if (mode == "listen" && key == "--overall-ms")
                config.session.overall_ns = bounded(value, 1, 10000) * 1000000;
            else if (mode == "listen" && key == "--receive-bytes")
                config.receive_bytes = bounded(value, 1, 64 * 1024 * 1024);
            else if (mode == "listen" && key == "--receive-count")
                config.receive_count = bounded(value, 1, 2000000);
            else
                throw std::invalid_argument("unknown option");
        }
        if (capture.empty() || output.empty() || !have_session)
            throw std::invalid_argument("capture, session and output are required");
        std::unique_ptr<IBook> book;
        if (engine == "indexed")
            book = std::make_unique<IndexedBook>();
        else
            book = std::make_unique<ScanBook>();
        RunOutcome result;
        if (mode == "replay")
            result =
                replay_capture(capture, *book, config.session, config.depth, config.include_orders);
        else {
            // Validate ports before reserving a new capture file.
            if (!config.listen_port || !config.source_port || !config.recovery_port ||
                config.listen_port == config.source_port ||
                config.listen_port == config.recovery_port ||
                config.source_port == config.recovery_port)
                throw std::invalid_argument("three distinct loopback ports are required");
            CaptureWriter writer(capture);
            result = run_udp(config, *book, writer);
        }
        result.engine = engine;
        if (auto error = write_report(output, result))
            throw IoFailure(*error);
        std::cout << "{\"status\":\"" << result.view.status << "\",\"expected\":\""
                  << result.view.expected << "\"}\n";
        if (result.view.status == "Complete")
            return 0;
        if (result.view.status == "Invalid")
            return 4;
        return 3;
    } catch (const IoFailure &error) {
        std::cerr << error.error.code << ": " << error.what() << '\n';
        return 2;
    } catch (const std::exception &error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
