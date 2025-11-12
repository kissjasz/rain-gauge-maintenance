
#!/usr/bin/env python3
"""
weather_monthly_batch_v3k_showall_najax.py
- Keeps AJAX path (POST-A, POST-B, POST-C) from v3j
- If AJAX fails and we use Non-AJAX full postback, also performs **Non-AJAX Show All**:
  GET -> POST-B (non-AJAX) -> parse Show All target -> POST-C (non-AJAX __EVENTTARGET)
- Saves HTML snapshots for diagnostics when --save-html
"""

import argparse, os, re, json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import requests, pandas as pd
from bs4 import BeautifulSoup
import weather_monthly_enhanced as wme

BASE = "http://eecmobile1.fortiddns.com"
DATA_PATH = "/eec/Raingauge_Data.aspx"
TARGET_PREFIX = "ctl00$UpdatePanel1"

AJAX_HEADERS = {
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "*/*",
    "Origin": BASE,
    "Referer": BASE + DATA_PATH,
}

def _load_thai_station_names():
    """โหลดชื่อสถานีภาษาไทยจาก JSON config"""
    try:
        config_file = os.path.join(os.path.dirname(__file__), "Latlonstation_config.json")
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Cannot load Latlonstation_config.json: {e}")
        return {}

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

def _extract_all_updatepanel_fragments(text: str) -> str:
    if not text or "|" not in text: return ""
    parts = text.split("|")
    html_list = []
    i = 0
    while i < len(parts) - 3:
        if parts[i] == "updatePanel":
            payload = parts[i+3] if i+3 < len(parts) else ""
            html_list.append(payload)
            i += 4
        else:
            i += 1
    return "\n".join(html_list)

def _find_result_table_in_html(html: str):
    soup = _soup(html)
    # Try common ids
    for tid in ("ctl00_ContentPlaceHolder1_gvWOR","GridView1","gvData","ctl00_ContentPlaceHolder1_GridView1"):
        t = soup.find("table", id=tid)
        if t: return t, tid
    # Try by RowStyle classes
    t = soup.find("table", class_=re.compile(r"(RowStyle_ITC|AltRowStyle_ITC)", re.I))
    if t: return t, t.get("id") or "(no-id)"
    # Fallback: biggest table
    tables = soup.find_all("table")
    if not tables: return None, None
    best = max(tables, key=lambda x: (len(x.find_all("th"))*3 + len(x.find_all("td"))))
    return best, best.get("id") or "(no-id)"

def _parse_table(table) -> list:
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
    session.post(url,data=payload,headers=AJAX_HEADERS,timeout=90)

def _extract_show_all_target_from_html(html: str) -> str:
    # Prioritize a button/link containing "Show All Records"
    # Capture only the target from its onclick/postback
    m = re.search(r"<(?:button|a)[^>]+onclick=\"__doPostBack\('([^']+)',''\)\"[^>]*>\s*Show\s+All\s+Records\s*</(?:button|a)>", html, flags=re.I)
    if m: return m.group(1)
    # Fallback: any __doPostBack, but prefer ones that look like GridView targets
    ms = re.findall(r"__doPostBack\('([^']+)',''\)", html, flags=re.I)
    for t in ms:
        if "$gvWOR$" in t or "gvWOR" in t:
            return t
    return ms[0] if ms else ""

def _filter_rows(rows: list, station_code: str, date_ddmmyyyy: str) -> list:
    want_date = date_ddmmyyyy
    out = []
    for r in rows:
        code = r.get("CODE") or r.get("Code") or r.get("code")
        if code and code.upper() != station_code.upper():
            continue
        ts = r.get("LATEST DATA (UTC)") or r.get("Time") or r.get("TIME") or ""
        if ts and len(ts) >= 10:
            if ts[:10] != want_date:
                continue
        out.append(r)
    return out

def fetch_daily(session,station_code,date_ddmmyyyy,time_hhmm,*,debug=False,save_html_dir=""):
    url=BASE+DATA_PATH
    # GET fresh hidden
    r=session.get(url,timeout=60, headers={"Referer": BASE + "/"})
    form=_pick_form(_soup(r.text)); hid=_hidden(form)

    # Try AJAX search first
    payloadB={**hid,
        "ctl00$ContentPlaceHolder1$dl_RAINGAUGE":station_code,
        "ctl00$ContentPlaceHolder1$tbDate":date_ddmmyyyy,
        "ctl00$ContentPlaceHolder1$tbTime":time_hhmm,
        "ctl00$ContentPlaceHolder1$btSearch":"Search",
        "ctl00$ScriptManager1":f"{TARGET_PREFIX}|ctl00$ContentPlaceHolder1$btSearch",
        "__ASYNCPOST":"true"}
    if debug: print(f"[POST-B] {station_code} {date_ddmmyyyy} {time_hhmm}")
    rB=session.post(url,data=payloadB,headers=AJAX_HEADERS,timeout=90)
    rawB=rB.text
    fragB=_extract_all_updatepanel_fragments(rawB)
    htmlB = fragB if fragB else rawB

    if save_html_dir:
        os.makedirs(save_html_dir, exist_ok=True)
        with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_B_raw.txt"),"w",encoding="utf-8") as f: f.write(rawB)
        with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_B.html"),"w",encoding="utf-8") as f: f.write(htmlB)

    t, tid = _find_result_table_in_html(htmlB)
    rows=_parse_table(t) if t else []

    # If likely paged or empty, try AJAX Show All
    show_all_target = _extract_show_all_target_from_html(htmlB)
    if (not rows or len(rows) < 200) and show_all_target:
        if debug: print(f"[POST-C/AJAX] Show All __EVENTTARGET={show_all_target}")
        rC0=session.get(url,timeout=60)
        formC=_pick_form(_soup(rC0.text)); hidC=_hidden(formC)
        payloadC={**hidC,
            "__EVENTTARGET": show_all_target,
            "__EVENTARGUMENT": "",
            "ctl00$ContentPlaceHolder1$dl_RAINGAUGE":station_code,
            "ctl00$ContentPlaceHolder1$tbDate":date_ddmmyyyy,
            "ctl00$ContentPlaceHolder1$tbTime":time_hhmm,
            "ctl00$ScriptManager1": f"{TARGET_PREFIX}|{show_all_target}",
            "__ASYNCPOST":"true"}
        rC=session.post(url,data=payloadC,headers=AJAX_HEADERS,timeout=90)
        rawC=rC.text
        fragC=_extract_all_updatepanel_fragments(rawC)
        htmlC = fragC if fragC else rawC
        if save_html_dir:
            with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_C_ajax_raw.txt"),"w",encoding="utf-8") as f: f.write(rawC)
            with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_C_ajax.html"),"w",encoding="utf-8") as f: f.write(htmlC)
        t2, tid2 = _find_result_table_in_html(htmlC)
        rows=_parse_table(t2) if t2 else rows
        if debug and rows: print(f"[DEBUG] After AJAX Show All: table={tid2} rows={len(rows)}")

    # If still <200, do Non-AJAX full postback search and non-AJAX Show All
    if not rows or len(rows) < 200:
        if debug: print("[FALLBACK] Non-AJAX full postback + Show All")
        rN0=session.get(url,timeout=60)
        formN=_pick_form(_soup(rN0.text)); hidN=_hidden(formN)
        payloadN={**hidN,
            "ctl00$ContentPlaceHolder1$dl_RAINGAUGE":station_code,
            "ctl00$ContentPlaceHolder1$tbDate":date_ddmmyyyy,
            "ctl00$ContentPlaceHolder1$tbTime":time_hhmm,
            "ctl00$ContentPlaceHolder1$btSearch":"Search"}
        rN=session.post(url,data=payloadN,timeout=90)
        htmlN=rN.text
        if save_html_dir:
            with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_N_search.html"),"w",encoding="utf-8") as f: f.write(htmlN)
        tN, tidN = _find_result_table_in_html(htmlN)
        rows=_parse_table(tN) if tN else []

        # Non-AJAX Show All
        show_all_target_N = _extract_show_all_target_from_html(htmlN)
        if (not rows or len(rows) < 200) and show_all_target_N:
            if debug: print(f"[POST-C/NON-AJAX] Show All __EVENTTARGET={show_all_target_N}")
            soupN = _soup(htmlN); formN2=_pick_form(soupN); hidN2=_hidden(formN2)
            payloadNC={**hidN2,
                "__EVENTTARGET": show_all_target_N,
                "__EVENTARGUMENT": "",
                # Preserve station/date/time
                "ctl00$ContentPlaceHolder1$dl_RAINGAUGE":station_code,
                "ctl00$ContentPlaceHolder1$tbDate":date_ddmmyyyy,
                "ctl00$ContentPlaceHolder1$tbTime":time_hhmm}
            rNC=session.post(url,data=payloadNC,timeout=90)
            htmlNC=rNC.text
            if save_html_dir:
                with open(os.path.join(save_html_dir,f"{station_code}_{date_ddmmyyyy.replace('/','-')}_N_showall.html"),"w",encoding="utf-8") as f: f.write(htmlNC)
            tNC, tidNC = _find_result_table_in_html(htmlNC)
            rows=_parse_table(tNC) if tNC else rows
            if debug and rows: print(f"[DEBUG] After NON-AJAX Show All: table={tidNC} rows={len(rows)}")

    # Filter to exact station and date
    rows = _filter_rows(rows, station_code, date_ddmmyyyy)
    
    # เลือกข้อมูลชุดสุดท้ายของแต่ละวัน (timestamp สูงสุด)
    if rows:
        from datetime import datetime
        
        def get_timestamp(row):
            ts = row.get("LATEST DATA (UTC)") or row.get("Time") or row.get("TIME") or ""
            try:
                return datetime.strptime(ts, "%d/%m/%Y %H:%M:%S")
            except:
                return datetime.min
        
        # เรียงตาม timestamp และเลือกตัวสุดท้าย (เวลาสูงสุดของวัน)
        rows = sorted(rows, key=get_timestamp)[:1]

    # Normalize
    norm=[]
    for rrow in rows:
        rr={k.strip():v for k,v in rrow.items()}
        def pick(keys):
            for k in rr:
                lk=k.lower()
                if any(p in lk for p in keys):
                    return rr[k]
            return ""
        rr["_timeUTC"]=rr.get("LATEST DATA (UTC)", pick(["time","latest"]))
        rr["_rain_mm"]=rr.get("24HR (mm)", pick(["24hr","rain"]))
        rr["_temp_c"]=pick(["temp"])
        rr["_humidity_"]=pick(["humidity","hum"])
        norm.append(rr)
    return norm

def month_range(y,m):
    start=datetime(y,m,1)
    end=datetime(y+1,1,1)-timedelta(days=1) if m==12 else datetime(y,m+1,1)-timedelta(days=1)
    return start,end
# >>> ADD BELOW month_range
def _parse_dt(s):
    from datetime import datetime
    try:
        return datetime.strptime(s, "%d/%m/%Y %H:%M:%S")
    except Exception:
        return None

def _sort_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["_dt"] = df["_timeUTC"].apply(_parse_dt)
    df.sort_values(by=["date", "_dt"], ascending=[True, True], inplace=True, kind="mergesort")
    return df.drop(columns=["_dt"])

def fetch_one_station_month(session,st,y,m,*,debug=False,save_html=False,outdir="weather_data"):
    code=st["code"]
    name=st["name"]  # ชื่อภาษาอังกฤษเดิม
    
    # โหลดชื่อภาษาไทย
    thai_names = _load_thai_station_names()
    if code in thai_names:
        name = thai_names[code].get("name_th", name)  # ใช้ชื่อไทย ถ้ามี
    
    rows=[]
    # set station may help session state
    post_a_set_station(session, code, debug=debug)
    start,end=month_range(y,m); cur=start
    save_dir=os.path.join(outdir,"_html") if save_html else ""
    while cur<=end:
        ds=cur.strftime("%d/%m/%Y")
        data=fetch_daily(session,code,ds,"23:59",debug=debug,save_html_dir=save_dir)
        if debug: print(f"[INFO] {code} {ds} rows={len(data)}")
        for r in data: r.update({"station_code":code,"station_name":name,"date":ds})
        rows.extend(data); cur+=timedelta(days=1)
    df=pd.DataFrame(rows)
    cols=["station_code","station_name","date","_timeUTC","_rain_mm","_temp_c","_humidity_"]
    for c in cols:
        if c not in df.columns: df[c] = ""
    df=df[cols]
    for c in ["_rain_mm","_temp_c","_humidity_"]:
        df[c]=pd.to_numeric(df[c], errors="coerce")
        df = _sort_df(df)
    return code,name,df,rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--user",required=True); ap.add_argument("--pass",dest="password",required=True)
    ap.add_argument("--year",type=int,required=True); ap.add_argument("--month",type=int,required=True)
    ap.add_argument("--outdir",default="weather_data")
    ap.add_argument("--csv",action="store_true"); ap.add_argument("--excel",action="store_true")
    ap.add_argument("--combined-csv",action="store_true"); ap.add_argument("--combined-excel",action="store_true")
    ap.add_argument("--filter",default=""); ap.add_argument("--debug",action="store_true")
    ap.add_argument("--workers",type=int,default=1); ap.add_argument("--save-html",action="store_true")
    args=ap.parse_args()

    os.makedirs(args.outdir,exist_ok=True)
    s=wme.login(args.user,args.password,debug=args.debug)

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

    if args.combined_csv or args.combined_excel:
        combo = pd.concat(combined, ignore_index=True) if combined else pd.DataFrame(columns=["station_code","station_name","date","_timeUTC","_rain_mm","_temp_c","_humidity_","year","month"])
        if args.combined_csv:
            out=os.path.join(args.outdir,f"weather_combined_{args.year}_{args.month:02d}.csv")
            combo.to_csv(out,index=False,encoding="utf-8-sig"); print(f"[OK] Combined CSV {out} rows={len(combo)}")
        if args.combined_excel:
            outx=os.path.join(args.outdir,f"weather_combined_{args.year}_{args.month:02d}.xlsx")
            with pd.ExcelWriter(outx, engine="xlsxwriter") as writer:
                combo.to_excel(writer, index=False, sheet_name="data")
            print(f"[OK] Combined XLSX {outx} rows={len(combo)}")
    print(f"[DONE] total rows={total}")

if __name__=="__main__":
    main()
