// Newly connected production entry only. Deterministic unit IO: no device,
// entropy source, socket, or board emulation. One process per boot lifetime.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include "../../src/ps/s2b_idle_app/boot_id.cpp"

namespace {
uint64_t clock_ticks = 0;
unsigned operations = 0, consumed = 0;
bool forbidden = false, uart_error = false;
std::string frame, prompt;
void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
void operation() {
    check(!forbidden, "latched entry accessed IO");
    check(++operations < 300000U, "test watchdog");
}
uint64_t now() { operation(); return clock_ticks++; }
uint32_t read(uint32_t offset) {
    operation();
    const bool available = clock_ticks >= 200 && consumed < frame.size();
    if (offset == 0x2cU) return available ? 0U : 2U;
    if (offset == 0x14U) return uart_error ? 0x20U : 0U;
    check(offset == 0x30U && available, "unexpected FIFO read");
    return static_cast<uint8_t>(frame[consumed++]);
}
void write(uint32_t offset, uint32_t value) {
    operation();
    check(offset == 0x30U && value <= 255U, "unexpected UART write");
    prompt.push_back(static_cast<char>(value));
}
}

int main(int argc, char **argv) {
    try {
        check(argc == 2, "one case per process");
        const std::string mode = argv[1];
        bool success = false;
        uint32_t expected = 0;
        if (mode == "entry-lf") {
            frame = "1234aBcD\n"; success = true; expected = 0x1234abcdU;
        } else if (mode == "entry-zero-crlf") {
            frame = "00000000\r\n"; success = true;
        } else if (mode == "entry-invalid") frame = "1234abcg\n";
        else if (mode == "entry-timeout") frame = "";
        else if (mode == "entry-uart-error") uart_error = true;
        else throw std::runtime_error("unknown case");
        s2b::boot_id_host_io = {1000, now, read, write};
        uint32_t out = 0xdeadbeefU;
        const bool actual = s2b::acquire_boot_id(out);
        check(actual == success, "production entry result");
        check(out == (success ? expected : 0xdeadbeefU), "output commit/preservation");
        if (!uart_error)
            check(prompt == "S2B BOOT_ID: 8 hex digits + LF/CRLF\r\n", "r1 prompt");
        check(operations > 0, "production entry did not acquire");
        const unsigned prior = operations;
        forbidden = true;
        for (uint32_t sentinel : {0U, 0x87654321U, 0xffffffffU}) {
            uint32_t again = sentinel;
            check(s2b::acquire_boot_id(again) == success, "entry result not latched");
            check(again == (success ? expected : sentinel), "entry cache/output");
        }
        check(operations == prior, "repeat entry touched IO");
        std::cout << "S2B_CONNECTED PASS " << mode << " operations=" << operations << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "S2B_CONNECTED FAIL " << e.what() << '\n';
        return 1;
    }
}
