#include "boot_id.h"

// Private, host-only IO adaptation. Production uses the existing BSP UART0.
#ifndef S2B_BOOT_ID_HOST_TEST
#define S2B_BOOT_ID_HOST_TEST 0
#endif
#if S2B_BOOT_ID_HOST_TEST != 0 && S2B_BOOT_ID_HOST_TEST != 1
#error S2B_BOOT_ID_HOST_TEST must be 0 or 1
#endif
#if !S2B_BOOT_ID_HOST_TEST
#include "xparameters.h"
#include "xtime_l.h"
#include "xuartps_hw.h"
#endif

namespace s2b {
namespace {

#if S2B_BOOT_ID_HOST_TEST
#if defined(__aarch64__) || defined(__arm__)
#error The private test adapter must not be used in a target App
#endif
// Register identifiers/bits from the existing 2020.2 xuartps_hw.h.
// Simulated observations only: no host MMIO or fake board.
constexpr uint32_t XUARTPS_ISR_OFFSET = 0x14U;
constexpr uint32_t XUARTPS_SR_OFFSET = 0x2cU;
constexpr uint32_t XUARTPS_FIFO_OFFSET = 0x30U;
constexpr uint32_t XUARTPS_SR_RXEMPTY = 0x02U;
constexpr uint32_t XUARTPS_SR_TXFULL = 0x10U;
constexpr uint32_t XUARTPS_IXR_OVER = 0x20U;
constexpr uint32_t XUARTPS_IXR_FRAMING = 0x40U;
constexpr uint32_t XUARTPS_IXR_PARITY = 0x80U;
struct BootIdHostIo {
    uint64_t frequency;
    uint64_t (*now)();
    uint32_t (*read)(uint32_t offset);
    void (*write)(uint32_t offset, uint32_t value);
};
// Same-translation-unit tests only. No reset hook: one process per lifetime.
BootIdHostIo boot_id_host_io = {};
#endif

inline uint32_t uart_read(uint32_t offset) {
#if S2B_BOOT_ID_HOST_TEST
    return boot_id_host_io.read(offset);
#else
    return XUartPs_ReadReg(XPAR_XUARTPS_0_BASEADDR, offset);
#endif
}

inline void uart_write(uint32_t offset, uint32_t value) {
#if S2B_BOOT_ID_HOST_TEST
    boot_id_host_io.write(offset, value);
#else
    XUartPs_WriteReg(XPAR_XUARTPS_0_BASEADDR, offset, value);
#endif
}

// Approved r1 acquisition. No global hardware initialization.
// Private host adaptation does not change the parser or acquisition state.
// Production connection authorized 2026-10-10; device execution remains separate.
// Requires exclusive UART0 ownership and a PS-initialized independent cold boot;
// it must never run over a live C3/ROI App or an outstanding DMA operation.
class Uart0BootIdCandidate {
public:
    static bool acquire(uint32_t &out) {
        // One attempt per initialization lifetime, not per terminal connection.
        // No reset/retry API. Repeated success does not touch UART or the clock.
        enum State { Untried, Failed, Succeeded };
        static State state = Untried;
        static uint32_t cached = 0;
        if (state == Succeeded) {
            out = cached;
            return true;
        }
        if (state != Untried) return false;
        state = Failed;  // latch before any operation; every early return fails

        const uint64_t start = ticks_now();
        Budgets limits;
        if (!make_budgets(limits)) return false;
        uint32_t candidate = 0;  // zero is valid; never a failure fallback
        if (!discard_residue(start, limits) || !send_prompt(start, limits) ||
            !read_frame(start, limits, candidate) ||
            !wait_tail(start, limits)) return false;

        // Final observed RX/error/deadline check, not an atomic hardware fence
        // against a byte arriving later. Only now may the local value commit.
        Snapshot final_sample;
        if (!observe(start, limits, final_sample) ||
            has_rx(final_sample)) return false;
        cached = candidate;
        state = Succeeded;
        out = candidate;
        return true;
    }

private:
    struct Budgets {
        uint64_t total, residue, prompt, quiet;
    };
    struct Snapshot {
        uint64_t at;
        uint32_t channel;
    };

    static uint64_t ticks_now() {
#if S2B_BOOT_ID_HOST_TEST
        return boot_id_host_io.now();
#else
        XTime value;
        // Current EL3 BSP may ENABLE a disabled counter via StartTimer.
        // Not unconditionally read-only; device authorization must cover this.
        XTime_GetTime(&value);
        return static_cast<uint64_t>(value);
#endif
    }

    static bool ms_to_ticks(uint64_t ms, uint64_t &ticks) {
#if S2B_BOOT_ID_HOST_TEST
        const uint64_t frequency = boot_id_host_io.frequency;
#else
        const uint64_t frequency = static_cast<uint64_t>(COUNTS_PER_SECOND);
#endif
        const uint64_t maximum = ~uint64_t(0);
        // Checked multiply + ceil; reject invalid/ambiguous timer budgets.
        if (frequency == 0 || ms == 0 ||
            frequency > (maximum - 999U) / ms) return false;
        ticks = (frequency * ms + 999U) / 1000U;
        return ticks != 0 && ticks < (uint64_t(1) << 63);
    }

    static bool make_budgets(Budgets &limits) {
        return ms_to_ticks(60000, limits.total) &&
               ms_to_ticks(100, limits.residue) &&
               ms_to_ticks(1000, limits.prompt) &&
               ms_to_ticks(20, limits.quiet);
    }

    static bool observe(uint64_t start, const Budgets &limits, Snapshot &s) {
        // Read status only: never clear sticky errors or reset/configure UART.
        // IXR_OVER is overrun; IXR_RXOVR is merely the RX FIFO trigger.
        s.channel = uart_read(XUARTPS_SR_OFFSET);
        const uint32_t errors = uart_read(XUARTPS_ISR_OFFSET);
        s.at = ticks_now();
        const uint32_t mask = XUARTPS_IXR_OVER | XUARTPS_IXR_FRAMING |
                              XUARTPS_IXR_PARITY;
        // Unsigned elapsed supports a single counter wrap, not a reset/stall.
        // Equality expires. No byte/phase progress ever renews this deadline.
        return (errors & mask) == 0 && s.at - start < limits.total;
    }

    static bool has_rx(const Snapshot &s) {
        return (s.channel & XUARTPS_SR_RXEMPTY) == 0;
    }

    static uint8_t pop_rx() {
        // Call only after nonempty status and a byte-budget check. Unlike
        // RecvByte this performs one FIFO read with no internal waiting loop.
        return static_cast<uint8_t>(uart_read(XUARTPS_FIFO_OFFSET));
    }

    static bool discard_residue(uint64_t start, const Budgets &limits) {
        uint64_t quiet_start = start;
        bool observing_quiet = false;
        unsigned int discarded = 0;
        for (;;) {
            Snapshot s;
            if (!observe(start, limits, s) ||
                s.at - start >= limits.residue) return false;
            if (has_rx(s)) {
                // At 64 reads, only inspect status: never drain a 65th byte.
                if (discarded == 64U) return false;
                (void)pop_rx();
                ++discarded;
                Snapshot after;
                if (!observe(start, limits, after) ||
                    after.at - start >= limits.residue) return false;
                quiet_start = after.at;
                observing_quiet = !has_rx(after);
            } else {
                // Start at an observed empty FIFO, not at function entry.
                if (!observing_quiet) {
                    quiet_start = s.at;
                    observing_quiet = true;
                } else if (s.at - quiet_start >= limits.quiet) {
                    return true;
                }
            }
        }
    }

    static bool send_prompt(uint64_t start, const Budgets &limits) {
        // Dormant candidate text, not an authorized live injection procedure.
        static const char prompt[] = "S2B BOOT_ID: 8 hex digits + LF/CRLF\r\n";
        static_assert(sizeof(prompt) - 1U <= 64U, "r1 prompt byte budget");
        const uint64_t phase_start = ticks_now();
        unsigned int sent = 0;
        for (;;) {
            Snapshot s;
            if (!observe(start, limits, s) || has_rx(s) ||
                s.at - phase_start >= limits.prompt) return false;
            // Also checks deadline/RX/errors AFTER the last FIFO write.
            if (sent == sizeof(prompt) - 1U) return true;
            if ((s.channel & XUARTPS_SR_TXFULL) == 0) {
                uart_write(XUARTPS_FIFO_OFFSET,
                           static_cast<uint8_t>(prompt[sent]));
                ++sent;
            }
        }
        // FIFO enqueue is NOT proof that the terminal displayed the prompt.
        // No SendByte/printf, TX-empty wait, RX read or timer renewal here.
    }

    static bool read_byte(uint64_t start, const Budgets &limits,
                          unsigned int &received, uint8_t &byte) {
        if (received >= 10U) return false;
        for (;;) {
            Snapshot s;
            if (!observe(start, limits, s)) return false;
            if (has_rx(s)) {
                const uint8_t next = pop_rx();
                ++received;
                Snapshot after;
                if (!observe(start, limits, after)) return false;
                byte = next;
                return true;
            }
        }
    }

    static bool hex_digit(uint8_t byte, uint32_t &nibble) {
        if (byte >= '0' && byte <= '9') nibble = byte - '0';
        else if (byte >= 'a' && byte <= 'f') nibble = byte - 'a' + 10U;
        else if (byte >= 'A' && byte <= 'F') nibble = byte - 'A' + 10U;
        else return false;
        return true;
    }

    static bool read_frame(uint64_t start, const Budgets &limits,
                           uint32_t &candidate) {
        unsigned int received = 0;
        uint32_t value = 0;
        for (unsigned int digit = 0; digit != 8U; ++digit) {
            uint8_t byte;
            uint32_t nibble;
            if (!read_byte(start, limits, received, byte) ||
                !hex_digit(byte, nibble)) return false;
            value = (value << 4) | nibble;  // exactly eight u32-safe nibbles
        }
        uint8_t end;
        if (!read_byte(start, limits, received, end)) return false;
        if (end == '\r') {
            if (!read_byte(start, limits, received, end)) return false;
        }
        if (end != '\n') return false;  // no trim, correction or resync
        candidate = value;  // still acquisition-local, NOT the caller's out
        return true;
    }

    static bool wait_tail(uint64_t start, const Budgets &limits) {
        Snapshot first;
        if (!observe(start, limits, first) || has_rx(first)) return false;
        const uint64_t phase_start = first.at;
        for (;;) {
            Snapshot s;
            if (!observe(start, limits, s) || has_rx(s)) return false;
            if (s.at - phase_start >= limits.quiet) return true;
            // Never pop extra bytes. Delayed later lines remain undetectable.
        }
    }
};

}  // namespace

bool acquire_boot_id(uint32_t &out) {
    // PC CSPRNG -> manual UART0, under the approved r1 out-of-band contract.
    // No local entropy/fallback: freshness is an operator obligation, not proof
    // furnished by this parser. Failure preserves out and latches until cold boot.
    return Uart0BootIdCandidate::acquire(out);
}
}  // namespace s2b
