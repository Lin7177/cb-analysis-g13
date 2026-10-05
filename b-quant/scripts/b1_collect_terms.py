# 恢复说明（2026-10-05）：本脚本自老仓库 git（scripts/collect_b_terms.py @ b24c242）字节级恢复——
# 它是 B1_verified 公告证据缓存（387 PDF + 1032 JSON，缓存本体按决策留在老仓库 data/cache/，未入库）与
# data/curated/terms_verified.csv 的采集器。历史冻结：内部 ROOT 相对路径按老仓库布局书写（work/B_methods 等），
# 当前布局下运行前需适配；恢复原因：主PPT条款/溢价数字的公告原文证据层再获取能力（N3）。
"""Collect public issuer announcement mirrors and build traceable Group13 terms.

python scripts/collect_b_terms.py --collect downloads immutable issuer documents
through Eastmoney's public announcement index. Without --collect, rerun cached
evidence extraction. Current provider quotes remain candidates until supported
by documents published on or before T; financial statements are not terms.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import unicodedata
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'data/cache/B1_verified'
OUT=ROOT/'work/B_methods/B1'
T='2026-09-30'
INDEX='https://np-anotice-stock.eastmoney.com/api/security/ann'
CONTENT='https://np-cnotice-stock.eastmoney.com/api/content/ann'
PROVIDER='https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BOND_CB_LIST&columns=ALL'

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def fetch(url,params):
    for attempt in range(3):
        try:
            resp=requests.get(url,params=params,timeout=40,headers={'User-Agent':'Mozilla/5.0'})
            resp.raise_for_status(); result=resp.json()
            if result.get('data') is None: raise ValueError('empty data')
            return result
        except (requests.RequestException, ValueError):
            if attempt==2: raise
            time.sleep(1+attempt)

def notices(stock,start,end,label):
    path=CACHE/f'{stock}_{label}_index.json'
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))['rows']
    rows=[]; page=1
    while True:
        params={'sr':-1,'page_size':100,'page_index':page,'ann_type':'A','client_source':'web','stock_list':stock,'begin_time':start,'end_time':end}
        data=fetch(INDEX,params)['data']; rows.extend(data['list'])
        if len(rows)>=data['total_hits'] or not data['list']: break
        page+=1
    dump(path,{'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'url':INDEX,'params':params,'rows':rows})
    return rows

def content(art):
    path=CACHE/f"{art['art_code']}.json"
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    result=fetch(CONTENT,{'art_code':art['art_code'],'client_source':'web','page_index':1})
    result['retrieved_at_utc']=datetime.now(timezone.utc).isoformat()
    result['index_record']=art
    dump(path,result)
    return result

def collect_one(base,p):
    stock=base['stock_key'].split(':')[1]
    current=notices(stock,'2026-01-01',T,'2026')
    issue=p['VALUE_DATE'][:10]
    issuance=notices(stock,issue[:4]+'-01-01',issue[:4]+'-12-31','issuance')
    keywords=('转股','赎回','回售','下修','付息','信用评级','跟踪评级','募集说明书','上市公告书','受托管理事务')
    picked=[a for a in current if any(k in a['title'] for k in keywords)]
    picked += [a for a in issuance if any(k in a['title'] for k in ('募集说明书','上市公告书')) and '转' in a['title']]
    seen=set(); errors=[]
    for a in picked:
        if a['art_code'] in seen: continue
        seen.add(a['art_code'])
        try: content(a)
        except Exception as exc: errors.append((a['art_code'],str(exc)))
    print(base['bond_key'], 'documents',len(seen),'errors',len(errors),flush=True)
    return errors

def compact(s): return re.sub(r'\s+','',unicodedata.normalize('NFKC',s or ''))
def date(s): return (s or '')[:10]

def coupon_sequence(s):
    found=re.search(r'第一年(?:为)?(\d+(?:\.\d+)?)%',s)
    if not found: return []
    chunk=s[found.start():found.start()+300]
    rates=[]
    for year in '一二三四五六':
        m=re.search(r'第'+year+r'年(?:为)?(\d+(?:\.\d+)?)%',chunk)
        if not m:return []
        rates.append(float(m.group(1)))
    return rates

def maturity_redemption(s):
    found=re.search(r'(\d+(?:\.\d+)?)(?:%|元)(?:人民币)?[（(]?含最后一期(?:年度)?利息',s)
    return float(found.group(1)) if found else None

def chinese_date(s):
    y,m,d=map(int,s.split('-'));return f'{y}年{m}月{d}日'

def named_date(text,label):
    m=re.search(label+r'(?:为|是|期)?[:：]?(\d{4})年(\d{1,2})月(\d{1,2})日',text)
    return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}' if m else ''

def pdf_one(path):
    from pypdf import PdfReader
    import io
    obj=json.loads(path.read_text(encoding='utf-8')); url=obj['data'].get('attach_url','')
    txt=path.with_suffix('.txt'); pdf=path.with_suffix('.pdf')
    if txt.exists(): return
    if not pdf.exists():
        r=requests.get(url,timeout=90,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status()
        if not r.content.startswith(b'%PDF'): raise ValueError('not PDF '+url)
        pdf.write_bytes(r.content)
    reader=PdfReader(io.BytesIO(pdf.read_bytes()))
    text='\n'.join(f'\n[PDF page {i+1}]\n'+(p.extract_text() or '') for i,p in enumerate(reader.pages))
    txt.write_text(text,encoding='utf-8')
    print('PDF',obj['index_record']['art_code'],len(reader.pages),flush=True)

def collect_pdfs(base):
    paths=list(CACHE.glob('AN*.json')); selected=[]
    for b in base:
        stock=b['stock_key'].split(':')[1]
        ds=[]
        for path in paths:
            obj=json.loads(path.read_text(encoding='utf-8'));a=obj['index_record']
            if any(c['stock_code']==stock for c in a['codes']):ds.append((path,a))
        trustee=sorted([(p,a) for p,a in ds if '受托管理' in a['title'] and '2025年度' in a['title']],key=lambda x:x[1]['display_time'],reverse=True)
        listing=sorted([(p,a) for p,a in ds if '上市公告书' in a['title']],key=lambda x:x[1]['display_time'],reverse=True)
        selected += [x[0] for x in trustee[:1]+listing[:1]]
    with ThreadPoolExecutor(max_workers=3) as ex:
        fs=[ex.submit(pdf_one,p) for p in set(selected)]
        for f in as_completed(fs):
            try: f.result()
            except Exception as exc: print('PDF unavailable',str(exc),flush=True)

def cninfo_one(b,p,orgs,history_only=False):
    stock=b['stock_key'].split(':')[1]; org=orgs[stock]
    column='sse' if b['stock_key'].startswith('SH') else 'szse'
    iy=int(p['VALUE_DATE'][:4])
    queries=[('coupon_history','付息',f'{iy}-01-01',T)] if history_only else [('listing_extended','上市公告书',f'{iy}-01-01',f'{iy+1}-12-31')]+[('2026_'+kw,kw,'2026-01-01',T) for kw in ['受托管理','付息','转股','赎回','回售','评级','到期']]
    for label,keyword,start,end in queries:
        index=CACHE/f'{stock}_cninfo_{label}.json'
        if index.exists(): anns=json.loads(index.read_text(encoding='utf-8'))['announcements']
        else:
            anns=[];page=1
            while True:
                for attempt in range(3):
                    try:
                        r=requests.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',data={'pageNum':page,'pageSize':100,'column':column,'tabName':'fulltext','stock':stock+','+org,'searchkey':keyword,'seDate':start+'~'+end,'isHLtitle':'true'},headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'},timeout=40);r.raise_for_status();data=r.json();break
                    except (requests.RequestException,ValueError):
                        if attempt==2:raise
                        time.sleep(2+attempt)
                batch=data.get('announcements') or [];anns.extend(batch)
                if len(anns)>=data.get('totalAnnouncement',0) or not batch:break
                page+=1
            dump(index,{'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'announcements':anns,'source_url':'https://www.cninfo.com.cn/new/hisAnnouncement/query'})
        for a in anns:
            title=re.sub('<[^>]+>','',a['announcementTitle'])
            path=CACHE/f"AN_CN{a['announcementId']}.json"
            url='https://static.cninfo.com.cn/'+a['adjunctUrl']
            # The disclosed date is conservative: same-day announcements count only
            # if a separate timestamp establishes public availability by 15:00.
            d=a['adjunctUrl'].split('/')[1]
            if not path.exists():dump(path,{'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'index_record':{'art_code':'CN'+a['announcementId'],'title':title,'codes':[{'stock_code':stock}],'display_time':d+' 23:59:59','notice_date':d,'source_type':'cninfo_official','publication_time_precision':'date_only_conservative_end_of_day'},'data':{'attach_url':url,'notice_content':''}})
            # Full listings and trustee reports are necessary for cashflow audit.
            if label.startswith('listing') or any(kw in title for kw in ('受托管理','转股','赎回','回售','付息','评级')):
                try:pdf_one(path)
                except Exception as exc:print('OfficialPDFerror',b['bond_key'],str(exc),flush=True)
    print('CNinfo',b['bond_key'],flush=True)

def writecsv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--collect',action='store_true');parser.add_argument('--pdfs',action='store_true');parser.add_argument('--cninfo',action='store_true');parser.add_argument('--couponhistory',action='store_true');parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if args.offline and any((args.collect,args.pdfs,args.cninfo,args.couponhistory)):parser.error('--offline cannot be combined with network collection flags')
    base=list(csv.DictReader((OUT/'base_v1.csv').open(encoding='utf-8-sig')))
    providers=json.loads((ROOT/'data/cache/B1/eastmoney_cb_pages.json').read_text(encoding='utf-8'))
    by={r['SECURITY_CODE']:r for r in providers['rows']}
    if args.cninfo or args.couponhistory:
        op=CACHE/'cninfo_stock_list.json'
        if not op.exists():
            r=requests.get('https://www.cninfo.com.cn/new/data/szse_stock.json',timeout=40);r.raise_for_status();dump(op,r.json())
        orgs={s['code']:s['orgId'] for s in json.loads(op.read_text(encoding='utf-8'))['stockList']}
        with ThreadPoolExecutor(max_workers=4) as ex:
            fs=[ex.submit(cninfo_one,b,by[b['bond_key'].split(':')[1]],orgs,args.couponhistory) for b in base]
            for f in as_completed(fs):f.result()
    if args.collect:
        with ThreadPoolExecutor(max_workers=4) as ex:
            fs=[ex.submit(collect_one,b,by[b['bond_key'].split(':')[1]]) for b in base]
            for f in as_completed(fs): f.result()
    if args.pdfs: collect_pdfs(base)
    docs=[]
    for path in CACHE.glob('AN*.json'):
        obj=json.loads(path.read_text(encoding='utf-8'));a=obj['index_record']; text=path.with_suffix('.txt').read_text(encoding='utf-8') if path.with_suffix('.txt').exists() else obj['data'].get('notice_content','')
        if a.get('source_type')=='cninfo_official':
            a['notice_date']=obj['data']['attach_url'].split('/')[-2]
            a['display_time']=date(a['notice_date'])+' 23:59:59'
        if a['display_time'][:19] > T+' 15:00:00': continue
        docs.append({'art':a,'text':compact(text),'url':obj['data'].get('attach_url',''),'path':path.relative_to(ROOT).as_posix(),'hash':hashlib.sha256(path.read_bytes()).hexdigest()})
    rows=[]; flows=[]; sources=[]; evidence=[]; events=[]
    for b in base:
        p=by[b['bond_key'].split(':')[1]];stock=b['stock_key'].split(':')[1]
        relevant=sorted([d for d in docs if any(c['stock_code']==stock for c in d['art']['codes'])],key=lambda d:d['art']['display_time'],reverse=True)
        rates=[float(x) for x in re.findall(r'(\d+(?:\.\d+)?)%',p['INTEREST_RATE_EXPLAIN'])]
        if len(rates)!=6: raise ValueError((b['bond_key'],'coupon rates',rates))
        redeem=re.search(r'(\d+(?:\.\d+)?)%[（(]?含最后一期(?:年度)?利息',compact(p['REDEEM_CLAUSE']))
        if not redeem: raise ValueError((b['bond_key'],'redemption clause'))
        amount=float(redeem.group(1))
        k=float(p['TRANSFER_PRICE'])
        kdocs=[d for d in relevant if any(x in d['text'] for x in (f'{k:.2f}元/股',f'{k:g}元/股',f'{k:.2f}元／股',f'{k:g}元／股')) and ('转股价格' in d['text'] or '转股价' in d['text'])]
        cashdocs=[d for d in relevant if coupon_sequence(d['text'])==rates and maturity_redemption(d['text'])==amount]
        # Automatic matches require manual review; retain provider candidate status.
        officialk=[d for d in kdocs if d['url'].startswith('https://static.cninfo.com.cn/')]
        kdoc=(officialk or kdocs)[0] if kdocs else None
        official=[d for d in cashdocs if d['url'].startswith('https://static.cninfo.com.cn/')]
        cdoc=(official or cashdocs)[0] if cashdocs else None
        row={'bond_key':b['bond_key'],'bond_name':b['bond_name'],'stock_key':b['stock_key'],'observation_date':T,'conversion_price':k,'issue_date':date(p['VALUE_DATE']),'maturity_date':date(p['EXPIRE_DATE']),'conversion_start':date(p['TRANSFER_START_DATE']),'conversion_end':date(p['TRANSFER_END_DATE']),'coupon_rates':json.dumps(rates),'redemption_amount_including_last_coupon':amount,'rating':p['RATING'],'rating_date':'','known_call_put_events':'','source_url':kdoc['url'] if kdoc else PROVIDER,'published_at':kdoc['art']['display_time'][:19] if kdoc else '', 'effective_date':'','cashflow_source_url':cdoc['url'] if cdoc else PROVIDER,'verification_status':'document_matches_pending_manual_review' if kdoc and cdoc else 'provider_candidate_with_partial_document_support','conversion_price_status':'document_numeric_match' if kdoc else 'provider_candidate','cashflow_status':'document_numeric_match' if cdoc else 'provider_candidate','latest_term_doc':kdoc['art']['title'] if kdoc else '', 'cashflow_doc':cdoc['art']['title'] if cdoc else '', 'retrieved_at_utc':providers['retrieved_at_utc']}
        rows.append(row)
        # Legal maturity is the final contractual day, not provider EXPIRE_DATE
        # (which is often the first day after the six-year interest period).
        row['maturity_date']=date(p['TRANSFER_END_DATE'])
        row['provider_expire_date']=date(p['EXPIRE_DATE'])
        row['cashflow_status']='issuer_cashflow_sequence_matched' if cdoc else 'provider_candidate'
        row['conversion_price_status']='issuer_current_price_matched' if kdoc else 'provider_candidate'
        row['cashflow_verification_detail']='six_coupon_rates_and_inclusive_redemption_numeric_sequence'
        row['conversion_price_confirmation_date']=date(kdoc['art']['display_time']) if kdoc else ''
        row['index_search_period']='2026-01-01 to 2026-09-30; exact public timestamp filtered <=15:00'
        row['verification_status']='issuer_core_terms_verified_with_documented_limits' if kdoc and cdoc else 'incomplete_core_terms'
        row['rating_status']='provider_candidate_pending_credit_research_confirmation'
        ratingfile=OUT/'rating_verification.json'
        if ratingfile.exists():
            rating=json.loads(ratingfile.read_text(encoding='utf-8'))[b['bond_key']]
            row['rating']=rating['rating'];row['rating_date']=rating['published_date'];row['rating_source_url']=rating['url'];row['rating_status']='issuer_or_rating_agency_source_crosschecked_by_A';row['rating_date_type']='source_publication_date'
        else:row['rating_source_url']='';row['rating_date_type']='unknown'
        row['conversion_start_status']='issuer_original_contract_date'
        if kdoc:
            match=re.search(r'转股(?:期限|时间|期为)[：:]?(\d{4})年(\d{1,2})月(\d{1,2})日至',kdoc['text'])
            if match:
                row['conversion_start']=f'{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}'
                row['conversion_start_status']='latest_issuer_confirmation'
        relevant_events=[d for d in relevant if b['bond_name'] in d['text'] and any(x in d['art']['title'] for x in ('不向下','不提前赎回','回售结果','即将到期','可能满足赎回')) and not any(x in d['art']['title'] for x in ('核查意见','法律意见','受托管理'))]
        seen_event=set()
        for d in relevant_events:
            title=d['art']['title'].split(':')[-1]
            if title in seen_event:continue
            seen_event.add(title)
            txt=d['text'];m=re.search(r'(?:未来[一二三四五六\d]+个月|本次回售申报期|回售价格|停止交易日|已有10个交易日)',txt)
            excerpt=txt[max(0,m.start()-40):m.start()+360] if m else txt[:420]
            events.append({'bond_key':b['bond_key'],'event_title':title,'published_at':d['art']['display_time'][:19],'event_excerpt':excerpt,'source_url':d['url'],'interpretation_status':'exact_disclosure_excerpt_not_assumed_current_exercise_right'})
        row['known_call_put_events']='; '.join(e['event_title']+' ['+e['published_at'][:10]+']' for e in events if e['bond_key']==b['bond_key'])
        effective_dates={'SH:111002':'2026-06-03','SH:113625':'2025-06-13','SH:113646':'2025-11-19','SH:113655':'2026-08-21','SH:113670':'2026-06-26','SH:113693':'2026-06-23','SZ:123072':'2026-05-28','SZ:123183':'2026-04-28','SZ:123229':'2026-06-18','SZ:123250':'2026-09-23','SZ:127044':'2026-06-18','SZ:127047':'2024-11-01','SH:113633':'2026-07-08','SH:113659':'2024-11-08','SH:113703':'2026-06-08','SZ:123154':'2026-08-07','SZ:123235':'2025-06-03','SZ:127069':'2026-05-28'}
        row['effective_date']=effective_dates.get(b['bond_key'],'')
        row['effective_date_status']='manual_review_of_issuer_history_or_initial_issue' if row['effective_date'] else 'confirmed_current_price_but_last_change_date_unspecified'
        edocs=[d for d in kdocs if chinese_date(row['effective_date']) in d['text']]
        row['effective_date_source_url']=edocs[0]['url'] if edocs else (kdoc['url'] if kdoc else '')
        if cdoc:
            txt=cdoc['text'];pos=txt.find('第一年');red=re.search(r'\d+(?:\.\d+)?(?:%|元)(?:人民币)?[（(]?含最后一期(?:年度)?利息',txt)
            evidence.append({'bond_key':b['bond_key'],'field':'coupon_rates_and_redemption','source_url':cdoc['url'],'cache_file':cdoc['path'],'coupon_excerpt':txt[max(0,pos-70):pos+220],'redemption_excerpt':txt[max(0,red.start()-90):red.start()+80] if red else '', 'actual_value':row['coupon_rates']+'; redemption='+str(amount),'verification':'numeric_sequence_checked_against_cached_provider','sha256_pdf':hashlib.sha256((ROOT/cdoc['path']).with_suffix('.pdf').read_bytes()).hexdigest() if (ROOT/cdoc['path']).with_suffix('.pdf').exists() else ''})
        if kdoc:
            txt=kdoc['text'];pos=txt.find(f'{k:.2f}元');pos=pos if pos>=0 else txt.find(f'{k:g}元')
            evidence.append({'bond_key':b['bond_key'],'field':'current_conversion_price','source_url':kdoc['url'],'cache_file':kdoc['path'],'coupon_excerpt':txt[max(0,pos-100):pos+100],'redemption_excerpt':'','actual_value':str(k),'verification':'T-prior issuer numeric confirmation plus subsequent index review','sha256_pdf':''})
        issued=datetime.fromisoformat(row['issue_date']); totalyear=int(p['BOND_EXPIRE'])
        for year,rate in enumerate(rates,1):
            dt=issued.replace(year=issued.year+year).date().isoformat() if year<totalyear else row['maturity_date']
            coupon_docs=[d for d in relevant if '付息' in d['art']['title'] and (named_date(d['text'],'付息日') or named_date(d['text'],'兑息日') or named_date(d['text'],'除息日'))[:4]==dt[:4]] if year<totalyear else []
            actual=coupon_docs[0] if coupon_docs else None
            actualpay=(named_date(actual['text'],'付息日') or named_date(actual['text'],'兑息日') or named_date(actual['text'],'利息发放日')) if actual else ''
            exdate=named_date(actual['text'],'除息日') if actual else ''
            flows.append({'bond_key':b['bond_key'],'contractual_date':dt,'payment_date':actualpay or dt,'actual_payment_date':actualpay,'ex_date':exdate,'ex_date_verified':str(bool(exdate)).lower(),'coupon_amount':rate if year<totalyear else 0,'redemption_amount':amount if year==totalyear else 0,'cashflow_amount':rate if year<totalyear else amount,'cashflow_type':'coupon' if year<totalyear else 'redemption','coupon_rate_pct':rate,'last_coupon_included_in_redemption':year==totalyear,'payment_date_status':'issuer_actual_payment_date' if actualpay else 'contractual_date_not_actual_exchange_calendar','verification_status':'issuer_coupon_date_verified' if exdate else row['cashflow_status'],'source_url':actual['url'] if actual else row['cashflow_source_url']})
        for d in relevant:
            sources.append({'bond_key':b['bond_key'],'title':d['art']['title'],'published_at':d['art']['display_time'][:19],'notice_date':date(d['art']['notice_date']),'source_url':d['url'],'source_type':'cninfo_official' if d['url'].startswith('https://static.cninfo.com.cn/') else 'issuer_document_via_public_mirror','cache_file':d['path'],'sha256':d['hash'],'numeric_K_match':d in kdocs,'cashflow_numeric_match':d in cashdocs})
    writecsv(OUT/'terms_verified.csv',rows);writecsv(OUT/'cashflows.csv',flows);writecsv(OUT/'source_index.csv',sources);writecsv(OUT/'verification_evidence.csv',evidence)
    if events:writecsv(OUT/'events.csv',events)
    finalbase=[]
    for b,row in zip(base,rows):
        fresh=dict(b)
        fresh['terms_status']=row['verification_status']
        fresh['conversion_price']=row['conversion_price']
        fresh['conversion_value']=round(float(b['stock_close'])*100/row['conversion_price'],6)
        fresh['conversion_premium_pct']=round((float(b['bond_close'])/fresh['conversion_value']-1)*100,6)
        fresh['conversion_price_source_url']=row['source_url']
        fresh['input_information_cutoff']='2026-09-30 15:00 Asia/Shanghai'
        fresh['input_quote_basis']='full_price_per_100_face'
        finalbase.append(fresh)
    writecsv(OUT/'base.csv',finalbase)
    writecsv(ROOT/'data/curated/b_terms_group13_20260930.csv',rows);writecsv(ROOT/'data/curated/b_cashflows_group13_20260930.csv',flows)
    print('Built',len(rows),'terms',len(flows),'cashflows',len(sources),'sources',flush=True)

if __name__=='__main__': main()
