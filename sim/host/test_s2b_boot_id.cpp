// Offline unit harness, not a UART/board emulator or an identity source.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

#if S2B_BOOT_ID_HOST_TEST
// Deliberately reuse the actual candidate in the same translation unit.
// No copied parser, public hook, state reset or second implementation.
#include "../../src/ps/s2b_idle_app/boot_id.cpp"
#include <algorithm>
#include <deque>
#include <vector>
#else
#include "../../src/ps/s2b_idle_app/boot_id.h"
#endif

static void require(bool ok, const char *what) {
    if (!ok) throw std::runtime_error(what);
}

static void production_closed() {
    const uint32_t sentinels[] = {0U, 0x13579bdfU, 0xffffffffU};
    for (uint32_t original : sentinels) {
        uint32_t out = original;
        require(!s2b::acquire_boot_id(out), "production entry opened");
        require(out == original, "production entry changed out");
    }
}

#if S2B_BOOT_ID_HOST_TEST
namespace {
struct Event { uint64_t at; std::string bytes; };
struct Simulation {
    uint64_t frequency = 1000, elapsed = 0, step = 1, base = 0;
    uint64_t first_sample_delay = 0, full_until = 0;
    uint64_t error_at = ~uint64_t(0), jump_at = ~uint64_t(0), jump_to = 0;
    uint32_t error = 0, harmless_status = 0;
    unsigned error_after_read = ~0U, error_after_write = ~0U;
    unsigned reads = 0, writes = 0, clocks = 0, samples = 0, operations = 0;
    uint64_t first_write = 0, last_read = 0;
    std::vector<Event> events;
    std::deque<uint8_t> rx;
    std::string tx;
    size_t event_index = 0;
    bool forever_full = false, forbidden = false;

    void count() {
        require(!forbidden, "cached/latched/stub call touched platform");
        require(++operations < 300000U, "harness watchdog (not candidate timeout)");
    }
    void arrivals() {
        while (event_index < events.size() && events[event_index].at <= elapsed) {
            for (unsigned char ch : events[event_index].bytes) rx.push_back(ch);
            ++event_index;
        }
    }
    uint64_t now() {
        count();
        ++clocks;
        if (clocks == 2U) elapsed += first_sample_delay;
        if (elapsed >= jump_at) { elapsed = jump_to; jump_at = ~uint64_t(0); }
        const uint64_t result = base + elapsed;
        elapsed += step;
        return result;
    }
    uint32_t read(uint32_t offset) {
        count();
        // Independent literal register map, checked by the runner against BSP.
        if (offset == 0x2cU) {
            ++samples;
            arrivals();
            return (rx.empty() ? 0x02U : 0U) |
                   ((forever_full || elapsed < full_until) ? 0x10U : 0U);
        }
        if (offset == 0x14U) {
            return harmless_status | ((elapsed >= error_at ||
                reads >= error_after_read || writes >= error_after_write) ? error : 0U);
        }
        require(offset == 0x30U, "unexpected register read");
        require(!rx.empty(), "FIFO read without available byte");
        require(++reads <= 74U, "r1 RX byte cap exceeded");
        last_read = elapsed;
        const uint8_t byte = rx.front(); rx.pop_front();
        return byte;
    }
    void write(uint32_t offset, uint32_t value) {
        count();
        require(offset == 0x30U, "write outside TX FIFO (reset/config/clear)");
        require(!forever_full && elapsed >= full_until, "write while TX full");
        require(++writes <= 64U && value <= 255U, "r1 TX limit/value exceeded");
        if (writes == 1U) first_write = elapsed;
        tx.push_back(static_cast<char>(value));
    }
} sim;
uint64_t now() { return sim.now(); }
uint32_t read(uint32_t offset) { return sim.read(offset); }
void write(uint32_t offset, uint32_t value) { sim.write(offset, value); }

struct Expect {
    bool success = false;
    uint32_t value = 0x1234abcdU;
    int reads = -1, writes = -1;
    uint64_t earliest = 0, latest = ~uint64_t(0), first_write_min = 0;
};

Expect configure(const std::string &mode) {
    Expect e;
    std::string frame = "1234aBcD\n";
    uint64_t frame_at = 200;
    bool add_frame = true;
    if (mode == "lf" || mode == "crlf" || mode == "zero" || mode == "max" ||
        mode == "upper" || mode == "wrap" || mode == "rx-trigger" ||
        mode == "fractional-frequency" || mode == "high-frequency" ||
        mode == "delayed-after-success") {
        e.success = true;
        if (mode == "crlf") frame = "1234aBcD\r\n";
        if (mode == "zero") { frame = "00000000\n"; e.value = 0; }
        if (mode == "max") { frame = "ffffffff\n"; e.value = 0xffffffffU; }
        if (mode == "upper") frame = "1234ABCD\n";
        if (mode == "wrap") sim.base = ~uint64_t(0) - 100U;
        if (mode == "rx-trigger") sim.harmless_status = 0x01U;
        if (mode == "fractional-frequency") sim.frequency = 1001;
        if (mode == "high-frequency") {
            sim.frequency = 1000000; sim.step = 1000; frame_at = 200000;
        }
        if (mode == "delayed-after-success") sim.events.push_back({241, "old-line\n"});
        e.reads = static_cast<int>(frame.size()); e.writes = 37;
    } else if (mode == "empty" || mode == "missing-eol" || mode == "cr-only" ||
               mode == "partial") {
        if (mode == "empty") frame.clear();
        if (mode == "missing-eol") frame = "1234abcd";
        if (mode == "cr-only") frame = "1234abcd\r";
        if (mode == "partial") frame = "123";
        e.earliest = 60000; e.latest = 60001;
        e.reads = static_cast<int>(frame.size());
    } else if (mode.compare(0, 4, "bad-") == 0) {
        const int byte = std::stoi(mode.substr(4));
        require(byte >= 0 && byte <= 255, "invalid test byte");
        frame[3] = static_cast<char>(byte); e.reads = 4;
    } else if (mode.compare(0, 9, "position-") == 0) {
        const unsigned pos = static_cast<unsigned>(std::stoul(mode.substr(9)));
        require(pos < 8, "invalid digit position"); frame[pos] = 'g'; e.reads = pos + 1;
    } else if (mode == "short-line") { frame = "1234567\n"; e.reads = 8;
    } else if (mode == "ninth-digit") { frame = "1234abcd0\n"; e.reads = 9;
    } else if (mode == "prefix") { frame = "0x1234abcd\n"; e.reads = 2;
    } else if (mode == "space") { frame = " 1234abcd\n"; e.reads = 1;
    } else if (mode == "crcrlf") { frame = "1234abcd\r\r\n"; e.reads = 10;
    } else if (mode == "trailing-space") { frame = "1234abcd \n"; e.reads = 9;
    } else if (mode == "lfcr") { frame = "1234abcd\n\r"; e.reads = 9;
    } else if (mode == "double-line") { frame += "87654321\n"; e.reads = 9;
    } else if (mode == "burst") { frame += std::string(1000, 'f'); e.reads = 9;
    } else if (mode == "tail-before" || mode == "tail-equal" || mode == "tail-final") {
        sim.events.push_back({mode == "tail-before" ? 237U :
                              mode == "tail-equal" ? 238U : 239U, "!"});
        e.reads = 9;
    } else if (mode == "residue64" || mode == "residue65" || mode == "residue-max-frame") {
        sim.frequency = 10000; frame_at = 2000;
        const unsigned count = mode == "residue65" ? 65 : 64;
        sim.events.push_back({0, std::string(count, 'x')});
        if (mode == "residue-max-frame") frame = "1234abcd\r\n";
        e.success = count == 64;
        e.reads = count == 64 ? 64 + static_cast<int>(frame.size()) : 64;
        e.writes = count == 64 ? 37 : 0;
    } else if (mode == "residue-quiet-reset") {
        sim.events.push_back({0, "x"}); sim.events.push_back({20, "y"});
        e.success = true; e.reads = 11; e.first_write_min = 43;
    } else if (mode == "first-empty-delay") {
        sim.first_sample_delay = 70;
        e.success = true; e.first_write_min = 94;
    } else if (mode == "residue-equal" || mode == "residue-before") {
        sim.first_sample_delay = mode == "residue-equal" ? 79 : 78;
        e.success = mode == "residue-before";
        if (!e.success) { e.writes = 0; e.reads = 0; e.earliest = 100; e.latest = 101; }
    } else if (mode == "residue-active") {
        for (unsigned t = 0; t < 100; t += 10) sim.events.push_back({t, "x"});
        e.writes = 0; e.earliest = 100; e.latest = 101;
    } else if (mode == "prompt-full" || mode == "prompt-before" || mode == "prompt-equal") {
        frame_at = 1200;
        sim.forever_full = mode == "prompt-full";
        sim.full_until = mode == "prompt-before" ? 984 : 985;
        e.success = mode == "prompt-before";
        if (!e.success) { e.reads = 0; e.earliest = 1022; e.latest = 1023; }
        e.writes = mode == "prompt-full" ? 0 : 37;
    } else if (mode == "prompt-rx" || mode == "prompt-final-rx") {
        sim.events.push_back({mode == "prompt-rx" ? 30U : 60U, "x"});
        e.reads = 0; e.writes = mode == "prompt-rx" ? 7 : 37;
    } else if (mode == "total-before" || mode == "total-equal" || mode == "total-first-byte") {
        frame_at = mode == "total-before" ? 59960 : mode == "total-equal" ? 59961 : 60000;
        e.success = mode == "total-before";
        e.reads = mode == "total-first-byte" ? 0 : 9;
        e.latest = 60001; e.earliest = 60000;
    } else if (mode == "total-after-pop") {
        frame_at = 59999; e.reads = 1; e.earliest = 60000; e.latest = 60001;
    } else if (mode == "slow-drip") {
        add_frame = false;
        for (unsigned i = 0; i < 8; ++i) sim.events.push_back({200U + i * 7000U, frame.substr(i, 1)});
        sim.events.push_back({60000, "\n"}); e.reads = 8;
        e.earliest = 60000; e.latest = 60001;
    } else if (mode == "prompt-total" || mode == "residue-total") {
        sim.jump_at = mode == "prompt-total" ? 30 : 10; sim.jump_to = 60000;
        e.reads = 0; e.writes = mode == "prompt-total" ? 7 : 0; e.latest = 60001;
    } else if (mode == "frequency-zero" || mode == "frequency-overflow" || mode == "frequency-low") {
        sim.frequency = mode == "frequency-zero" ? 0 : mode == "frequency-low" ? 1 : ~uint64_t(0);
        e.reads = 0; e.writes = 0;
    } else if (mode.compare(0, 6, "error-") == 0) {
        const size_t sep = mode.find('-', 6);
        require(sep != std::string::npos, "bad error mode");
        sim.error = static_cast<uint32_t>(std::stoul(mode.substr(6, sep - 6)));
        const std::string phase = mode.substr(sep + 1);
        if (phase == "residue") { sim.error_at = 0; e.reads = 0; e.writes = 0; }
        else if (phase == "after-discard") {
            sim.events.push_back({0, "x"}); sim.error_after_read = 1; e.reads = 1; e.writes = 0;
        } else if (phase == "prompt") { sim.error_after_write = 1; e.reads = 0; e.writes = 1; }
        else if (phase == "prompt-final") { sim.error_after_write = 37; e.reads = 0; e.writes = 37; }
        else if (phase == "frame") { sim.error_at = 200; e.reads = 0; }
        else if (phase == "after-pop") { sim.error_after_read = 1; e.reads = 1; }
        else if (phase == "after-eol") { sim.error_after_read = 9; e.reads = 9; }
        else if (phase == "tail") { sim.error_at = 230; e.reads = 9; }
        else if (phase == "final") { sim.error_at = 239; e.reads = 9; }
        else throw std::runtime_error("unknown error phase");
    } else throw std::runtime_error("unknown case");
    if (add_frame && !frame.empty()) sim.events.push_back({frame_at, frame});
    std::stable_sort(sim.events.begin(), sim.events.end(),
        [](const Event &a, const Event &b) { return a.at < b.at; });
    return e;
}

void run_case(const std::string &mode) {
    const Expect e = configure(mode);
    s2b::boot_id_host_io = {sim.frequency, now, read, write};
    sim.forbidden = true; production_closed(); sim.forbidden = false;
    uint32_t out = 0xdeadbeefU;
    const bool ok = s2b::Uart0BootIdCandidate::acquire(out);
    std::cout << "observed success=" << ok << " out=" << out << " ticks=" << sim.elapsed
              << " rx=" << sim.reads << " tx=" << sim.writes
              << " first_tx=" << sim.first_write << " operations=" << sim.operations << '\n';
    require(ok == e.success, "candidate result mismatch");
    require(out == (e.success ? e.value : 0xdeadbeefU), "out commit/failure preservation");
    if (e.reads >= 0) require(sim.reads == static_cast<unsigned>(e.reads), "RX count mismatch");
    if (e.writes >= 0) require(sim.writes == static_cast<unsigned>(e.writes), "TX count mismatch");
    require(sim.elapsed >= e.earliest && sim.elapsed <= e.latest, "deadline boundary mismatch");
    require(sim.first_write >= e.first_write_min, "quiet interval started before empty observation");
    const std::string prompt = "S2B BOOT_ID: 8 hex digits + LF/CRLF\r\n";
    require(sim.tx == prompt.substr(0, sim.tx.size()), "prompt bytes mismatch");
    if (ok) require(sim.tx == prompt, "success without complete prompt");
    // The same real entry stays closed even after private candidate success.
    sim.forbidden = true; production_closed();
    const unsigned prior_operations = sim.operations;
    // Change all platform conditions; a repeated call must not inspect them.
    sim.frequency = 0; sim.error = 0xe0; sim.error_at = 0;
    sim.forever_full = true; sim.rx.push_back('!'); sim.elapsed += 100000;
    for (uint32_t sentinel : {0U, 0x87654321U, 0xffffffffU}) {
        uint32_t again = sentinel;
        require(s2b::Uart0BootIdCandidate::acquire(again) == ok, "latch/cache changed result");
        require(again == (ok ? e.value : sentinel), "latch/cache changed output");
    }
    require(sim.operations == prior_operations, "repeat touched platform");
}
}  // namespace
#endif

int main(int argc, char **argv) {
    try {
#if S2B_BOOT_ID_HOST_TEST
        require(argc == 2, "one case per fresh process required");
        run_case(argv[1]);
        std::cout << "S2B_BOOT_ID PASS " << argv[1] << '\n';
#else
        (void)argc; (void)argv;
        production_closed();
        std::cout << "S2B_BOOT_ID DEFAULT_OFF PASS\n";
#endif
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "S2B_BOOT_ID FAIL: " << e.what() << '\n'; return 1;
    }
}
