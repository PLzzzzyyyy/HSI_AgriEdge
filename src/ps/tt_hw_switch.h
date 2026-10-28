#ifndef TT_HW_SWITCH_H
#define TT_HW_SWITCH_H
#include "tt_hw.h"

// 应用为单线程；正常在两次完整前向之间切换。切换前会等待已启动的投影完成。
enum TTBackend { TT_BACKEND_PL, TT_BACKEND_PS };
int tt_hw_select(TTBackend backend);  // PL 首次选择时初始化驱动；失败保留原模式
TTBackend tt_hw_backend();
const char *tt_hw_backend_name();

#endif
