"""TF/CRR reference valuation; not a complete China-clause model."""
import json, math
from datetime import date
import QuantLib as ql

def qdate(value):
    d=date.fromisoformat(str(value)[:10])
    return ql.Date(d.day,d.month,d.year)

def dated_cashflows(term):
    rates=json.loads(term['coupon_rates']) if isinstance(term['coupon_rates'],str) else term['coupon_rates']
    issue=date.fromisoformat(term['issue_date']); maturity=date.fromisoformat(term['maturity_date'])
    flows=[]
    for i,rate in enumerate(rates):
        try: when=issue.replace(year=issue.year+i+1)
        except ValueError: when=issue.replace(year=issue.year+i+1,day=28)
        if i==len(rates)-1: when=maturity
        amount=float(term['redemption_amount_including_last_coupon']) if i==len(rates)-1 else float(rate)
        flows.append((when,amount))
    return flows

def debt_floor(term,evaluation,riskfree,spread):
    return sum(a*math.exp(-(riskfree+spread)*(d-evaluation).days/365) for d,a in dated_cashflows(term) if d>evaluation)

def tree_value(term,spot,sigma,riskfree,spread,dividend=0.0,steps=401,evaluation=date(2026,9,30),conversion_ratio=None):
    maturity=date.fromisoformat(term['maturity_date'])
    if maturity<=evaluation:
        return max(float(term['redemption_amount_including_last_coupon']),100*spot/float(term['conversion_price']))
    ql.Settings.instance().evaluationDate=qdate(evaluation.isoformat())
    dc=ql.Actual365Fixed(); issue=qdate(term['issue_date'])
    dates=[issue]+[qdate(d.isoformat()) for d,_ in dated_cashflows(term)]
    schedule=ql.Schedule(dates,ql.NullCalendar(),ql.Unadjusted)
    target=json.loads(term['coupon_rates']) if isinstance(term['coupon_rates'],str) else term['coupon_rates']
    # Adjust annualized rates so exact contractual coupon amounts survive leap/short periods.
    coupons=[float(c)/100/dc.yearFraction(dates[i],dates[i+1]) for i,c in enumerate(target)]
    redemption=float(term['redemption_amount_including_last_coupon'])-float(target[-1])
    start=max(evaluation,date.fromisoformat(term['conversion_start']))
    exercise=ql.AmericanExercise(qdate(start.isoformat()),qdate(maturity.isoformat()))
    ratio=conversion_ratio if conversion_ratio is not None else 100/float(term['conversion_price'])
    bond=ql.ConvertibleFixedCouponBond(exercise,ratio,ql.CallabilitySchedule(),issue,0,coupons,dc,schedule,redemption)
    ed=qdate(evaluation.isoformat())
    risk=ql.YieldTermStructureHandle(ql.FlatForward(ed,riskfree,dc))
    div=ql.YieldTermStructureHandle(ql.FlatForward(ed,dividend,dc))
    vol=ql.BlackVolTermStructureHandle(ql.BlackConstantVol(ed,ql.NullCalendar(),max(.01,sigma),dc))
    process=ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(spot)),div,risk,vol)
    bond.setPricingEngine(ql.BinomialConvertibleEngine(process,'crr',steps,ql.QuoteHandle(ql.SimpleQuote(spread))))
    return float(bond.NPV())  # evaluation=settlement; full value per 100 face.
