"""Generate fixed DP artwork from installed OFL Noto Sans SC (no SD font file).

Only this private App's label header is written. Font binary is not distributed.
"""
import argparse
import hashlib
import json
import ast
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, __version__

ROOT=Path(__file__).resolve().parents[1]
LABELS=[('TITLE','无人机高光谱张量农情分析系统',24),('SCENE','龙口 / v2 · 二维分类图',20),
        ('READY','等待地面站任务',22),('RUNNING','正在推理',22),
        ('DONE','推理完成',22),('FAILED','失败 · 保留已提交结果',22),
        ('TASK','任务 · 整景巡检',20),('PROGRESS','已处理',18),('LEGEND','类别图例',18),
        ('STRUCTURE','种植结构',20),('TELEMETRY','遥测',20),
        ('RATE','像素 / 秒（计算）',16),('LATENCY','毫秒 / 像素',16),
        ('UNMEASURED','未测',28),('POWER','功率 / 温度 / 能耗：未测',17),
        ('SOURCE','DP与电脑同步显示 · 同一份板端分类结果',18),
        ('EMPTY','未完成区域留空；图像比例、类别颜色与地面站一致',18),
        ('FAULT','外部PL复位后才可重新推理',18)]
LABELS += [(f'CLASS{i}',s,18) for i,s in enumerate(('玉米','棉花','芝麻','阔叶大豆','窄叶大豆','水稻','水体','道路与房屋','混合杂草'))]

LABELS += [(f'SCENE{i}',s+' · 二维分类图',20) for i,s in enumerate(('龙口','洪湖','汉川'))]
LABELS += [('NO_TASK','等待任务 · 尚未选择模型',20)]
LABELS += [('REJECT','输入或模型准备失败 · 未开始计算',18)]
SCENE_CLASSES={}
CHINESE_CLASSES={
    'honghu':['红色屋顶','道路','裸土','棉花','棉秆','油菜','大白菜','小白菜','甘蓝','榨菜','菜心','青菜','小青菜',
              '生菜','莴笋','覆膜生菜','罗马生菜','胡萝卜','白萝卜','蒜苗','蚕豆','树木'],
    'hanchuan':['草莓','豇豆','大豆','高粱','空心菜','西瓜','青菜','树木','草地','红色屋顶','灰色屋顶','塑料','裸土','道路','高亮物体','水体'],
}
for scene,size in [('honghu',16),('hanchuan',16)]:
    palette=json.loads((ROOT/f'gcs/scenes/{scene}/palette.json').read_text(encoding='utf-8'))
    SCENE_CLASSES[scene]=CHINESE_CLASSES[scene]
    if len(SCENE_CLASSES[scene])!=len(palette['classes'])-1:raise ValueError('Display class count differs from palette')
    LABELS += [(f'{scene.upper()}_{i}',name,size) for i,name in enumerate(SCENE_CLASSES[scene])]

LABELS += [(name,text,size) for name,text,size in [
    ('TASK_SCAN','整景巡检',36),('TASK_REGION','区域识别',36),('TASK_WAIT','等待任务',36),
    ('STATE_PREP','正在加载输入',24),('STATE_RUNNING','正在推理',24),('STATE_DONE','已完成',24),
    ('STATE_PAUSED','已暂停',24),('STATE_STOPPED','已停止',24),('STATE_FAILED','任务失败',24),
    ('DIMENSION','行 × 列',20),('ROW','行',22),('COL','列',22),('COMPUTED','已计算',20),
    ('BOARD_TASK','板端任务',18),('AREA_SCAN','整景分类面积',24),('AREA_REGION','当前矩形分类面积',24),
    ('AREA_BASIS','仅统计板端已计算像素',16),('AREA_CLASS','类别',18),('AREA_M2','面积（平方米）',18),
    ('AREA_SHARE','占比',18),('AREA_PIXELS','像素',18),('AREA_TOTAL','已计算总面积',18),
    ('PROBE_TITLE','单点探查',28),('PROBE_EMPTY','尚无探查结果',20),('PROBE_RUNNING','板端正在探查',20),
    ('PROBE_DONE','最近一次探查',18),('PROBE_FAILED','探查失败',20),('PROBE_CONF','置信度',18),
    ('PROBE_ATTN','完整注意力已生成',16),('PROBE_ONLY','独立探查不计入区域统计',16),
    ('SYSTEM','系统状态',22),('LINK_WAIT','等待 PC 连接',22),('LINK_ON','PC 通信正常',22),
    ('LINK_TIMEOUT','未收到 PC 消息',22),('LINK_AGE','距最近消息',18),
    ('COMMAND_IDLE','待机',22),('COMMAND_PC','正在执行PC端指令',22),
    ('COMMAND_TERMINAL','正在执行终端指令',22),
    ('HINT_START','请在 PC 控制台开始识别',16),('HINT_RECOVER','请在 PC 开始按钮旁恢复连接',16),
    ('HINT_RUNNING','当前任务正在运行',16),('HINT_PREP','正在准备数据，请稍候',16),
    ('HINT_PAUSED','请在 PC 继续或停止任务',16),('HINT_NEXT','可在 PC 下发下一任务',16),
    ('RETAIN','已完成的分类结果保留',16),('GSD_HINT','面积按 GSD 换算；行列从 0 开始',16),
    ('SCOPE_HINT','青框：实际任务范围；灰色：尚无分类结果',18),
    ('PARCEL_HINT','地块：在 PC 台账选择并同步',16),
    ('UNMEASURED_HINT','功耗与能耗 · 板端同步显示',16),
    ('POWER_EST','芯片功耗',18),('ENERGY_EST','本任务能耗',16),
    ('POWER_MODEL','任务计时与温度同步',14),
    ('POWER_FALLBACK','温度暂不可用',14),
    ('PARCEL_TITLE','地块统计',24),('PARCEL_TOTAL','地块总面积',16),('PARCEL_SEEN','已识别面积',16),
    ('PARCEL_COVER','识别覆盖率',16),('PARCEL_FULL','完整覆盖',18),('PARCEL_PART','部分覆盖',18),
    ('PARCEL_NONE','任务未覆盖此地块',16),('PARCEL_MAIN','主要类别',16),('PARCEL_SHARE','主类占比',16),
    ('PARCEL_MIX','混杂比例',16),('PARCEL_LOW','低置信占比',16),
    ('PARCEL_SOURCE','PC 汇总，基于板卡分类结果',16),('PARCEL_SCOPE','仅统计地块内已接收像素；未识别不外推',14),
    ('PARCEL_LOCAL_SOURCE','板端本地统计，基于实际分类结果',16),
    ('PARCEL_LOCAL_LIVE','板端地块统计',16),('PARCEL_LOCAL_NAME','按键地块',20),
    ('PARCEL_STALE','更新已暂停，保留上次统计',16),('PARCEL_LIVE','地块统计同步中',16),
    ('CHIP_TEMP','芯片温度',20),('TEMP_PEAK','本次启动峰值',16),('TEMP_FAIL','温度读取不可用',16),
    ('FAULT_HINT','任务失败，请在 PC 查看错误',16),
    ('DISPATCH_TITLE','任务下发状态',24),('DISPATCH_NONE','尚无任务指令',18),
    ('DISPATCH_PC','来源：PC 控制台',18),('DISPATCH_K5_ONE','来源：KEY5 单击',18),
    ('DISPATCH_K5_TWO','来源：KEY5 双击',18),('DISPATCH_K5_HOLD','来源：KEY5 长按',18),
    ('DISPATCH_K6_ONE','来源：KEY6 单击',18),('DISPATCH_K6_TWO','来源：KEY6 双击',18),
    ('DISPATCH_K6_HOLD','来源：KEY6 长按',18),('DISPATCH_ACTION','动作：',18),
    ('DISPATCH_POINT','单点探查',18),('DISPATCH_SCAN','整景巡检',18),('DISPATCH_REGION','矩形区域识别',18),
    ('DISPATCH_PARCEL','地块外接框识别',18),('DISPATCH_SCENE','切换场景',18),
    ('DISPATCH_PAUSE','暂停任务',18),('DISPATCH_RESUME','继续任务',18),('DISPATCH_STOP','停止任务',18),
    ('DISPATCH_WAIT','等待后台接收',18),('DISPATCH_RECEIVED','指令已接收，等待执行',18),
    ('DISPATCH_PREP','加载输入，等待首批结果',18),('DISPATCH_RUNNING','任务正在执行',18),
    ('DISPATCH_DONE','本次操作已完成',18),('DISPATCH_FAILED','操作失败，请在 PC 查看日志',16),
    ('DISPATCH_SELECTED','场景已选中，等待下发任务',16),
    ('KEY_GUIDE5','KEY5 单击：单点；双击：整景',14),
    ('KEY_GUIDE6','KEY6 单击：矩形；双击：地块',14),
    ('KEY_GUIDE_HOLD','两键各自长按2秒：切景；KEY7复位',14),
]]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font',type=Path,default=Path('C:/Windows/Fonts/NotoSansSC-VF.ttf'))
    parser.add_argument('--report',type=Path,default=ROOT/'build/host/gcs_models_font_manifest.json')
    args=parser.parse_args()
    tree=ast.parse((ROOT/'gcs/engine.py').read_text(encoding='utf-8'))
    mission=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MISSION' for t in n.targets))
    metadata={ast.literal_eval(k):v for k,v in zip(mission.keys,mission.values)}
    gsd_mm=[round(ast.literal_eval(next(k.value for k in metadata[s].keywords if k.arg=='gsd_m'))*1000)
            for s in ('longkou','honghu','hanchuan')]
    records=[]
    parts=['// Generated fixed label artwork. Noto Sans SC / SIL OFL 1.1; see docs/licenses/notosanssc_ofl.txt.\n'
           '// Reproduce with tools/generate_gcs_dp_labels.py; no font binary or model data.\n'
           '#ifndef S2C_ROI_LABELS_H\n#define S2C_ROI_LABELS_H\nnamespace s2c { namespace labels {\n'
           'struct Bitmap { unsigned w,h; const unsigned char *bits; };\n']
    for name,text,size in LABELS:
        font=ImageFont.truetype(str(args.font),size)
        if hasattr(font,'get_variation_axes'):
            axes=font.get_variation_axes()
            if len(axes)==1:font.set_variation_by_axes([600 if size>=24 else 500])
        left,top,right,bottom=font.getbbox(text)
        im=Image.new('1',(right-left,bottom-top));ImageDraw.Draw(im).text((-left,-top),text,font=font,fill=1)
        bits=bytearray((im.width*im.height+7)//8)
        pixels=im.get_flattened_data() if hasattr(im,'get_flattened_data') else im.getdata()
        for i,v in enumerate(pixels):
            if v:bits[i//8] |= 1<<(7-i%8)
        parts.append(f'static const unsigned char {name}_BITS[]={{\n'+',\n'.join(
            ','.join(f'0x{v:02x}' for v in bits[k:k+24]) for k in range(0,len(bits),24))+'\n};\n')
        parts.append(f'static const Bitmap {name}={{{im.width},{im.height},{name}_BITS}};\n')
        records.append(dict(name=name,text=text,size=size,width=im.width,height=im.height,sha256=hashlib.sha256(bits).hexdigest()))
    parts.append('static const Bitmap CLASSES[9]={'+','.join('CLASS'+str(i) for i in range(9))+'};\n')
    for scene,names in SCENE_CLASSES.items():
        parts.append(f'static const Bitmap {scene.upper()}_CLASSES[{len(names)}]={{'+','.join(f'{scene.upper()}_{i}' for i in range(len(names)))+'};\n')
    parts.append('static const Bitmap SCENES[3]={SCENE0,SCENE1,SCENE2};\n')
    parts.append('static const Bitmap *const CLASS_TABLES[3]={CLASSES,HONGHU_CLASSES,HANCHUAN_CLASSES};\n')
    parts.append('static const unsigned SCENE_GSD_MM[3]={'+','.join(map(str,gsd_mm))+'};\n}}\n#endif\n')
    target=ROOT/'src/ps/s2c_roi_app/roi_labels.h';target.write_text(''.join(parts),encoding='utf-8')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(dict(font=str(args.font),font_sha256=hashlib.sha256(args.font.read_bytes()).hexdigest(),
        pillow=__version__,license='SIL OFL 1.1',font_binary_redistributed=False,labels=records,
        header_sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)

if __name__=='__main__':main()
