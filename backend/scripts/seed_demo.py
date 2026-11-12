import random,json
from datetime import datetime,timedelta,timezone
from src.config.database import SessionLocal,Base,engine
from src.models import User,MeasurementStream,Measurement,Baseline,ControlRun,Investigation
from src.utils.security import hash_password
from src.services.control_algorithm import freeze_measurements,analyze_process

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for role,name in [("admin","程砚 · 质量负责人"),("analyst","沈微 · 工艺分析师"),("viewer","顾远 · 工艺观察员")]:
            email=role+"@qingzhen.demo"
            if not db.query(User).filter_by(email=email).first():db.add(User(email=email,name=name,role=role,password_hash=hash_password("Qingzhen2026!")))
        for idx,name,mu,sd in [(1,"底涂稳定参考",20.,.22),(2,"面涂低位参考",19.65,.28),(3,"热喷涂漂移观察",20.,.22),(4,"试制波动观察",20.1,.48)]:
            code=f"T-{idx:02}";stream=db.query(MeasurementStream).filter_by(code=code).first()
            if not stream:
                stream=MeasurementStream(code=code,name=name,description="每10分钟采样一次的合成膜厚，按测量序号保留时间顺序；规格18–22μm。",source="qt-coating-202611.csv",lsl=18.,usl=22.,unit="μm")
                db.add(stream);db.flush()
            rng=random.Random({1:605,2:502,3:802,4:504}[idx]);existing=set(x[0] for x in db.query(Measurement.source_key).filter_by(stream_id=stream.id))
            for i in range(1,241):
                value=round(rng.gauss(mu,sd)+(0.85 if idx==3 and i>150 else 0),4);key=f"{code}-{i:04}"
                if key not in existing:db.add(Measurement(stream_id=stream.id,source_key=key,sequence=i,measured_at=(datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(minutes=10*(i-1))).isoformat(),value=value))
            db.flush();bname=code+" · 前80点冻结基线";baseline=db.query(Baseline).filter_by(name=bname).first()
            rows=db.query(Measurement).filter_by(stream_id=stream.id).order_by(Measurement.sequence).all()
            if not baseline:
                baseline=Baseline(name=bname,stream_id=stream.id,sample_count=80,snapshot=freeze_measurements(rows,80),owner="沈微 · 工艺分析师")
                db.add(baseline);db.flush()
            if idx in [1,3]:
                rname=code+" · 首次过程观察";run=db.query(ControlRun).filter_by(name=rname).first()
                if not run:
                    run=ControlRun(name=rname,baseline_id=baseline.id,smoothing=.2,ewma_l=3.,status="completed",result=analyze_process(rows,baseline,stream,.2,3.),owner="沈微 · 工艺分析师")
                    db.add(run);db.flush()
                    if idx==1:db.add(Investigation(run_id=run.id,title="T-01基准复核档案",finding="已核对控制界限和规格界限来源，统计结果保留完整假设说明。",action="继续独立采样并按周复查，不将单次能力值作为保证。",status="approved",owner="沈微 · 工艺分析师",reviewer="程砚 · 质量负责人",review_note="批准此研究记录归档，能力解释仍以稳定及正态近似为前提。",reviewed_at=datetime.now(timezone.utc).isoformat()))
        # T-05：含两次停机/漏测断档的涂层流（序号缺失且时间断档），演示分段控制图与分段能力。
        code="T-05";gap_stream=db.query(MeasurementStream).filter_by(code=code).first()
        if not gap_stream:
            gap_stream=MeasurementStream(code=code,name="停机分段观察",description="每10分钟采样一次；含两次停机漏测：序号120–149与200–219缺失，采样时间同步断档。断档处图线断开、段首极差留空、EWMA从冻结基线重启；能力按段独立计算。规格18–22μm。",source="qt-coating-202611-gap.csv",lsl=18.,usl=22.,unit="μm")
            db.add(gap_stream);db.flush()
        rng=random.Random(715);existing=set(x[0] for x in db.query(Measurement.source_key).filter_by(stream_id=gap_stream.id))
        # 序号1..119、150..199、220..240；时钟按序号推进，缺失序号造成>10分钟的时间断档。
        for i in list(range(1,120))+list(range(150,200))+list(range(220,241)):
            key=f"{code}-{i:04}"
            if key not in existing:
                value=round(rng.gauss(20.,.25),4)
                db.add(Measurement(stream_id=gap_stream.id,source_key=key,sequence=i,measured_at=(datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(minutes=10*(i-1))).isoformat(),value=value))
        db.flush()
        bname=code+" · 前80点冻结基线";gap_baseline=db.query(Baseline).filter_by(name=bname).first()
        gap_rows=db.query(Measurement).filter_by(stream_id=gap_stream.id).order_by(Measurement.sequence).all()
        if not gap_baseline:
            gap_baseline=Baseline(name=bname,stream_id=gap_stream.id,sample_count=80,snapshot=freeze_measurements(gap_rows,80),owner="沈微 · 工艺分析师")
            db.add(gap_baseline);db.flush()
        rname=code+" · 停机分段观察";gap_run=db.query(ControlRun).filter_by(name=rname).first()
        if not gap_run:
            db.add(ControlRun(name=rname,baseline_id=gap_baseline.id,smoothing=.2,ewma_l=3.,status="completed",result=analyze_process(gap_rows,gap_baseline,gap_stream,.2,3.),owner="沈微 · 工艺分析师"))
            db.flush()
        db.commit();print(json.dumps({m.__tablename__:db.query(m).count() for m in [User,MeasurementStream,Measurement,Baseline,ControlRun,Investigation]},ensure_ascii=False))
if __name__=="__main__":seed()
