#ifndef AGRIEDGE_INA226_H
#define AGRIEDGE_INA226_H
#include <cstdint>

namespace power_monitor {
// The board adapter must implement bounded I2C transactions on CONFIRMED pins.
// This module never configures GPIO, selects pins or searches unknown buses.
struct Bus {
    void *context;
    bool (*read)(void *, uint8_t address, uint8_t reg, uint16_t &value);
    bool (*write)(void *, uint8_t address, uint8_t reg, uint16_t value);
};
struct Config {
    uint8_t address=0x40;
    uint32_t shunt_microohms=0; // R010 = 10000; must be physically confirmed.
    uint32_t maximum_milliamps=0; // Confirm module/connector continuous rating.
    bool wiring_confirmed=false;
};
enum class State : uint8_t { disabled, unidentified, idle, converting, valid,
    io_error, timeout, range_error, reverse_current };
struct Sample {
    State state=State::disabled;
    uint32_t sequence=0;
    uint64_t sampled_us=0;
    uint32_t bus_microvolts=0;
    int32_t shunt_nanovolts=0;
    int32_t current_microamps=0;
    int32_t power_microwatts=0;
};
class Ina226 {
public:
    explicit Ina226(Bus bus):bus_(bus){}
    bool identify(uint8_t address); // Only FE/FF ID reads, never register writes.
    bool configure(const Config &);
    bool start(uint64_t now_us);
    // Call from the foreground loop; no waits/sleeps. True = a new valid sample.
    bool poll(uint64_t now_us);
    const Sample &sample() const {return sample_;}
    static bool convert(uint16_t bus, int16_t shunt, const Config &, Sample &);
private:
    Bus bus_;Config config_{};Sample sample_{};
    bool identified_=false,configured_=false;uint8_t identified_address_=0;
    uint64_t started_=0;
};

// Integrates only adjacent valid samples within the current task. Missing or
// invalid intervals are excluded and reflected in coverage, never extrapolated.
class TaskEnergy {
public:
    void begin(uint32_t task, uint64_t now_us);
    void add(const Sample &);
    void finish(uint64_t now_us);
    uint64_t measured_microjoules() const {return energy_;}
    uint64_t covered_us() const {return covered_;}
    uint64_t duration_us() const {return end_>=start_?end_-start_:0;}
    uint32_t task() const {return task_;}
    bool active() const {return active_;}
private:
    uint32_t task_=0;bool active_=false,previous_=false;
    uint64_t start_=0,end_=0,last_at_=0,energy_=0,covered_=0;
    int32_t last_power_=0;uint32_t last_sequence_=0;
};
} // namespace power_monitor
#endif
