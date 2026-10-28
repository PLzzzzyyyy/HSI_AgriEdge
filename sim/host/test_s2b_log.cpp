// HOST ONLY. Include the real private log/STOP/formatter, never the App entry.
#if !defined(S2B_LOG_HOST_TEST) || S2B_LOG_HOST_TEST != 1
#error This harness requires the private host log adapter
#endif
#include "../../src/ps/s2b_idle_app/main.cpp"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif

namespace {
struct Parked {};
struct Observation {
    std::string bytes, events;
    size_t reads = 0, limit = 0, full_at = size_t(-1);
    uint32_t status = 0, last_status = 0;
    bool stopping = false;
} io;
size_t calls = 0;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
uint32_t read_status(uint32_t offset) {
    require(offset == 0x2cU, "unexpected read (only UART SR allowed)");
    require(io.reads < io.limit, "extra status read/retry/budget overrun");
    require(!io.stopping || (!io.events.empty() && io.events[0] == 'D'),
            "STOP logged before disabling interrupts");
    io.last_status = io.status | (io.reads == io.full_at ? 0x10U : 0U);
    ++io.reads;
    io.events += 'R';
    return io.last_status;
}
void write_byte(uint32_t offset, uint32_t value) {
    require(offset == 0x30U, "unexpected write (only UART FIFO allowed)");
    require(value <= 255U, "byte was sign-extended");
    require(!io.events.empty() && io.events.back() == 'R', "write without status read");
    require((io.last_status & 0x10U) == 0, "write while TX full");
    io.events += 'W';
    io.bytes += static_cast<char>(value);
}
void disable_interrupts() {
    require(io.stopping && io.events.empty(), "unexpected/late/repeated disable");
    io.events += 'D';
}
void park() {
    require(io.stopping, "unexpected park");
    io.events += 'P';
    throw Parked{};  // Observes reachability only; does not prove hardware parking.
}
void reset(size_t limit, size_t full_at = size_t(-1), uint32_t status = 0,
           bool stopping = false) {
    io = Observation{};
    io.limit = limit;
    io.full_at = full_at;
    io.status = status;
    io.stopping = stopping;
    log_host_io = {read_status, write_byte, disable_interrupts, park};
}
void check(const std::string &expected, size_t reads, bool stopping = false) {
    require(io.bytes == expected, "output differs in content/length/order");
    require(io.reads == reads, "wrong read count");
    std::string events = stopping ? "D" : "";
    for (size_t i = 0; i < expected.size(); ++i) events += "RW";
    if (reads == expected.size() + 1U) events += 'R';
    else require(reads == expected.size(), "invalid expected trace");
    if (stopping) events += 'P';
    require(io.events == events, "side-effect ordering differs");
    ++calls;
}
void check_log(const char *text, bool result, const std::string &expected,
               size_t reads, size_t full_at = size_t(-1), uint32_t status = 0) {
    reset(reads, full_at, status);
    require(try_log(text) == result, "wrong try_log result");
    check(expected, reads);
}
void check_stop(const char *reason, const std::string &expected, size_t reads,
                size_t full_at = size_t(-1)) {
    reset(reads, full_at, 0, true);
    bool parked = false;
    try { stop(reason); }
    catch (const Parked &) { parked = true; }
    require(parked, "STOP did not reach park");
    check(expected, reads, true);
}

// Inaccessible next page makes an actual input overread fail, without ASan.
// Private host virtual memory only: not MMIO, device access or a fake board.
class GuardPage {
public:
    GuardPage() {
#if defined(_WIN32)
        SYSTEM_INFO info;
        GetSystemInfo(&info);
        page_ = info.dwPageSize;
        data_ = static_cast<char *>(VirtualAlloc(nullptr, page_ * 2U,
                                                MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        require(data_ != nullptr, "VirtualAlloc failed");
        DWORD old;
        if (!VirtualProtect(data_ + page_, page_, PAGE_NOACCESS, &old)) {
            VirtualFree(data_, 0, MEM_RELEASE);
            throw std::runtime_error("VirtualProtect failed");
        }
#else
        const long page = sysconf(_SC_PAGESIZE);
        require(page > 0, "sysconf failed");
        page_ = static_cast<size_t>(page);
        void *p = mmap(nullptr, page_ * 2U, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        require(p != MAP_FAILED, "mmap failed");
        data_ = static_cast<char *>(p);
        if (mprotect(data_ + page_, page_, PROT_NONE) != 0) {
            munmap(data_, page_ * 2U);
            throw std::runtime_error("mprotect failed");
        }
#endif
    }
    ~GuardPage() {
#if defined(_WIN32)
        VirtualFree(data_, 0, MEM_RELEASE);
#else
        munmap(data_, page_ * 2U);
#endif
    }
    GuardPage(const GuardPage &) = delete;
    GuardPage &operator=(const GuardPage &) = delete;
    char *end() { return data_ + page_; }
private:
    char *data_ = nullptr;
    size_t page_ = 0;
};

// Independent formatting oracle in TEST ONLY; production retains no printf/IO.
std::string expected_bound(uint32_t id) {
    std::ostringstream s;
    s << "S2B UDP PCB bound; boot_id=" << std::hex << std::nouppercase
      << std::setfill('0') << std::setw(8) << id << "; NOT a link/PING PASS\r\n";
    return s.str();
}
void check_bound(uint32_t id) {
    const std::string expected = expected_bound(id);
    reset(expected.size());
    log_bound(id);
    check(expected, expected.size());
}

void run_case(const std::string &name) {
    require(!kLabNetworkConfirmed, "network gate changed");
    if (name.compare(0, 7, "length-") == 0) {
        const size_t n = std::stoul(name.substr(7));
        const std::string text(n, 'a');
        check_log(text.c_str(), n < 96U, text.substr(0, 96), std::min(n, size_t(96)));
    } else if (name.compare(0, 7, "txfull-") == 0) {
        const size_t at = std::stoul(name.substr(7));
        const std::string text(97, 'b');
        check_log(text.c_str(), false, text.substr(0, at), at + 1U, at);
    } else if (name.compare(0, 11, "status-bit-") == 0) {
        const uint32_t status = uint32_t(1) << std::stoul(name.substr(11));
        const bool full = status == 0x10U;
        check_log("xy", !full, full ? "" : "xy", full ? 1U : 2U, size_t(-1), status);
    } else if (name == "status-all") {
        check_log("xy", false, "", 1, size_t(-1), 0xffffffffU);
        check_log("xy", true, "xy", 2, size_t(-1), 0xffffffefU);
    } else if (name == "nul-short-circuit") {
        check_log("", true, "", 0, 0, 0xffffffffU);
        check_log("abc\0DO NOT LOG", true, "abc", 3, 3);
        const std::string text(95, 'n');
        check_log(text.c_str(), true, text, 95, 95);
    } else if (name == "byte-domain") {
        for (unsigned int value = 1; value <= 255; ++value) {
            const char text[] = {static_cast<char>(value), '\0'};
            check_log(text, true, std::string(text, 1), 1);
        }
    } else if (name == "repeated-calls") {
        reset(4, 0);
        require(!try_log("drop"), "full call succeeded");
        require(try_log("ok"), "next call did not recover");
        require(try_log("!"), "third call failed");
        require(io.bytes == "ok!" && io.reads == 4 && io.events == "RRWRWRW",
                "retry, deferred suffix or stale state across calls");
        calls += 3;
    } else if (name == "format-matrix") {
        for (uint32_t id : {0U, 1U, 0x12345678U, 0x89abcdefU, 0xffffffffU,
                            0x80000000U, 0x00abcdefU}) check_bound(id);
        for (unsigned int pos = 0; pos < 8; ++pos)
            for (uint32_t digit = 0; digit < 16; ++digit) check_bound(digit << (4U * pos));
        uint32_t id = 0x13579bdfU;  // deterministic test values, NOT boot identity
        for (unsigned int i = 0; i < 256; ++i) {
            id = id * 1664525U + 1013904223U;
            check_bound(id);
        }
    } else if (name == "format-txfull") {
        const uint32_t id = 0x89abcdefU;
        const std::string expected = expected_bound(id);
        for (size_t at = 0; at < expected.size(); ++at) {
            reset(at + 1U, at);
            log_bound(id);
            check(expected.substr(0, at), at + 1U);
        }
        check_bound(0);  // previous partial output cannot affect the next format
    } else if (name.compare(0, 12, "stop-length-") == 0) {
        const size_t n = std::stoul(name.substr(12));
        const std::string reason(n, 'r');
        const std::string expected = "S2B STOP: " + reason.substr(0, 96) + (n < 96 ? "\r\n" : "");
        check_stop(reason.c_str(), expected, expected.size());
    } else if (name == "stop-txfull") {
        const std::string reason(95, 'r');
        const std::string expected = "S2B STOP: " + reason + "\r\n";
        for (size_t at = 0; at < expected.size(); ++at)
            check_stop(reason.c_str(), expected.substr(0, at), at + 1U, at);
    } else if (name == "stop-embedded-nul") {
        check_stop("why\0hidden", "S2B STOP: why\r\n", 15);
    } else if (name == "guard-pages") {
        GuardPage page;
        for (size_t n : {size_t(0), size_t(1), size_t(94), size_t(95)}) {
            char *s = page.end() - n - 1U;
            std::memset(s, 'g', n);
            s[n] = '\0';
            check_log(s, true, std::string(n, 'g'), n, n);
        }
        char *s = page.end() - 96;
        std::memset(s, 'g', 96);
        check_log(s, false, std::string(96, 'g'), 96);
        check_stop(s, "S2B STOP: " + std::string(96, 'g'), 106);
        // TX-full prefix must not touch reason, even when reason is inaccessible.
        for (size_t at = 0; at < 10; ++at)
            check_stop(page.end(), std::string("S2B STOP: ").substr(0, at), at + 1U, at);
    } else {
        throw std::runtime_error("unknown case: " + name);
    }
}
}

int main(int argc, char **argv) {
    try {
        require(argc == 2, "usage: test_s2b_log CASE");
        run_case(argv[1]);
        require(calls > 0, "empty case");
        std::cout << "S2B_LOG PASS " << argv[1] << " calls=" << calls << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "S2B_LOG FAIL: " << e.what() << '\n';
        return 1;
    } catch (...) {
        std::cerr << "S2B_LOG FAIL: unexpected exception\n";
        return 1;
    }
}
