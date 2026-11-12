"""分段控制图/能力算法的离线自检（不依赖数据库与Redis）。

运行：cd backend && python -I -m scripts.test_segmentation
"""
import os,sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as Row
from src.services.control_algorithm import (freeze_measurements,analyze_process,prepare_ordered,
    split_segments,monitor_segmented,SAMPLE_INTERVAL_MINUTES,GAP_SECONDS)
from src.services.capability_algorithm import capability_segment

BASE=datetime(2026,11,1,tzinfo=timezone.utc)
def mk(seq,value=None,minute=None):
    return Row(source_key=f"S-{seq:04}",sequence=seq,
               measured_at=(BASE+timedelta(minutes=(10*(seq-1) if minute is None else minute))).isoformat(),
               value=20.0+0.01*(seq%7) if value is None else value)
class Stream:id=1;code="T-99";name="测试流";lsl=18.;usl=22.;unit="μm"
class Baseline:
    def __init__(self,snap,n=100):self.id=9;self.name="b";self.sample_count=n;self.snapshot=snap;self.owner="t"

def check(name,cond):
    print(("PASS" if cond else "FAIL"),name)
    if not cond:raise SystemExit(1)

# 1) 乱序还原 + 重复序号拒绝
rows=[mk(3),mk(1),mk(2)]
ordered=prepare_ordered(rows)
check("乱序按序号还原",[r.sequence for r in ordered]==[1,2,3])
dup=rows+[mk(2,value=21.)]
try:
    prepare_ordered(dup);check("重复序号明确拒绝",False)
except ValueError as e:check("重复序号明确拒绝","重复" in str(e))

# 2) 时间倒退 / 重复时间拒绝（序号递增但时间不单调不减）
back=[mk(1,minute=20),mk(2,minute=5)]  # 第二点时间早于第一点
try:
    prepare_ordered(back);check("时间倒退明确拒绝",False)
except ValueError as e:check("时间倒退明确拒绝","倒退" in str(e))
same=[mk(1,minute=0),mk(2,minute=0)]
try:
    prepare_ordered(same);check("重复时间明确拒绝",False)
except ValueError as e:check("重复时间明确拒绝","重复时间" in str(e))

# 3) 断档识别：序号缺失 + 时间断档
seg_rows=[mk(i) for i in range(1,120)]          # 1..119
seg_rows+=[mk(i) for i in range(150,200)]       # 缺失120..149
seg_rows+=[mk(i) for i in range(220,241)]       # 缺失200..219
segs=split_segments(seg_rows)
check("断档切成3段",len(segs)==3)
check("各段边界",[ (s[0].sequence,s[-1].sequence) for s in segs ]==[(1,119),(150,199),(220,240)])
# 纯时间断档（序号连续但时间超10分钟）也分段
time_gap=[mk(1),mk(2,minute=25),mk(3,minute=35)]
check("时间断档同样分段",len(split_segments(time_gap))==2)
# 序号跳变但时间连续仍按序号断档分段
seq_gap=[mk(1),Row(source_key="x",sequence=5,measured_at=(BASE+timedelta(minutes=10)).isoformat(),value=20.)]
check("序号断档同样分段",len(split_segments(seq_gap))==2)
check("节奏常量为10分钟",SAMPLE_INTERVAL_MINUTES==10 and GAP_SECONDS==600)

# 4) 段首MR留空、EWMA每段从基线μ重启、t每段重置
snap=freeze_measurements([mk(i,value=20.+0.05*((i*3)%5-2)) for i in range(1,111)],100)
mu=snap['statistics']['mean']
mon=monitor_segmented(split_segments([r for r in seg_rows if r.sequence>snap['end_sequence']]),snap['statistics'],.2,3.)
starts=[p for p in mon if p['segment_start']]
check("段首数量=3",len(starts)==3)
check("段首移动极差留空",all(p['moving_range'] is None for p in starts))
check("非段首移动极差有值",all(p['moving_range'] is not None for p in mon if not p['segment_start']))
# EWMA重启：段首 z1 = λx1+(1-λ)μ
first=starts[0]
check("EWMA从冻结基线μ重启",abs(first['ewma']-(.2*first['row'].value+.8*mu))<1e-12)
# 段首EWMA界限使用t=1的启动期宽度（与第二段段首一致，因为t重置）
check("各段段首EWMA界限相同(t重置)",abs(starts[0]['ewma_lower']-starts[1]['ewma_lower'])<1e-12)
check("段首不产生MR信号",all('moving_range' not in p['signals'] for p in starts))

# 5) 端到端 analyze_process：分段结构、能力按段、不足50点保留原因不拼段
baseline=Baseline(snap,100)
result=analyze_process(seg_rows,baseline,Stream(),.2,3.)
check("结果记录3段",result['segment_count']==3 and len(result['segments'])==3)
check("监测点总数",result['monitor_count']==(119-100)+50+21)
check("每点带分段与段内位置",all({'segment_id','segment_position','segment_start'}<=set(p) for p in result['points']))
check("点保留原测量位置(sequence/source_key/time)",all('source_key' in p and 'measured_at' in p and 'sequence' in p for p in result['points']))
counts=[s['monitor_count'] for s in result['segments']]
check("段长度19/50/21",counts==[19,50,21])
cap_by_len={c:s['capability'] for c,s in zip(counts,result['segments'])}
check("19点段能力留空并说明",cap_by_len[19]['cp'] is None and cap_by_len[19]['eligible'] is False and "不足50" in cap_by_len[19]['note'])
check("21点段能力留空并说明",cap_by_len[21]['cp'] is None and "不足50" in cap_by_len[21]['note'])
check("50点段给出能力数值",cap_by_len[50]['cp'] is not None and cap_by_len[50]['cpk'] is not None and cap_by_len[50]['eligible'])
check("跨段不下放单一能力值（不拼段）",result['capability']['cp'] is None and "不拼段" in result['capability']['note'])
check("方法版本升级v2",result['method_version']=="imr-ewma-capability-v2")
check("输入指纹为64位hex",len(result['input_hash'])==64)
# 信号带段号
check("信号带segment_id",all('segment_id' in s for s in result['signals']))

# 6) 单段场景：顶层能力与该段一致，向后兼容
single=[mk(i,value=20.+0.1*((i*13)%6-3)) for i in range(1,181)]
snap2=freeze_measurements(single,100)
r2=analyze_process(single,Baseline(snap2),Stream(),.2,3.)
check("单段时分段数=1",r2['segment_count']==1)
check("单段顶层Cp等同分段Cp",r2['capability']['cp']==r2['segments'][0]['capability']['cp'])
check("单段监测80点",r2['monitor_count']==80)

# 7) 常量段不报错：控制图保留、能力留空说明（基线正常、监测段常量）
base_rows=[mk(i,value=20.+0.1*((i*7)%5-2)) for i in range(1,101)]
const_tail=[Row(source_key=f"C-{i:04}",sequence=i,measured_at=(BASE+timedelta(minutes=10*(i-1))).isoformat(),value=20.0) for i in range(101,181)]
snap3=freeze_measurements(base_rows+const_tail[:3],100)  # 冻结前100点（即base_rows），仅满足保留后续点的要求
mixed=base_rows+const_tail
r3=analyze_process(mixed,Baseline(snap3),Stream(),.2,3.)
check("常量监测段不报错且能力留空",r3['segments'][0]['capability']['cp'] is None and "移动极差为零" in r3['segments'][0]['capability']['note'])
check("常量段控制图仍保留",len(r3['points'])==80)

# 8) 能力模块直接验证50点门槛与解释位
cap_short=capability_segment([20.]*10,18.,22.)
check("capability_segment不足50拒绝计算",cap_short['cp'] is None and cap_short['eligible'] is False)
cap_ok=capability_segment([20.+0.2*((i*11)%7-3) for i in range(60)],18.,22.)
check("capability_segment满50可计算",cap_ok['cp'] is not None and cap_ok['eligible'] is True)

# 9) 冻结基线段含断档必须拒绝（停机间隔不得污染基线MRbar/σ）
gap_baseline_rows=[mk(i) for i in range(1,60)]+[mk(i) for i in range(80,130)]  # 缺60..79
try:
    freeze_measurements(gap_baseline_rows,100);check("基线段序号断档拒绝冻结",False)
except ValueError as e:check("基线段序号断档拒绝冻结","断档" in str(e))
# 点2在90分（与点1间隔90分钟），点3顺延到100分，保证整体时间单调、仅点1→2超节奏
time_gap_base=[mk(1),Row(source_key="t2",sequence=2,measured_at=(BASE+timedelta(minutes=90)).isoformat(),value=20.),Row(source_key="t3",sequence=3,measured_at=(BASE+timedelta(minutes=100)).isoformat(),value=20.)]+[Row(source_key=f"S-{i:04}",sequence=i,measured_at=(BASE+timedelta(minutes=10*(i-1)+80)).isoformat(),value=20.+0.01*(i%7)) for i in range(4,110)]
try:
    freeze_measurements(time_gap_base,100);check("基线段时间断档拒绝冻结",False)
except ValueError as e:check("基线段时间断档拒绝冻结","节奏" in str(e) or "断档" in str(e))
# 连续基线可正常冻结且快照记录节奏
clean=freeze_measurements([mk(i,value=20.+0.05*(i%5-2)) for i in range(1,111)],100)
check("基线快照记录10分钟节奏",clean['sample_interval_minutes']==10)

print("ALL SEGMENTATION TESTS PASSED")
