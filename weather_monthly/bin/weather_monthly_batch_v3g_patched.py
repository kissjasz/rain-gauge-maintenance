
#!/usr/bin/env python3
"""
weather_monthly_batch_v3g_patched.py
- Explicit POST-A to set station once per run
- For each day: GET fresh hidden fields, POST-B search, extract UpdatePanel fragment
- More robust fragment parsing and HTML fallbacks
"""

import argparse, os, re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import requests, pandas as pd
from bs4 import BeautifulSoup
import weather_monthly_enhanced as wme

BASE = "http://eecmobile1.fortiddns.com"
DATA_PATH = "/eec/Raingauge_Data.aspx"
TARGET_PREFIX = "ctl00$UpdatePanel1"

def _soup(html): return BeautifulSoup(html, "html.parser")

def _pick_form(soup):
    form = soup.find("form", id="form1") or soup.find("form")
    if not form: raise RuntimeError("form not found")
    return form

def _hidden(form):
    d = {}
    for name in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION"):
        el = form.find("input", {"name": name})
        if el and el.has_attr("value"): d[name] = el["value"]
    d.setdefault("__EVENTTARGET",""); d.setdefault("__EVENTARGUMENT","")
    return d

def _extract_updatepanel_fragment(text: str, panel_id: str = "ctl00_UpdatePanel1") -> str:
    # strict token parsing
    if not text or "|" not in text: return ""
    parts = text.split("|")
    html_list = []
    i = 0
    while i < len(parts) - 3:
        if parts[i] == "updatePanel":
            pid = parts[i+1] if i+1 < len(parts) else ""
            # parts[i+2] is length (may be wrong), parts[i+3] is html payload
            payload = parts[i+3] if i+3 < len(parts) else ""
            if not panel_id or pid == panel_id:
                html_list.append(payload)
            i += 4
        else:
            i += 1
    return "\n".join(html_list)

def _find_result_table_in_html(html: str):
    soup = _soup(html)
    for tid in ("ctl00_ContentPlaceHolder1_gvWOR","GridView1","gvData","ctl00_ContentPlaceHolder1_GridView1"):
        t = soup.find("table", id=tid)
        if t: return t
    t = soup.find("table", class_=re.compile(r"(RowStyle_ITC|AltRowStyle_ITC)", re.I))
    if t: return t
    tables = soup.find_all("table")
    if not tables: return None
    return max(tables, key=lambda x: (len(x.find_all("th"))*3 + len(x.find_all("td"))))

def _parse_table(table) -> List[Dict]:
    rows=[]; headers=[]
    thead=table.find("thead")
    if thead: headers=[th.get_text(strip=True) for th in thead.find_all("th")]
    if not headers:
        first_tr=table.find("tr")
        if first_tr: headers=[th.get_text(strip=True) for th in first_tr.find_all(["th","td"])]
    trs=table.find_all("tr")
    start = 1 if trs and trs[0].find_all("th") else 0
    for tr in trs[start:]:
        cells=[td.get_text(" ",strip=True) for td in tr.find_all("td")]
        if not cells: continue
        row={headers[i] if i<len(headers) else f"col{i+1}":v for i,v in enumerate(cells)}
        rows.append(row)
    return rows

def _parse_codes_and_names_from_select(html: str):
    soup=_soup(html)
    sel=soup.find("select",id="ctl00_ContentPlaceHolder1_dl_RAINGAUGE") or soup.find("select",{"name":"ctl00$ContentPlaceHolder1$dl_RAINGAUGE"})
    res={}
    if not sel: return res
    for opt in sel.find_all("option"):
        val=(opt.get("value") or "").strip()
        if not val or val.startswith("--"): continue
        text=opt.get_text(" ",strip=True)
        name=text.split(" - ",1)[1].strip() if " - " in text else text
        res[val]={"code":val,"name":name,"status":"UNKNOWN"}
    return res

def station_listing(session) -> Dict[str, Dict]:
    r=session.get(BASE+DATA_PATH,timeout=60)
    return _parse_codes_and_names_from_select(r.text)

def post_a_set_station(session, station_code, *, debug=False):
    # GET to get hidden, then fire dropdown change via __EVENTTARGET
    url=BASE+DATA_PATH
    r=session.get(url,timeout=60)
    form=_pick_form(_soup(r.text)); hid=_hidden(form)
    ddl="ctl00$ContentPlaceHolder1$dl_RAINGAUGE"
    payload={**hid,
        "__EVENTTARGET": ddl,
        "__EVENTARGUMENT": "",
        ddl: station_code,
        "ctl00$ContentPlaceHolder1$tbDate":"",
        "ctl00$ContentPlaceHolder1$tbTime":"",
        "ctl00$ScriptManager1": f"{TARGET_PREFIX}|{ddl}",
        "__ASYNCPOST": "true"}
    headers={"X-MicrosoftAjax":"Delta=true"}
    if debug: print(f"[POST-A] set {station_code}")
    session.post(url,data=payload,headers=headers,timeout=90)

def fetch_daily(session,station_code,date_ddmmyyyy,time_hhmm,*,debug=False,save_html_dir=""):
    url=BASE+DATA_PATH
    # Refresh hidden per day
    r=session.get(url,timeout=60)
    form=_pick_form(_soup(r.text)); hid=_hidden(form)
    payload={**hid,
        "ctl00$ContentPlaceHolder1$dl_RAINGAUGE":station_code,
        "ctl00$ContentPlaceHolder1$tbDate":date_ddmmyyyy,
        "ctl00$ContentPlaceHolder1$tbTime":time_hhmm,
        "ctl00$ContentPlaceHolder1$btSearch":"Search",
        "ctl00$ScriptManager1":f"{TARGET_PREFIX}|ctl00$ContentPlaceHolder1$btSearch",
        "__ASYNCPOST":"true"}
    headers={"X-MicrosoftAjax":"Delta=true"}
    if debug: print(f"[POST-B] {station_code} {date_ddmmyyyy} {time_hhmm}")
    r2=session.post(url,data=payload,headers=headers,timeout=90)
    raw=r2.text

    frag=_extract_updatepanel_fragment(raw,"ctl00_UpdatePanel1")
    html = frag if frag else raw

    # fallback: if still no table, try a plain GET after POST-B
    t=_find_result_table_in_html(html)
    if not t:
        r3=session.get(url,timeout=60)
        html2=r3.text
        t=_find_result_table_in_html(html2)
        if t: html=html2

    if save_html_dir:
        os.makedirs(save_html_dir, exist_ok=True)
        with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}.html"),"w",encoding="utf-8") as f:
            f.write(html)

    if not t:
        if debug: print("[WARN] result table not found")
        return []

    raw_rows=_parse_table(t)
    norm=[]
    for rrow in raw_rows:
        rr={k.strip():v for k,v in rrow.items()}
        def pick(keys):
            for k in rr:
                lk=k.lower()
                if any(p in lk for p in keys):
                    return rr[k]
            return ""
        rr["_time"]=rr.get("LATEST DATA (UTC)", pick(["time","latest"]))
        rr["_rain_mm"]=rr.get("24HR (mm)", pick(["24hr","rain"]))
        rr["_battery_v"]=pick(["batt"])
        rr["_solar_v"]=pick(["solar"])
        rr["_temp_c"]=pick(["temp"])
        rr["_hum_pct"]=pick(["humidity","hum"])
        norm.append(rr)
    return norm

def month_range(y,m):
    start=datetime(y,m,1)
    end=datetime(y+1,1,1)-timedelta(days=1) if m==12 else datetime(y,m+1,1)-timedelta(days=1)
    return start,end

def fetch_one_station_month(session,st,y,m,*,debug=False,save_html=False,outdir="weather_data"):
    code=st["code"]; name=st["name"]; rows=[]
    post_a_set_station(session, code, debug=debug)
    start,end=month_range(y,m); cur=start
    save_dir=os.path.join(outdir,"_html") if save_html else ""
    while cur<=end:
        ds=cur.strftime("%d/%m/%Y")
        data=fetch_daily(session,code,ds,"23:59",debug=debug,save_html_dir=save_dir)
        if debug: print(f"[INFO] {code} {ds} rows={len(data)}")
        for r in data: r.update({"station_code":code,"station_name":name,"date":ds})
        rows.extend(data); cur+=timedelta(days=1)
    return code,name,pd.DataFrame(rows),rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--user",required=True); ap.add_argument("--pass",dest="password",required=True)
    ap.add_argument("--year",type=int,required=True); ap.add_argument("--month",type=int,required=True)
    ap.add_argument("--outdir",default="weather_data")
    ap.add_argument("--csv",action="store_true"); ap.add_argument("--excel",action="store_true")
    ap.add_argument("--combined-csv",action="store_true")
    ap.add_argument("--filter",default=""); ap.add_argument("--debug",action="store_true")
    ap.add_argument("--workers",type=int,default=1); ap.add_argument("--save-html",action="store_true")
    args=ap.parse_args()

    os.makedirs(args.outdir,exist_ok=True)
    s=wme.login(args.user,args.password,debug=args.debug)

    # station list from select
    r=s.get(BASE+DATA_PATH,timeout=60)
    stations=_parse_codes_and_names_from_select(r.text)
    if not stations: raise SystemExit("No stations listed")
    selected=list(stations.values())
    if args.filter.strip():
        terms=[t.strip().upper() for t in args.filter.split(",") if t.strip()]
        selected=[st for st in selected if any(term in st["code"].upper() for term in terms)]

    results=[]
    for st in selected:
        results.append(fetch_one_station_month(s,st,args.year,args.month,debug=args.debug,save_html=args.save_html,outdir=args.outdir))

    combined=[]; total=0
    for code,name,df,raw in results:
        total+=len(df)
        if args.csv:
            p=os.path.join(args.outdir,f"weather_{code}_{args.year}_{args.month:02d}.csv")
            df.to_csv(p,index=False,encoding="utf-8-sig"); print(f"[OK] CSV {p} rows={len(df)}")
        if args.excel:
            try:
                wme.export_to_excel_with_charts(raw, {"code": code, "name": name}, args.year, args.month, os.path.join(args.outdir, f"weather_{code}_{args.year}_{args.month:02d}.xlsx"))
            except Exception:
                x=os.path.join(args.outdir,f"weather_{code}_{args.year}_{args.month:02d}.xlsx")
                df.to_excel(x,index=False); print(f"[OK] XLSX {x} rows={len(df)}")
        if not df.empty:
            df2=df.copy(); df2["year"]=args.year; df2["month"]=args.month; combined.append(df2)

    if args.combined_csv or (not args.csv and not args.excel):
        out=os.path.join(args.outdir,f"weather_combined_{args.year}_{args.month:02d}.csv")
        if combined:
            pd.concat(combined,ignore_index=True).to_csv(out,index=False,encoding="utf-8-sig")
        else:
            pd.DataFrame(columns=["station_code","station_name","date","_time","_rain_mm","_battery_v","_solar_v","_temp_c","_hum_pct","year","month"]).to_csv(out,index=False,encoding="utf-8-sig")
        print(f"[OK] Combined CSV {out}")
    print(f"[DONE] total rows={total}")

if __name__=="__main__":
    main()
