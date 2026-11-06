#include "feed/io.hpp"
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace feed {
namespace {
volatile std::sig_atomic_t interrupted = 0;
extern "C" void interrupt_handler(int) {
    interrupted = 1;
}

struct Socket {
    int fd = -1;
    ~Socket() {
        if (fd >= 0)
            ::close(fd);
    }
};

class SignalScope {
  public:
    SignalScope() {
        interrupted = 0;
        struct sigaction action{};
        action.sa_handler = interrupt_handler;
        sigemptyset(&action.sa_mask);
        if (sigaction(SIGINT, &action, &old_int_) != 0)
            throw IoFailure({"io", {}, 0, "cannot install SIGINT handler"});
        if (sigaction(SIGTERM, &action, &old_term_) != 0) {
            sigaction(SIGINT, &old_int_, nullptr);
            throw IoFailure({"io", {}, 0, "cannot install SIGTERM handler"});
        }
    }
    ~SignalScope() {
        sigaction(SIGINT, &old_int_, nullptr);
        sigaction(SIGTERM, &old_term_, nullptr);
    }

  private:
    struct sigaction old_int_{}, old_term_{};
};

sockaddr_in loopback(uint16_t port) {
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(port);
    return address;
}

bool terminal(const std::string &status) {
    return status == "Complete" || status == "Invalid" || status == "RecoveryFailed" ||
           status == "Cancelled";
}
} // namespace

RunOutcome run_udp(const LiveConfig &config, IBook &book, CaptureWriter &capture) {
    if (!config.listen_port || !config.source_port || !config.recovery_port ||
        config.listen_port == config.source_port || config.listen_port == config.recovery_port ||
        config.source_port == config.recovery_port || config.receive_buffer < 20 ||
        config.receive_buffer > 65507 || config.receive_bytes == 0 ||
        config.receive_bytes > 64 * 1024 * 1024 || config.receive_count == 0 ||
        config.receive_count > 2000000)
        throw std::invalid_argument("invalid loopback ports or receive limits");

    auto session_config = config.session;
    session_config.live = true;
    Session session(book, session_config);
    SignalScope signals;
    Socket socket;
    socket.fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket.fd < 0 || fcntl(socket.fd, F_SETFD, FD_CLOEXEC) != 0 ||
        fcntl(socket.fd, F_SETFL, O_NONBLOCK) != 0)
        throw IoFailure({"io", {}, 0, "cannot create nonblocking UDP socket"});
    const auto listen = loopback(config.listen_port);
    if (::bind(socket.fd, reinterpret_cast<const sockaddr *>(&listen), sizeof(listen)) != 0)
        throw IoFailure({"io", {}, 0, "cannot bind loopback listener"});
    const auto recovery = loopback(config.recovery_port);
    TransportMetrics metrics;
    std::vector<std::byte> buffer(config.receive_buffer);
    const auto origin = std::chrono::steady_clock::now();
    auto now = [&]() -> uint64_t {
        return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                         std::chrono::steady_clock::now() - origin)
                                         .count());
    };
    auto send_requests = [&](const Effects &effects) {
        for (const auto &request : effects.requests) {
            const auto sent =
                ::sendto(socket.fd, request.wire.data(), request.wire.size(), 0,
                         reinterpret_cast<const sockaddr *>(&recovery), sizeof(recovery));
            if (sent != static_cast<ssize_t>(request.wire.size())) {
                session.stop({"io", request.first, 0, "UDP recovery request send failed"});
                return;
            }
            ++metrics.requests_sent; // Session caps requests at 128, far below uint64 overflow.
        }
    };

    // The orchestrator starts its already-bound peers only after this handshake.
    std::cout << "{\"ready\":true,\"port\":" << config.listen_port << "}\n" << std::flush;
    while (true) {
        if (interrupted)
            session.cancel();
        send_requests(session.on_time(now()));
        if (terminal(session.status(now())))
            break;

        pollfd descriptor{socket.fd, POLLIN, 0};
        const int ready = ::poll(&descriptor, 1, 5);
        if (ready < 0) {
            if (errno == EINTR)
                continue;
            session.stop({"io", {}, 0, "poll failed"});
            break;
        }
        if (descriptor.revents & (POLLERR | POLLNVAL | POLLHUP)) {
            session.stop({"io", {}, 0, "UDP socket poll error"});
            break;
        }
        if (ready == 0)
            continue;

        // Check time before every datagram, including continuously readable foreign traffic.
        if (interrupted)
            session.cancel();
        send_requests(session.on_time(now()));
        if (terminal(session.status(now())))
            break;
        sockaddr_in peer{};
        iovec vector{buffer.data(), buffer.size()};
        msghdr message{};
        message.msg_name = &peer;
        message.msg_namelen = sizeof(peer);
        message.msg_iov = &vector;
        message.msg_iovlen = 1;
        const auto received = ::recvmsg(socket.fd, &message, 0);
        if (received < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
                continue;
            session.stop({"io", {}, 0, "recvmsg failed"});
            break;
        }
        const bool truncated = (message.msg_flags & MSG_TRUNC) != 0;
        const auto copied = std::min<size_t>(static_cast<size_t>(received), buffer.size());
        // macOS returns copied bytes on truncation, not the original datagram length.
        // Charge the maximum admitted datagram size, conservatively, even for foreign peers.
        const uint64_t charged_bytes = truncated ? 65507 : copied;
        ++metrics.received;
        metrics.received_bytes += charged_bytes;
        if (metrics.received > config.receive_count ||
            metrics.received_bytes > config.receive_bytes) {
            session.stop({"resource_limit", {}, 0, "all-peer receive budget exceeded"});
            break;
        }
        const auto peer_port = ntohs(peer.sin_port);
        if (message.msg_namelen != sizeof(peer) || peer.sin_family != AF_INET ||
            peer.sin_addr.s_addr != htonl(INADDR_LOOPBACK) ||
            (peer_port != config.source_port && peer_port != config.recovery_port)) {
            ++metrics.foreign;
            continue;
        }
        const Bytes bytes(buffer.data(), copied);
        if (auto error = capture.append(bytes, truncated)) {
            session.stop(*error);
            break;
        }
        send_requests(session.ingest(bytes, now(), truncated));
    }
    if (auto error = capture.finish())
        throw IoFailure(*error);
    return {session.view(now(), config.depth, config.include_orders),
            session.counters(),
            session.audit(),
            metrics,
            false,
            config.depth,
            config.include_orders};
}
} // namespace feed
