#include "feed/io.hpp"
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
namespace feed {
namespace {
constexpr uint64_t cap = 64ULL * 1024 * 1024;
Error problem(const char *code, const char *detail) {
    return {code, {}, 0, detail};
}
size_t read_bytes(int fd, void *buffer, size_t n) {
    size_t total = 0;
    while (total < n) {
        auto r = ::read(fd, static_cast<char *>(buffer) + total, n - total);
        if (r < 0) {
            if (errno == EINTR)
                continue;
            throw IoFailure(problem("io_error", "capture read failed"));
        }
        if (r == 0)
            break;
        total += static_cast<size_t>(r);
    }
    return total;
}
bool write_bytes(int fd, const void *buffer, size_t n) {
    size_t total = 0;
    while (total < n) {
        auto r = ::write(fd, static_cast<const char *>(buffer) + total, n - total);
        if (r < 0) {
            if (errno == EINTR)
                continue;
            return false;
        }
        if (r == 0)
            return false;
        total += static_cast<size_t>(r);
    }
    return true;
}
} // namespace
CaptureReader::CaptureReader(const std::filesystem::path &path) {
    fd_ = ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd_ < 0)
        throw IoFailure(problem("io_error", "cannot open regular capture"));
    try {
        struct stat st{};
        if (fstat(fd_, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 8 ||
            static_cast<uint64_t>(st.st_size) > cap)
            throw IoFailure(problem("capture_format", "capture must be a bounded regular file"));
        char magic[8];
        if (read_bytes(fd_, magic, 8) != 8 || std::memcmp(magic, "FRCP0001", 8) != 0)
            throw IoFailure(problem("capture_format", "invalid capture magic"));
    } catch (...) {
        ::close(fd_);
        fd_ = -1;
        throw;
    }
}
CaptureReader::~CaptureReader() {
    if (fd_ >= 0)
        ::close(fd_);
}
Result<std::optional<CapturedDatagram>> CaptureReader::next() {
    std::array<unsigned char, 5> header{};
    const auto n = read_bytes(fd_, header.data(), header.size());
    if (n == 0)
        return std::optional<CapturedDatagram>{};
    if (n != 5 || header[0] > 1)
        return problem("capture_format", "partial or invalid capture record header");
    uint32_t size = 0;
    for (size_t j = 1; j < 5; ++j)
        size = (size << 8) | header[j];
    if (size > 65507 || records_ >= 2000000 || 5ULL + size > cap - bytes_)
        return problem("capture_format", "capture record/resource bound");
    CapturedDatagram out;
    out.truncated = header[0] != 0;
    out.data.resize(size);
    if (read_bytes(fd_, out.data.data(), size) != size)
        return problem("capture_format", "truncated capture payload");
    bytes_ += 5 + size;
    ++records_;
    return std::optional<CapturedDatagram>{std::move(out)};
}
CaptureWriter::CaptureWriter(const std::filesystem::path &path) {
    fd_ = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd_ < 0)
        throw IoFailure(problem("io_error", "capture destination must be new"));
    if (!write_bytes(fd_, "FRCP0001", 8)) {
        ::close(fd_);
        fd_ = -1;
        throw IoFailure(problem("io_error", "capture header write failed"));
    }
}
CaptureWriter::~CaptureWriter() {
    if (fd_ >= 0)
        ::close(fd_);
}
std::optional<Error> CaptureWriter::append(Bytes data, bool truncated) {
    if (fd_ < 0)
        return problem("io_error", "capture already closed");
    if (data.size() > 65507 || records_ >= 2000000 || data.size() + 5 > cap - bytes_)
        return problem("resource_limit", "capture byte/record limit");
    std::array<unsigned char, 5> h{};
    h[0] = truncated ? 1 : 0;
    for (unsigned j = 0; j < 4; ++j)
        h[1 + j] = static_cast<unsigned char>((data.size() >> (24 - j * 8)) & 255);
    if (!write_bytes(fd_, h.data(), h.size()) || !write_bytes(fd_, data.data(), data.size()))
        return problem("io_error", "capture write failed");
    bytes_ += h.size() + data.size();
    ++records_;
    return {};
}
std::optional<Error> CaptureWriter::finish() {
    if (fd_ < 0)
        return {};
    const int fd = fd_;
    fd_ = -1;
    if (::close(fd) != 0)
        return problem("io_error", "capture close failed");
    return {};
}
RunOutcome replay_capture(const std::filesystem::path &path, IBook &book, SessionConfig config,
                          size_t depth, bool include_orders) {
    config.live = false;
    Session session(book, config);
    CaptureReader reader(path);
    while (true) {
        auto next = reader.next();
        if (auto error = std::get_if<Error>(&next))
            throw IoFailure(*error);
        auto &record = std::get<std::optional<CapturedDatagram>>(next);
        if (!record)
            break;
        session.ingest(record->data, 0, record->truncated);
        if (session.status(0) == "Invalid")
            break;
    }
    RunOutcome out;
    out.offline = true;
    out.depth = depth;
    out.include_orders = include_orders;
    out.view = session.view(0, depth, include_orders);
    out.counters = session.counters();
    out.audit = session.audit();
    if (out.view.status == "ReplayPrefix" || out.view.status == "Gap")
        out.view.status = "Incomplete";
    return out;
}
} // namespace feed
