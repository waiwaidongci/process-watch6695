import csv,io
from redis import Redis
from fastapi import HTTPException
from ..config.settings import REDIS_URL
from ..models import ControlRun,Baseline,Investigation
from ..utils.serialize import record
from .audit_service import log
queue=Redis.from_url(REDIS_URL,decode_responses=True)
def list_runs(db):return [record(r) for r in db.query(ControlRun).order_by(ControlRun.id.desc())]
def get_run(db,rid):
    row=db.get(ControlRun,rid)
    if not row:raise HTTPException(404,"运行不存在")
    return row

def create_run(db,data,user):
    if not db.get(Baseline,data.baseline_id):raise HTTPException(404,"基线不存在")
    row=ControlRun(**data.model_dump(),owner=user.name)
    db.add(row);db.flush();log(db,user.email,"control.enqueue",row.id);db.commit()
    try:queue.rpush("process:jobs",row.id)
    except Exception:
        row.status="failed";row.error="队列不可用，请重新提交";db.commit();raise HTTPException(503,row.error)
    return record(row)
def export_run(db,rid):
    row=get_run(db,rid)
    if row.status!="completed":raise HTTPException(409,"运行尚未完成")
    if not db.query(Investigation).filter_by(run_id=rid,status="approved").first():raise HTTPException(403,"调查尚未经负责人批准，不能导出")
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['segment_id','segment_position','segment_start','sequence','source_key','time','thickness','moving_range','ewma','ewma_lower','ewma_upper','signals','input_hash'])
    for p in row.result['points']:
        writer.writerow([p['segment_id'],p['segment_position'],'yes' if p['segment_start'] else 'no',
                         p['sequence'],p['source_key'],p['measured_at'],p['value'],
                         '' if p['moving_range'] is None else p['moving_range'],
                         p['ewma'],p['ewma_lower'],p['ewma_upper'],'|'.join(p['signals']),row.result['input_hash']])
    # 分段能力清单：不足50点的段明确标注原因，不拼段凑数。
    writer.writerow([])
    writer.writerow(['# 分段能力（按停机断档独立计算）'])
    writer.writerow(['segment_id','start_sequence','end_sequence','start_time','end_time','monitor_count','cp','cpk','interpretable','note'])
    for seg in row.result.get('segments',[]):
        cap=seg['capability']
        writer.writerow([seg['segment_id'],seg['start_sequence'],seg['end_sequence'],seg['start_time'],seg['end_time'],
                         seg['monitor_count'],'' if cap['cp'] is None else cap['cp'],'' if cap['cpk'] is None else cap['cpk'],
                         'yes' if cap['interpretable'] else 'no',cap['note']])
    return out.getvalue()
