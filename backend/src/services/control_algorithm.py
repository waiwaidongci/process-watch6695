"""Individuals/MR Phase-I estimation and Phase-II EWMA, with downtime-gap segmentation.

停机/漏测处理口径：
- 采样节奏为每 10 分钟一点；序号不连续（delta>1）或相邻采样时间超过一个节奏（>10 分钟）即判定为断档。
- 断档处图线断开：段首移动极差留空（不与上一段末点相连），EWMA 从冻结基线均值重新起算。
- 乱序数据先按序号还原；重复序号明确拒绝；还原后时间必须单调不减，时间倒退/重复时间明确拒绝。
- 能力指数按段独立计算；不足 50 点的段保留控制图与原因，不拼段凑数。

Constants: d2=1.128, D4=3.267.
"""
import math,statistics
from datetime import datetime
from ..utils.fingerprint import fingerprint,measurement_record
D2=1.128
D4=3.267
# 采样节奏：每 10 分钟一个测量点；相邻点间隔超过该值即视为停机/漏测断档。
SAMPLE_INTERVAL_MINUTES=10
GAP_SECONDS=SAMPLE_INTERVAL_MINUTES*60
# 能力研究单段所需的最少独立监测点。
CAPABILITY_MIN_POINTS=50

def validate_values(values,min_count=5):
    if len(values)<min_count:raise ValueError(f"至少需要{min_count}个测量点")
    if any(type(v) not in (int,float) or abs(v)>1e9 or not math.isfinite(v) for v in values):raise ValueError("测量值必须为有限数字")
    if max(abs(v) for v in values)>1e9:raise ValueError("测量值超出支持范围")

def parse_time(value):
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (ValueError,TypeError):raise ValueError("测量时间不是有效的ISO-8601时间")

def prepare_ordered(rows):
    """乱序先按序号还原；重复序号、时间倒退或重复时间一律明确拒绝。"""
    ordered=sorted(rows,key=lambda r:r.sequence)
    if len({r.sequence for r in ordered})!=len(ordered):raise ValueError("测量序号重复，已拒绝该来源数据")
    previous=None
    for r in ordered:
        ts=parse_time(r.measured_at)
        if previous is not None and ts<previous:raise ValueError(f"序号{r.sequence}的测量时间早于前一点，时间倒退的数据已拒绝")
        if previous is not None and ts==previous:raise ValueError(f"序号{r.sequence}与前一点测量时间相同，重复时间已拒绝")
        previous=ts
    return ordered

def split_segments(rows):
    """按序号断档或超过10分钟节奏的时间断档切分，返回[[row,...],...]。"""
    if not rows:return []
    segments=[[rows[0]]]
    for prev,row in zip(rows,rows[1:]):
        seq_gap=row.sequence-prev.sequence
        time_gap=(parse_time(row.measured_at)-parse_time(prev.measured_at)).total_seconds()
        if seq_gap!=1 or time_gap>GAP_SECONDS:
            segments.append([row])
        else:
            segments[-1].append(row)
    return segments

def estimate_baseline(values):
    validate_values(values)
    mr=[abs(b-a) for a,b in zip(values,values[1:])]
    mean=statistics.mean(values);mrbar=statistics.mean(mr);sigma=mrbar/D2
    if sigma<=1e-12:raise ValueError("移动极差为零，无法建立统计控制界限")
    ilow,ihigh=mean-3*sigma,mean+3*sigma
    i_flags=[i+1 for i,x in enumerate(values) if x<ilow or x>ihigh]
    mr_flags=[i+2 for i,x in enumerate(mr) if x>D4*mrbar]
    return {"mean":mean,"mrbar":mrbar,"sigma":sigma,"i_lower":ilow,"i_upper":ihigh,"mr_upper":D4*mrbar,"i_signals":i_flags,"mr_signals":mr_flags,"stable":not(i_flags or mr_flags)}

def freeze_measurements(rows,sample_count):
    ordered=prepare_ordered(rows)
    if not 5<=sample_count<=len(ordered)-3:raise ValueError("基线范围不足或没有后续监测点")
    chosen=ordered[:sample_count]
    # 冻结基线段必须序号连续且无超过采样节奏的时间断档，否则停机间隔会污染MRbar/σ估计。
    for prev,row in zip(chosen,chosen[1:]):
        if row.sequence-prev.sequence!=1:
            raise ValueError(f"冻结基线段在序号{prev.sequence}后出现断档，不能把停机间隔纳入控制界限估计")
        if (parse_time(row.measured_at)-parse_time(prev.measured_at)).total_seconds()>GAP_SECONDS:
            raise ValueError(f"冻结基线段在序号{prev.sequence}后采样时间超过{SAMPLE_INTERVAL_MINUTES}分钟节奏，存在停机断档，拒绝冻结")
    points=[measurement_record(x) for x in chosen]
    return {"points":points,"statistics":estimate_baseline([x.value for x in chosen]),
            "input_hash":fingerprint(points),"end_sequence":chosen[-1].sequence,
            "sample_interval_minutes":SAMPLE_INTERVAL_MINUTES}

def monitor_segmented(segments,baseline,smoothing,ewma_l):
    """分段监测：段首MR留空、EWMA每段从冻结基线μ重启，界限时间索引t每段从1计。"""
    mu,sigma,mrbar=baseline['mean'],baseline['sigma'],baseline['mrbar']
    if not math.isfinite(smoothing) or not 0<smoothing<=1:raise ValueError("EWMA lambda必须在(0,1]内")
    if not math.isfinite(ewma_l) or not 1<=ewma_l<=5:raise ValueError("EWMA L必须在[1,5]内")
    if not all(math.isfinite(v) for v in [mu,sigma,mrbar]) or sigma<=1e-12:raise ValueError("基线参数无效")
    out=[]
    for seg_id,rows in enumerate(segments,1):
        z=mu  # EWMA 从冻结基线重启
        previous=None
        for t,row in enumerate(rows,1):
            x=row.value
            mr=None if previous is None else abs(x-previous)  # 段首极差留空，不跨停机连接
            z=smoothing*x+(1-smoothing)*z
            width=ewma_l*sigma*math.sqrt(smoothing/(2-smoothing)*(1-(1-smoothing)**(2*t)))
            lower,upper=mu-width,mu+width
            flags=[]
            if x<mu-3*sigma or x>mu+3*sigma:flags.append('individual')
            if mr is not None and mr>D4*mrbar:flags.append('moving_range')
            if z<lower or z>upper:flags.append('ewma')
            out.append({"row":row,"segment_id":seg_id,"segment_position":t,"segment_start":t==1,
                        "moving_range":mr,"ewma":z,"ewma_lower":lower,"ewma_upper":upper,"signals":flags})
            previous=x
    return out

def analyze_process(rows,baseline,stream,smoothing=.2,ewma_l=3.):
    ordered=prepare_ordered(rows)
    validate_values([x.value for x in ordered])
    snapshot=baseline.snapshot
    monitored_rows=[x for x in ordered if x.sequence>snapshot['end_sequence']]
    if not monitored_rows:raise ValueError("没有基线结束之后的监测点，无法分析")
    if not (math.isfinite(stream.lsl) and math.isfinite(stream.usl) and stream.lsl<stream.usl):raise ValueError("规格下限必须小于上限且均为有限数字")
    segments=split_segments(monitored_rows)
    monitored=monitor_segmented(segments,snapshot['statistics'],smoothing,ewma_l)
    points=[]
    for m in monitored:
        p=dict(measurement_record(m['row']),
               segment_id=m['segment_id'],segment_position=m['segment_position'],segment_start=m['segment_start'],
               moving_range=m['moving_range'],ewma=m['ewma'],ewma_lower=m['ewma_lower'],ewma_upper=m['ewma_upper'],signals=m['signals'])
        points.append(p)
    signals=[{"sequence":p['sequence'],"segment_id":p['segment_id'],"kind":kind,
              "value":p['ewma'] if kind=='ewma' else p['moving_range'] if kind=='moving_range' else p['value']}
             for p in points for kind in p['signals']]
    from .capability_algorithm import capability_segment
    segment_results=[]
    for seg_id,seg_rows in enumerate(segments,1):
        values=[r.value for r in seg_rows]
        cap=capability_segment(values,stream.lsl,stream.usl)
        seg_has_signal=any(p['segment_id']==seg_id and p['signals'] for p in monitored)
        cap['interpretable']=bool(cap['eligible'] and snapshot['statistics']['stable'] and not seg_has_signal)
        segment_results.append({
            "segment_id":seg_id,
            "start_sequence":seg_rows[0].sequence,"end_sequence":seg_rows[-1].sequence,
            "start_time":seg_rows[0].measured_at,"end_time":seg_rows[-1].measured_at,
            "monitor_count":len(seg_rows),
            "signal_counts":{k:sum(1 for p in points if p['segment_id']==seg_id and k in p['signals']) for k in ['individual','moving_range','ewma']},
            "stable":not seg_has_signal,
            "capability":cap,
        })
    # 顶层能力字段：仅当所有监测点同属一段时与该段一致；跨段时不下放单一能力值，避免拼段凑数。
    if len(segment_results)==1:
        capability=dict(segment_results[0]['capability'])
    else:
        capability={"cp":None,"cpk":None,"mean":None,"sigma_within":None,"sample_count":len(monitored_rows),
                    "interpretable":False,"eligible":False,"normal_approximation":True,"normality_tested":False,
                    "note":f"监测数据跨{len(segment_results)}个停机分段，能力指数按段分别给出，不拼段计算单一Cp/Cpk。"}
    stream_data={"id":stream.id,"code":stream.code,"name":stream.name,"lsl":stream.lsl,"usl":stream.usl,"unit":stream.unit}
    input_data={"method":"imr-ewma-capability-v2","stream":stream_data,"source":[measurement_record(x) for x in ordered],
                "baseline":snapshot,"smoothing":smoothing,"ewma_l":ewma_l,
                "sample_interval_minutes":SAMPLE_INTERVAL_MINUTES}
    source_baseline=[measurement_record(x) for x in ordered[:baseline.sample_count]]
    stable=snapshot['statistics']['stable'] and not signals
    if len(segment_results)>1:
        interp=("过程存在稳定性信号，Cp/Cpk不得用于宣称过程能力" if not stable else
                f"监测跨{len(segment_results)}个分段，各段能力独立解释，不提供拼段能力值")
    else:
        interp="未见本工具三类越界信号；能力值仍以正态近似和独立性为前提" if stable else "过程存在稳定性信号，Cp/Cpk不得用于宣称过程能力"
    return {"stream":stream_data,
            "baseline":{"id":baseline.id,"name":baseline.name,"sample_count":baseline.sample_count,**snapshot},
            "points":points,"signals":signals,
            "signal_counts":{k:sum(s['kind']==k for s in signals) for k in ['individual','moving_range','ewma']},
            "monitor_count":len(monitored_rows),
            "segment_count":len(segment_results),"segments":segment_results,
            "sample_interval_minutes":SAMPLE_INTERVAL_MINUTES,
            "stable":stable,"capability":capability,"smoothing":smoothing,"ewma_l":ewma_l,
            "baseline_source_changed":fingerprint(source_baseline)!=snapshot['input_hash'],
            "input_hash":fingerprint(input_data),"method_version":"imr-ewma-capability-v2",
            "interpretation":interp,
            "assumptions":("正态近似、按时间独立采样；未检验正态性或自相关。控制界限由冻结基线估计，规格18–22等为外部要求，两者不同。"
                           f"采样节奏每{SAMPLE_INTERVAL_MINUTES}分钟一点，序号断档或相邻时间超过该节奏即分段："
                           "图线在断档处断开，段首移动极差留空，EWMA从冻结基线均值重启；能力指数按段独立计算，不足50点的段只保留控制图与原因，不拼段凑数。")}
