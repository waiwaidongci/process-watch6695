import {useState} from 'react';
import {useSearchParams,Link} from 'react-router-dom';
import {useProcessData} from '../hooks/useProcess';
import {RunSummary} from '../components/RunSummary';
import {ControlChart} from '../components/ControlChart';
import {StatusBadge} from '../components/common/StatusBadge';
import {Notice} from '../components/common/Notice';
import {DataTable} from '../components/common/DataTable';
import {SignalKinds} from '../constants/enums';
import {number,time} from '../utils/format';

export function Results(){
  const s=useProcessData(true),[params]=useSearchParams(),[selected,setSelected]=useState(Number(params.get('run'))||0);
  const run=s.runs.find(x=>x.id===selected)||s.runs[0];
  const r=run?.result;
  return <div className="page results-page">
    <div className="page-title">
      <div><p className="eyebrow">SIGNAL INTERPRETATION / 04</p><h1>信号与能力<span>越界先调查，能力结论留在前提之后；停机断档分段计算，不拼段凑数。</span></h1></div>
      <Link className="outline" to={'/reviews'+(run?'?run='+run.id:'')}>建立调查 →</Link>
    </div>
    <Notice message={s.error} retry={s.refresh}/>
    <div className="run-picker"><label>运行档案<select aria-label="运行档案" value={run?.id||''} onChange={e=>setSelected(Number(e.target.value))}>{s.runs.map(x=><option key={x.id} value={x.id}>#{x.id} / {x.name} / {x.status}</option>)}</select></label>{run&&<StatusBadge status={run.status}/>}</div>
    {run?.status==='completed'&&r?<>
      <div className={'result-conclusion '+(!r.stable?'warning':'')}><span>{r.stable?'稳定性观察':'调查优先'}</span><b>{r.interpretation}</b></div>
      <RunSummary run={run}/>
      <ControlChart result={r}/>
      {r.segment_count>1&&<div className="segment-heading">
        <div className="section-heading"><h2>停机分段与分段能力</h2><span>{r.segment_count} 段 · 每{r.sample_interval_minutes}分钟节奏识别序号/时间断档</span></div>
        <DataTable head={['分段','原测量位置（序号）','采样时间范围','监测点','I/MR/EWMA 信号','Cp','Cpk','能力解释']}>
          {r.segments.map(seg=><tr key={seg.segment_id}>
            <td><span className="segment-tag">段 {seg.segment_id}</span></td>
            <td className="mono">#{seg.start_sequence} – #{seg.end_sequence}</td>
            <td className="mono">{time(seg.start_time)}<br/>{time(seg.end_time)}</td>
            <td>{seg.monitor_count}</td>
            <td className="mono">{seg.signal_counts.individual}/{seg.signal_counts.moving_range}/{seg.signal_counts.ewma}</td>
            <td>{number(seg.capability.cp,3)}</td>
            <td>{number(seg.capability.cpk,3)}</td>
            <td><span className={seg.capability.interpretable?'safe':'alert'}>{seg.capability.interpretable?'可作能力解释':'不作能力结论'}</span><small className="seg-note">{seg.capability.note}</small></td>
          </tr>)}
        </DataTable>
        <p className="caption">段首移动极差留空（不与停机前末点相连），EWMA 每段从冻结基线均值重启；能力按段独立估计，不足50点或移动极差为零的段只保留控制图与原因，绝不与相邻段拼接。</p>
      </div>}
      <div className="capability-strip"><div><span>Cp / 数值{r.segment_count>1?'（跨段不拼）':''}</span><b>{number(r.capability.cp,3)}</b></div><div><span>Cpk / 数值</span><b>{number(r.capability.cpk,3)}</b></div><p className={!r.capability.interpretable?'alert':''}>{r.capability.note}</p></div>
      <p className="caption">{r.assumptions}</p>
      {r.baseline_source_changed&&<Notice message="当前来源的基线段已变化；本运行仍使用冻结快照，请复核来源版本。"/>}
      <div className="section-heading"><h2>首批触发信号</h2><span>{r.signals.length} 条 / 展示前12条</span></div>
      <div className="signals-list">{r.signals.slice(0,12).map((x,i)=><div key={i}><span>#{x.sequence}{r.segment_count>1&&<em className="signal-seg"> 段{x.segment_id}</em>}</span><b>{SignalKinds[x.kind as keyof typeof SignalKinds]}</b><small>{number(x.value,4)}</small></div>)}{!r.signals.length&&<p>未见本工具三类越界信号；不等同证明过程绝对稳定。</p>}</div>
      <p className="fingerprint">方法 {r.method_version} · 输入SHA256 {r.input_hash} · {time(run.created_at)}</p>
    </>:run?<div className="pending"><h2>{run.status==='failed'?'本次计算未完成':'后台正在计算控制图与能力指标'}</h2><p>{run.error||'独立worker从Redis队列执行，本页每2秒更新。'}</p></div>:<p className="empty">还没有运行，请先创建冻结基线。</p>}
  </div>;
}
