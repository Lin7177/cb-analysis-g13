# 恢复说明（2026-10-05）：本脚本自老仓库 git（scripts/collect_a_research.py @ eb3b64a）字节级恢复——
# A线财报与公告证据采集器（东财报表 API + 巨潮公告/PDF），其产出 work/A/results.csv（57列完整打分依据层）
# 已同步恢复为 b-quant/data/inputs/a_results_original.csv。历史冻结：内部路径按老仓库布局书写，运行前需适配。
"""Public financial statements and issuer announcement collection for Group 13.

Run: python scripts/collect_a_research.py
Cached responses allow reproducible --offline runs. Amounts are CNY yuan.
No data after the information cutoff is used in financial comparisons.
"""
from pathlib import Path
import argparse, concurrent.futures, datetime as dt, hashlib, json, re, sys
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'data/cache/A'; OUT=ROOT/'data/curated'; WORK=ROOT/'work/A'
T='2026-09-30'
ENDPOINT='https://datacenter-web.eastmoney.com/api/data/v1/get'
HEAD={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'}
NOW=dt.datetime.now(dt.timezone.utc).isoformat()
SOURCES=[]
OFFLINE=False

def cached(key,url,params=None,post=False):
    p=CACHE/(key+'.json')
    if p.exists(): return json.loads(p.read_text(encoding='utf8'))
    if OFFLINE: raise RuntimeError(f'missing cached input {key}')
    for i in range(3):
        try:
            r=requests.post(url,data=params,headers=HEAD,timeout=40) if post else requests.get(url,params=params,headers=HEAD,timeout=40)
            r.raise_for_status(); obj=r.json()
            p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
            return obj
        except Exception:
            if i==2: raise

def issuer(row):
    code=str(row['正股代码']).zfill(6); exchange=row['正股唯一键'].split(':')[0]
    financial={}
    for typ in ['INCOME','BALANCE','CASHFLOW']:
        report='RPT_DMSK_FN_'+typ
        params={'reportName':report,'columns':'ALL','filter':f'(SECURITY_CODE="{code}")(REPORT_DATE>=\'2025-06-30\')(REPORT_DATE<=\'2026-06-30\')','pageSize':50,'pageNumber':1,'sortColumns':'REPORT_DATE','sortTypes':-1}
        obj=cached(f'{code}_{typ}',ENDPOINT,params)
        assert obj.get('success'),obj
        records=obj['result']['data'];financial[typ]={x['REPORT_DATE'][:10]:x for x in records if x.get('NOTICE_DATE') and x['NOTICE_DATE'][:10]<=T}
    top=cached(f'{code}_org','https://www.cninfo.com.cn/new/information/topSearch/query',{'keyWord':code,'maxNum':10},True)
    org=next(x['orgId'] for x in top if x['code']==code)
    anns=[]
    for tag,search in [('h1','2026年半年度报告'),('annual','2025年年度报告'),('rating','2026年跟踪评级'),('events','转债')]:
        params={'pageNum':1,'pageSize':50,'column':'sse' if exchange=='SH' else 'szse','tabName':'fulltext','plate':'sh' if exchange=='SH' else 'sz','stock':code+','+org,'searchkey':search,'secid':'','category':'','trade':'','seDate':'2026-01-01~2026-09-30' if tag!='events' else '2026-07-01~2026-09-30','sortName':'time','sortType':'desc','isHLtitle':'true'}
        obj=cached(f'{code}_ann_{tag}','https://www.cninfo.com.cn/new/hisAnnouncement/query',params,True)
        for a in obj.get('announcements') or []:
            a=dict(a); a['kind']=tag;a['title']=re.sub('<[^>]+>','',a['announcementTitle']);a['url']='https://static.cninfo.com.cn/'+a['adjunctUrl'];a['published_date']=dt.datetime.fromtimestamp(a['announcementTime']/1000,dt.timezone(dt.timedelta(hours=8))).date().isoformat();anns.append(a)
    # Full H1 and annual report; rating reports; event summaries are indexed, not treated as read.
    selected=[]
    for tag,needle in [('h1','2026年半年度报告'),('annual','2025年年度报告')]:
        choices=[a for a in anns if a['kind']==tag and needle in a['title'] and not any(s in a['title'] for s in ['摘要','取消','提示','说明会','更正'])]
        if choices: selected.append(max(choices,key=lambda a:a['adjunctSize']))
    ratings=[a for a in anns if a['kind']=='rating' and '评级' in a['title']]
    if ratings: selected.append(max(ratings,key=lambda a:a['adjunctSize']))
    events=[a for a in anns if a['kind']=='events' and a['published_date']<T and any(s in a['title'] for s in ['赎回','修正','调整'])]
    for i,a in enumerate(events[:2]):
        a['cache_tag']='event'+str(i+1);selected.append(a)
    # Latest events: full dated source register retained for assessment.
    for a in selected:
        pdf=CACHE/f"{code}_{a.get('cache_tag',a['kind'])}.pdf"
        if (not pdf.exists() or b'%%EOF' not in pdf.read_bytes()[-1000:]) and not OFFLINE:
            for trial in range(3):
                r=requests.get(a['url'],params={'audit':'complete'+str(trial)},headers=HEAD,timeout=100);r.raise_for_status()
                if r.content[:4]==b'%PDF' and b'%%EOF' in r.content[-1000:]:
                    pdf.write_bytes(r.content);break
            else:raise ValueError(f'incomplete issuer PDF {a["url"]}')
        a['cache_file']=str(pdf.relative_to(ROOT));a['sha256']=hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else ''
    inc=financial['INCOME']['2026-06-30'];bal=financial['BALANCE']['2026-06-30'];cf=financial['CASHFLOW']['2026-06-30'];prior=financial['INCOME'].get('2025-06-30',{});pcf=financial['CASHFLOW'].get('2025-06-30',{});annual=financial['INCOME'].get('2025-12-31',{})
    d={'bond_key':row['债券唯一键'],'stock_key':row['正股唯一键'],'bond_name':row['债券简称'],'issuer':row['正股简称'],'industry':row['行业'],'financial_period':'2026-06-30','financial_notice_date':inc['NOTICE_DATE'][:10],'revenue_yuan':inc['TOTAL_OPERATE_INCOME'],'revenue_yoy_pct':inc['TOI_RATIO'],'net_profit_yuan':inc['PARENT_NETPROFIT'],'net_profit_yoy_pct':inc['PARENT_NETPROFIT_RATIO'],'deducted_profit_yuan':inc['DEDUCT_PARENT_NETPROFIT'],'operating_cashflow_yuan':cf['NETCASH_OPERATE'],'prior_h1_revenue_yuan':prior.get('TOTAL_OPERATE_INCOME'),'prior_h1_net_profit_yuan':prior.get('PARENT_NETPROFIT'),'prior_h1_operating_cashflow_yuan':pcf.get('NETCASH_OPERATE'),'cash_yuan':bal['MONETARYFUNDS'],'total_assets_yuan':bal['TOTAL_ASSETS'],'total_liabilities_yuan':bal['TOTAL_LIABILITIES'],'short_borrowings_yuan':bal['SHORT_LOAN'],'debt_asset_ratio_pct':bal['DEBT_ASSET_RATIO'],'current_ratio_raw_provider_pct':bal['CURRENT_RATIO'],'current_ratio':bal['CURRENT_RATIO']/100,'accounts_receivable_yuan':bal['ACCOUNTS_RECE'],'inventory_yuan':bal['INVENTORY'],'annual_2025_revenue_yuan':annual.get('TOTAL_OPERATE_INCOME'),'annual_2025_profit_yuan':annual.get('PARENT_NETPROFIT'),'h1_pdf':next((a['url'] for a in selected if a['kind']=='h1'),''),'annual_pdf':next((a['url'] for a in selected if a['kind']=='annual'),''),'rating_pdf':next((a['url'] for a in selected if a['kind']=='rating'),'')}
    for a in anns:
        source_path=ROOT/a['cache_file'] if a.get('cache_file') else CACHE/f'{code}_ann_{a["kind"]}.json'
        retrieved=dt.datetime.fromtimestamp(source_path.stat().st_mtime,dt.timezone.utc).isoformat()
        SOURCES.append({'bond_key':d['bond_key'],'stock_key':d['stock_key'],'kind':a['kind'],'title':a['title'],'published_date':a['published_date'],'retrieved_at_utc':retrieved,'url':a['url'],'cache_file':a.get('cache_file',''),'sha256':a.get('sha256',''),'read_status':'downloaded_pending_read' if a in selected else 'index_only','page_reference':''})
    for typ in financial:
        retrieved=dt.datetime.fromtimestamp((CACHE/f'{code}_{typ}.json').stat().st_mtime,dt.timezone.utc).isoformat()
        SOURCES.append({'bond_key':d['bond_key'],'stock_key':d['stock_key'],'kind':'financial_api_'+typ,'title':'Eastmoney public structured consolidated statements','published_date':d['financial_notice_date'],'retrieved_at_utc':retrieved,'url':ENDPOINT+'?reportName=RPT_DMSK_FN_'+typ+'&columns=ALL&filter=(SECURITY_CODE%3D%22'+code+'%22)','cache_file':f'data/cache/A/{code}_{typ}.json','read_status':'parsed','page_reference':'API REPORT_DATE 2026-06-30; units CNY yuan'})
    print(code,d['issuer'],round(d['revenue_yuan']/1e8,3),round(d['net_profit_yuan']/1e8,3),round(d['operating_cashflow_yuan']/1e8,3),len(anns),flush=True)
    return d

def main():
    global OFFLINE
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');args=ap.parse_args();OFFLINE=args.offline
    CACHE.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    rows=pd.read_csv(ROOT/'work/universe_v1.csv',dtype=str).to_dict('records')
    records=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fs={pool.submit(issuer,r):r for r in rows}
        for f,r in fs.items():
            try:records.append(f.result())
            except Exception as e:errors.append({'bond_key':r['债券唯一键'],'error':repr(e)});print('ERROR',r['债券简称'],repr(e),flush=True)
    df=pd.DataFrame(records).sort_values('bond_key');df.to_csv(OUT/'a_financial_group13.csv',index=False,encoding='utf-8-sig');pd.DataFrame(SOURCES).to_csv(WORK/'sources.csv',index=False,encoding='utf-8-sig')
    (OUT/'a_financial_group13.manifest.json').write_text(json.dumps({'observation_date':T,'information_cutoff':'2026-09-30 15:00 Asia/Shanghai','retrieved_at_utc':NOW,'financial_unit':'CNY yuan','rows':len(df),'errors':errors,'source_caveat':'Provider statements are cross-checked to issuer H1 PDFs. Annual rows are not compared directly to H1 periods.'},ensure_ascii=False,indent=2),encoding='utf8')
    assert not errors,errors
    # pypdf ships with the desktop document runtime; no package installation required.
    bundle=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages'
    sys.path.append(str(bundle))
    from pypdf import PdfReader
    for p in CACHE.glob('*.pdf'):
        if '_annual' in p.name:continue
        dest=p.with_suffix('.txt')
        if not dest.exists():
            reader=PdfReader(p)
            dest.write_text('\n'.join(f'\n=== PDF PAGE {i+1} ===\n'+(page.extract_text() or '') for i,page in enumerate(reader.pages)),encoding='utf8')
    render_research()

def render_research():
    notes=json.loads((OUT/'a_notes_group13.json').read_text(encoding='utf8'))
    df=pd.read_csv(OUT/'a_financial_group13.csv');rows=[];sources=pd.read_csv(WORK/'sources.csv').fillna('')
    money=lambda v:f'{v/1e8:.2f}'
    doc=['# A路线：18券发行人、行业、信用与条款研究',
         '\n实际研究底稿，研究口径：2026-09-30收盘、当日15:00前公开信息；六个月新增买入背景。A独立判断发行人经营与信用，不代替B债券定价及最终3+3。由AI研究团队实施，逐券研究责任与讲解归属可调整，成员后续真实复核/修改贡献另行登记。',
         '\n## 如何使用与复算',
         '\n负责人先读全池比较和统一规范，再按券查正文。`results.csv`用于全池整合，`sources.csv`逐条列来源、公开日期、获取时间及实际阅读状态。运行 `python scripts/collect_a_research.py --offline` 可复现已缓存财务、PDF核验和研究输出；联网重跑不意味着采用观察日后新信息。人工解释保存在 `data/curated/a_notes_group13.json`，双版课堂内容保存在 `data/curated/a_presentation_group13.json`；改解释须有来源与理由。',
         '\n## 行业框架与全池比较',
         '\n课程池12券轻工、6券家电；实际还须细分地产链家居/陶瓷、纸与包装、出口消费制造、清洁电器、压缩机零件及集成灶。地产链共同承压不代表所有轻工公司同向，出口订单/汇率、包装产能与产品结构、家电新品/零件成本各有不同驱动。行业事实引用发行人报告并标明其归属，不把发行人预测当已实现事实，也不把单家公司情况扩展为全行业统计。',
         '\n2026H1统一合并口径，财务金额亿元；归母/扣非利润区分，亏损改善不用同比增长误称扭亏。2025年全年只作历史基线，不与半年度绝对量作增长比较。',
         '\n|券|细分|收入/同比|归母/扣非|经营现金流|2025全年收入/归母|当前评级|A判断|',
         '|---|---|---:|---:|---:|---:|---|---|']
    for _,r in df.iterrows():
        code=r.stock_key.split(':')[1];n=notes[code]
        doc.append(f'|{r.bond_name}|{n["subsector"]}|{money(r.revenue_yuan)}/{r.revenue_yoy_pct:+.2f}%|{money(r.net_profit_yuan)}/{money(r.deducted_profit_yuan)}|{money(r.operating_cashflow_yuan)}|{money(r.annual_2025_revenue_yuan)}/{money(r.annual_2025_profit_yuan)}|{n["rating"]}|{n["direction"]}|')
    doc+=['\n## 统一研究规范与逐券责任',
           '\n共同投资问题：在未来六个月、不加杠杆且重视下行的新增买入背景下，发行人的经营预期是否有持续盈利、现金与信用支持，条款行为怎样约束持有，哪些预期还须交给B检验价格补偿？这一问题覆盖18券，不由个人三券组合决定。',
           '\n六人各负责三券，均按行业、公司经营财务、信用、经营条件展望、条款行为五项规范完整研究，并记录问题、方法、正反证核验、判断和改判条件。研究归属可以由负责人调整，不把个人三券宣称为天然同行比较组；分工不等于学生已经完成独立贡献。',
           '\n|研究项目|统一回答与核验要求|', '|---|---|',
           '|行业与经营机制|辨认细分需求、成本、渠道和客户变化；区分发行人披露与全行业统计。|',
           '|经营与财务|检验增长来源、归母与扣非、经营现金及资本投入；不以规模或单一同比决定判断。|',
           '|偿债与信用|核对现金类资产口径、受限/币种/期限、债务及到期安排；评级是证据之一。|',
           '|六个月经营展望|提出可证伪的业务条件；不创造未经验证的股价预测模型。|',
           '|条款与发行人行为|区分机械调价、主动下修、提示、决议、实施及承诺期限；有效数值由B1验收。|',
           '|方法与反证|将管理层解释与本期财务、现金来源、债务和条款结果交叉判断；逐字核对只能验证数值，不能代替经济解释。|',
           '\n|责任|三券研究归属|', '|---|---|',
           '|A1|特纸、永吉、艾录|', '|A2|江山、欧22、志邦|', '|A3|金23、蒙娜、帝欧|',
           '|A4|乐歌、海顺、嘉益|', '|A5|科沃、莱克、翔26|', '|A6|火星、亿田、小熊|',
           '\n## 两版课堂汇报的共用底稿',
           '\n主版每人65秒：本人三券独立诊断总览25秒，一项重要判断的方法、反证核验与结论40秒。三券正文均完整保留，详述一券只是课堂选例；不在20分钟内逐券等量展开。备用版按行业需求成本、业务结构与增长来源、盈利质量、现金偿债信用、六个月经营驱动、条款发行人行为六个全池主题汇报，每主题65秒。两版共用18券底稿、同一报告、B证据和最终六案；主题汇报人汇总共享证据，不另行重做18券研究。',
           '\n## 信用与条款的共同解释边界',
           '\n货币资金含受限款，短借不含票据、租赁及全部一年内到期项目；本表补列到期负债但不简单把现金除短债当违约概率。应付债券是摊余成本账面值，不是T未转股面额。现金流受营运资本、保证金、退税及补贴影响；正现金流不是保证永远偿债。评级只用已读官方原件/发行人公告，不采用课程清单作为当前评级；等级不对应精确信用利差。',
           '\n条款分析区分权益分派机械调整、主动下修、触发提示、董事会决议、实施；未发现索引不证明没有事件。A解释发行人经营意愿与业务机制，T有效数值和模型约束由B1统一核验。9月30日只有日期而无时点的公告不当作15:00已知信息。',
           '\n## 逐券正文']
    for _,r in df.iterrows():
        code=r.stock_key.split(':')[1];n=notes[code];p=CACHE/f'{code}_h1.txt';text=p.read_text(encoding='utf8');parts=re.split(r'=== PDF PAGE (\d+) ===',text)
        refs={}
        for field in ['revenue_yuan','net_profit_yuan','deducted_profit_yuan','operating_cashflow_yuan','cash_yuan','total_assets_yuan','total_liabilities_yuan']:
            target=f'{r[field]:.2f}';hits=[parts[i] for i in range(1,len(parts),2) if target in re.sub(r'[,\s]','',parts[i+1])]
            assert hits,(code,field,target)
            refs[field]=hits[:3]
        for field in ['short_loan','current_noncurrent','long_loan','bond_book']:
            if n[field]!=0:
                assert f'{n[field]:.2f}' in re.sub(r'[,\s]','',text),(code,field,n[field])
        record=r.to_dict();record.update(n);record['current_ratio']=r.current_ratio;record['short_borrowings_yuan']=n['short_loan'];record['current_noncurrent_liabilities_yuan']=n['current_noncurrent'];record['long_borrowings_yuan']=n['long_loan'];record['bonds_book_yuan']=n['bond_book'];record['pdf_crosscheck']='7 monetary fields exact match';record['pdf_page_refs']=json.dumps(refs,ensure_ascii=False);record['a_direction']=n['direction'];record['positive_evidence']=n['positive'];record['negative_evidence']=n['negative'];record['change_condition']=n['condition'];record['business_mechanism']=n['mechanism'];rows.append(record)
        doc.extend([f'\n### {n["unit"]} · {r.bond_name} / {r.issuer} · {r.bond_key}',
                    f'\n**判断：{n["direction"]}。** {n["business"]}',
                    f'\n2026H1收入{money(r.revenue_yuan)}亿元（同比{r.revenue_yoy_pct:+.2f}%），归母{money(r.net_profit_yuan)}亿元、扣非{money(r.deducted_profit_yuan)}亿元；经营现金流{money(r.operating_cashflow_yuan)}亿元，上年同期{money(r.prior_h1_operating_cashflow_yuan)}亿元。资产负债率{r.debt_asset_ratio_pct:.2f}%，流动比率{r.current_ratio:.2f}倍。',
                    f'\n货币资金{money(r.cash_yuan)}亿元；短借{money(n["short_loan"])}亿元，一年内到期非流动负债{money(n["current_noncurrent"])}亿元，长期借款{money(n["long_loan"])}亿元，应付债券账面值{money(n["bond_book"])}亿元。当前评级{n["rating"]}，前次{n["rating_previous"]}。',
                    f'\n**正向证据/必须保留的反证：**{n["positive"]}',
                    f'\n**负向证据：**{n["negative"]}',
                    f'\n**信用解释：**{n["credit"]}',
                    f'\n**条款与发行人行为：**{n["terms"]}',
                    f'\n**六个月经营驱动：**{n["mechanism"]}',
                    f'\n**改判条件：**{n["condition"]}',
                    f'\n**出处：**[2026半年报]({r.h1_pdf})，{n["pages"]}；信用等级见{n["rating_page"]}'+(f'、[评级原件或结果公告]({r.rating_pdf})。' if isinstance(r.rating_pdf,str) else '。')])
        if code in ['603486','603801','002798','300911']:
            event_rows=sources[(sources.stock_key==r.stock_key)&(sources.kind=='events')&(sources.cache_file!='')]
            doc.append('\n条款已读原件：'+'；'.join(f'[{er["published_date"]} {er["title"]}]({er["url"]})' for _,er in event_rows.iterrows()))
            sources.loc[event_rows.index,'read_status']='event_original_read';sources.loc[event_rows.index,'page_reference']='全文；触发条件与决议区分'
        mask=(sources.stock_key==r.stock_key)&(sources.kind=='h1')&(sources.cache_file!='')
        sources.loc[mask,'read_status']='financial_exact_crosscheck_and_management_read';sources.loc[mask,'page_reference']=n['pages']+'；数值页码'+json.dumps(refs,ensure_ascii=False)
        mask=(sources.stock_key==r.stock_key)&(sources.kind=='rating')&(sources.cache_file!='')
        sources.loc[mask,'read_status']='rating_conclusion_read' if code!='603058' else 'scanned_pdf_rating_crosschecked_H1_p45';sources.loc[mask,'page_reference']=n['rating_page']
    doc+=['\n## 形成联合案例的使用方式',
          '\nA方向是经营/信用证据，不是最终债券买入结论。六案须引用B的当前价格、可适用估值和下行证据：科沃盈利增长需问价格/低权益弹性；海顺增长需问亏损与低估是否足够补偿；莱克现金好需问扣非薄利与短债；特纸成长需问扩张信用及买价；永吉需识别基金收益与价贵；帝欧须同时保留现金改善和BBB+；亿田须同时保留亏损收窄和算力负毛利。',
          '\n## 来源覆盖与限制',
          '\n已采集18/18官方2026半年报及2025年报，逐券将7项关键金额与半年报全文精确匹配。现金债务补录自合并资产负债表；评级17份原件/结果公告，其中永吉PDF为扫描件，用半年报45页交叉核实；科沃评级由半年报62页确认。年报作为原件缓存与历史基线，并不声称全文每页已审。',
          '\n全部初稿使用真实已取得证据；未来经营条件是分析假设，不是发生事实。发行人行业统计和管理层展望注明归属，课程池也不构成分散全市场投资组合。sources.csv中的index_only公告未当作已审原文。必要的有效条款/定价输入由B1专项原件验收，不能凭A事件摘要代替。']
    validate_presentation_content(rows, sources)
    pd.DataFrame(rows).to_csv(WORK/'results.csv',index=False,encoding='utf-8-sig')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts={x.name for x in font_manager.fontManager.ttflist}
    plt.rcParams['font.sans-serif']=[x for x in ['Microsoft YaHei','SimHei','Noto Sans CJK SC','DejaVu Sans'] if x in fonts]
    plt.rcParams['axes.unicode_minus']=False
    plot=pd.DataFrame(rows).sort_values(['unit','bond_key']);fig,axes=plt.subplots(1,2,figsize=(14,9),sharey=True,gridspec_kw={'width_ratios':[1,1.6]})
    y=list(range(len(plot)))
    axes[0].barh(y,plot.revenue_yoy_pct,color=['#2d826f' if x>=0 else '#bf655a' for x in plot.revenue_yoy_pct]);axes[0].set_yticks(y,plot.bond_name);axes[0].set_xlabel('营业收入同比（%）');axes[0].axvline(0,color='#777',lw=.8)
    axes[1].barh([v-.18 for v in y],plot.deducted_profit_yuan/1e8,height=.35,label='扣非归母净利润',color='#477da8');axes[1].barh([v+.18 for v in y],plot.operating_cashflow_yuan/1e8,height=.35,label='经营现金流',color='#d39a47');axes[1].set_xlabel('金额（亿元）');axes[1].axvline(0,color='#777',lw=.8);axes[1].legend(loc='lower right')
    axes[0].invert_yaxis();fig.suptitle('第13组18券发行人：增长、经常性利润与现金转化（2026H1）',fontsize=16)
    fig.text(.12,.025,'来源：各发行人2026半年报，7项金额已逐券与官方全文匹配。\n不同细分业务不按收入规模排名；经营现金流含营运资本等影响，不能等同可持续利润。',fontsize=10)
    fig.tight_layout(rect=[0,.07,1,.94]);fig.savefig(WORK/'全池财务比较.png',dpi=160);plt.close(fig)
    doc.insert(doc.index('\n## 统一研究规范与逐券责任'),'\n![18券财务比较](全池财务比较.png)')
    (WORK/'研究说明.md').write_text('\n'.join(doc)+'\n',encoding='utf8');sources.to_csv(WORK/'sources.csv',index=False,encoding='utf-8-sig')
    (OUT/'a_financial_group13_pdf_checks.json').write_text(json.dumps({'rows':18,'check':'7 monetary values exact normalized string match in each official H1 PDF','current_ratio_fix':'provider field is percent; divided by100 for multiple','short_borrowings':'API null replaced by explicit issuer consolidated balance sheet, blank statement cells reported0','units':'CNY yuan; rendered report CNY100million','source_page_refs':{r['bond_key']:r['pdf_page_refs'] for r in rows}},ensure_ascii=False,indent=2),encoding='utf8')

def validate_presentation_content(records, sources):
    """Keep curated classroom explanations separate; verify their real chart bindings.

    Collection must not regenerate artificial comparison groups or infer decisions.
    Changing an issuer assignment requires updating both its notes and classroom unit.
    """
    p=OUT/'a_presentation_group13.json'
    content=json.loads(p.read_text(encoding='utf8'))
    by_key={r['bond_key']:r for r in records}
    members=content['member_units']; themes=content['theme_units']
    assert len(members)==6 and len(themes)==6
    assigned=[k for u in members for k in u['bond_keys']]
    assert len(assigned)==18 and len(set(assigned))==18 and set(assigned)==set(by_key)
    assert {u['owner'] for u in members}=={f'A{i}' for i in range(1,7)}
    for u in members:
        assert len(u['bond_keys'])==3 and len(u['overview'])==3
        assert {r['bond_key'] for r in u['overview']}==set(u['bond_keys'])
        assert all(by_key[k]['unit']==u['owner'] for k in u['bond_keys'])
        assert u['overview_seconds']==25 and u['deep_dive']['seconds']==40
        assert u['deep_dive']['bond_key'] in u['bond_keys']
    for u in themes:
        assert u['seconds']==65 and set(u['evidence_pool_keys'])==set(by_key)
        assert set(u['example_bond_keys'])<=set(by_key)
    grouped=[k for r in content['full_pool_summary']['classification'] for k in r['bond_keys']]
    assert len(grouped)==18 and len(set(grouped))==18 and set(grouped)==set(by_key)
    valid_urls=set(sources.url)
    def visit(obj):
        if isinstance(obj,dict):
            if 'url' in obj and 'bond_key' in obj:
                assert obj['bond_key'] in by_key and obj['url'] in valid_urls, obj
            if 'series' in obj and 'source_fields' in obj:
                assert len(obj['series'])==len(obj['source_fields'])
                for series, bindings in zip(obj['series'],obj['source_fields']):
                    assert len(series['values'])==len(bindings)==len(obj['categories'])
                    for value, ref in zip(series['values'],bindings):
                        if 'field' in ref:
                            expected=float(by_key[ref['bond_key']][ref['field']])/ref.get('scale',1)
                        else:
                            fact=content['supplemental_facts'][ref['supplemental_fact']]
                            assert fact['bond_key']==ref['bond_key']
                            expected=fact['value']/ref.get('scale',1)
                        assert abs(value-expected)<1e-6,(ref,value,expected)
            for value in obj.values():visit(value)
        elif isinstance(obj,list):
            for value in obj:visit(value)
    visit(content)

if __name__=='__main__':main()
