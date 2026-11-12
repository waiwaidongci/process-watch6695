import {Run} from '../types/domain';
import {number} from '../utils/format';
export function RunSummary({run}:{run:Run}){
  const r=run.result;
  const cap=r.capability;
  return <div className="run-summary">
    <div>
      <span className="eyebrow">PROCESS / {r.stream.code}</span>
      <h3>{r.stream.name}</h3>
      <p>{r.monitor_count} 个后续监测点 · 前 {r.baseline.sample_count} 点冻结基线 · λ {r.smoothing}{r.segment_count>1?` · ${r.segment_count} 个停机分段（每${r.sample_interval_minutes}分钟节奏识别断档）`:''}</p>
    </div>
    <div className="summary-stat"><span>稳定性信号</span><b className={r.stable?'safe':'alert'}>{r.signals.length}</b><small>I {r.signal_counts.individual} / MR {r.signal_counts.moving_range} / EWMA {r.signal_counts.ewma}</small></div>
    <div className="summary-stat"><span>Cpk / 正态近似</span><b>{number(cap.cpk,2)}</b><small className={!cap.interpretable?'alert':''}>{cap.interpretable?'满足本工具稳定性先决':r.segment_count>1?'跨段不拼能力，见分段表':'不可作能力结论'}</small></div>
  </div>;
}
