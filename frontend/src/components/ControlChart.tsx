import {useState} from 'react';
import {Result,ControlPoint} from '../types/domain';
import {number} from '../utils/format';

type Mode='individual'|'ewma'|'moving_range';

export function ControlChart({result:r,compact=false}:{result:Result;compact?:boolean}){
  const [mode,setMode]=useState<Mode>('individual');
  const b=r.baseline.statistics,p=r.points;
  const valueOf=(x:ControlPoint):number|null=>mode==='ewma'?x.ewma:mode==='moving_range'?x.moving_range:x.value;
  const lowOf=(x:ControlPoint):number=>mode==='ewma'?x.ewma_lower:mode==='moving_range'?0:b.i_lower;
  const highOf=(x:ControlPoint):number=>mode==='ewma'?x.ewma_upper:mode==='moving_range'?b.mr_upper:b.i_upper;
  const values=p.map(valueOf);
  const finiteValues=values.filter((v):v is number=>v!==null);
  const lows=p.map(lowOf),highs=p.map(highOf);
  let min=Math.min(...finiteValues,...lows),max=Math.max(...finiteValues,...highs);
  if(mode==='individual'){min=Math.min(min,r.stream.lsl);max=Math.max(max,r.stream.usl)}
  const pad=(max-min)*.12||1;min-=pad;max+=pad;
  const x=(i:number)=>62+i/(p.length-1)*850,y=(v:number)=>230-(v-min)/(max-min)*195;
  // 按分段构造路径：段间不连线（停机断档处图线断开）；MR 模式段首空值跳过。
  const segmentPaths=(sel:(x:ControlPoint)=>number|null):string[]=>{
    const paths:string[]=[];let d='';
    p.forEach((pt,i)=>{
      const v=sel(pt);
      if(v===null||pt.segment_start&&i>0){if(d){paths.push(d);d=''}}
      if(v===null)return;
      d+=(d?'L':'M')+x(i)+','+y(v);
    });
    if(d)paths.push(d);
    return paths;
  };
  const paths=segmentPaths(valueOf);
  const limitPaths=[segmentPaths(lowOf),segmentPaths(highOf)];
  const center=mode==='moving_range'?b.mrbar:b.mean;
  const boundaries=p.map((pt,i)=>pt.segment_start&&i>0?i:-1).filter(i=>i>=0);
  return (
    <section className={'control-chart '+(compact?'compact':'')}>
      <div className="chart-toolbar">
        <h3>{mode==='individual'?'个体测量 / I':mode==='ewma'?'指数加权 / EWMA':'移动极差 / MR'}{r.segment_count>1&&<em className="segment-badge"> {r.segment_count} 段 · 断档断开</em>}</h3>
        <div className="chart-tabs">{([['individual','I'],['moving_range','MR'],['ewma','EWMA']] as const).map(([v,l])=><button key={v} className={mode===v?'active':''} onClick={()=>setMode(v)}>{l}</button>)}</div>
      </div>
      <svg viewBox="0 0 960 275" aria-label={mode+'控制图'}>
        {[0,1,2,3,4].map(i=>{const v=min+(max-min)*i/4;return <g key={i}><line x1="62" x2="912" y1={y(v)} y2={y(v)} className="gridline"/><text x="51" y={y(v)+4} textAnchor="end">{number(v,2)}</text></g>})}
        {limitPaths.flatMap((arr,li)=>arr.map((d,i)=><path key={'l'+li+'-'+i} d={d} className="control-limit"/>))}
        <line x1="62" x2="912" y1={y(center)} y2={y(center)} className="center-line"/>
        {mode==='individual'&&[r.stream.lsl,r.stream.usl].map(v=><g key={v}><line x1="62" x2="912" y1={y(v)} y2={y(v)} className="spec-line"/><text x="918" y={y(v)+4}>{v}</text></g>)}
        {boundaries.map(i=><g key={'gap'+i}><line x1={x(i)} x2={x(i)} y1="30" y2="235" className="gap-line"/><text x={x(i)} y="24" textAnchor="middle" className="gap-label">段{p[i].segment_id} 断档重启</text></g>)}
        {paths.map((d,i)=><path key={'v'+i} d={d} className="measurement-line"/>)}
        {p.map((pt,i)=>{const v=values[i];return v!==null&&pt.signals.includes(mode)?<circle key={i} cx={x(i)} cy={y(v)} r="3" className="signal-point"/>:null})}
        {[0,Math.floor((p.length-1)/2),p.length-1].map(i=><text key={i} x={x(i)} y="255" textAnchor="middle">#{p[i].sequence}</text>)}
      </svg>
      <div className="chart-legend">
        <span><i className="legend-measure"/>实际统计量</span>
        <span><i className="legend-control"/>统计控制界限</span>
        {mode==='individual'&&<span><i className="legend-spec"/>外部规格界限</span>}
        {r.segment_count>1&&<span><i className="legend-gap"/>停机断档（图线断开）</span>}
        <small>横轴为时间序号 · 每{r.sample_interval_minutes}分钟一点 · {r.stream.unit}</small>
      </div>
    </section>
  );
}
