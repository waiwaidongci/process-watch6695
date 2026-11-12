import math,statistics
from .control_algorithm import validate_values,D2,CAPABILITY_MIN_POINTS

def capability(values,lsl,usl,stable):
    """兼容旧调用：单段能力。不足50点或常量段时返回None数值与原因，不抛错（控制图仍保留）。"""
    seg=capability_segment(values,lsl,usl)
    seg['interpretable']=bool(seg['eligible'] and stable)
    if seg['eligible'] and not stable:
        seg['note']="稳定性先决条件未满足；以下数值仅保留复算，不作能力结论。"
    return seg

def capability_segment(values,lsl,usl):
    """单段能力指数。段独立计算；不足50点或移动极差为零时保留原因、数值为None，绝不与其他段拼接。"""
    validate_values(values,1)
    if not(math.isfinite(lsl) and math.isfinite(usl) and lsl<usl):raise ValueError("规格上下限无效")
    base={"sample_count":len(values),"normal_approximation":True,"normality_tested":False,
          "cp":None,"cpk":None,"mean":None,"sigma_within":None,"eligible":False,"interpretable":False}
    if len(values)<CAPABILITY_MIN_POINTS:
        base['note']=(f"该分段仅{len(values)}个监测点，不足{CAPABILITY_MIN_POINTS}点；控制图与信号保留，"
                      "能力指数不予计算，也不与其他分段拼接凑数。")
        return base
    mu=statistics.mean(values)
    if len(values)<2:
        base['note']="该分段不足2点，无法估计移动极差；控制图保留，能力指数不予计算。"
        return base
    mrbar=statistics.mean(abs(b-a) for a,b in zip(values,values[1:]))
    sigma=mrbar/D2
    if sigma<=1e-12:
        base.update(mean=mu)
        base['note']="该分段移动极差为零，组内σ无法估计；控制图与信号保留，能力指数不予计算，也不与其他分段拼接。"
        return base
    cp=(usl-lsl)/(6*sigma);cpk=min(usl-mu,mu-lsl)/(3*sigma)
    base.update(cp=cp,cpk=cpk,mean=mu,sigma_within=sigma,eligible=True)
    base['note']="仅在稳定过程、正态近似与独立采样假设下解释；未做正态检验。"
    return base
