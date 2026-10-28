# First-round implementation dependency ledger (2026-10-11)

Scope: user-authorized E/F/T2 implementation and A--G acceptance preparation.
No goal, new training, board operation, old P2, performance optimization or
production service replacement is authorized by this implementation ledger.

1. E + T2 hardware foundation: serial K7/DB18 datapath (not overlap/P2), ABI4
   ATTENTION output copied from the exact Q0.24 matrix consumed by CTX. Existing
   CLASS/LOGITS layouts stay unchanged. Real RTL accepted-start to done counter;
   HLS C zero is explicitly not a measurement. Separate IP/system/XSA paths.
2. E PS/transport: bounded output/cache ownership; one in-flight probe; raw
   attention fragments with boot/session/task/request/scene/model/coordinate,
   whole tensor CRC and strict duplicate/conflict/timeout handling.
3. F boot: SD preprovisioned, two-slot monotonic journal, durable reservation
   before READY. No UART input, automatic repair/reseed or bypass on media error.
   Offline provisioning is explicit and never writes removable media. Startup
   package must bind all image components to the final hardware and user ELF.
4. T2 PS: instrument existing numeric loops (validation, extract, normalization,
   embed), cache preparation/completion, submit and engine wait. Wait-service is
   a nested subset; hardware cycles exclude PS, include engine AXI stalls. Keep
   original task-step compute_us and private App buckets distinct.
5. G: only after all candidate paths are ready, derive complete source/assets
   manifest and revision gate; back up and verify unchanged user files before
   a single source sync. No App Build/platform mutation/device operation by agent.
6. A--D cross-regression: identity/recovery/history, three scenes/models, CLASS,
   PROBE, SD model transaction/activation, original PC map and DP, reports and
   timing. RAM/synthetic/host tests never close physical acceptance rows.

All new/affected hardware acceptance remains NOT RUN. Retain SD cold scan,
power-loss safety (specific user-approved procedure), real training/upload/
activation/same-ROI task comparison, full DP/PC inspection and final evidence
audit. Old service PID38476/8765 remains unchanged; bb6bd8e3 is not reusable.
Initial HEAD: 195682b; eight handoff documents dirty, no staged changes. Preserve
all user projects, old artifacts and initial document history. Git commit has
not been explicitly authorized this turn; do not stage unrelated changes.
