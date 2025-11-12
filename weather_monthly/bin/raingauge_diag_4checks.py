
#!/usr/bin/env python3
"""
raingauge_diag_4checks.py
Usage:
  python raingauge_diag_4checks.py --user USER --pass PASS --station G1001 --date 05/11/2025 --time 23:59 --outdir diag_4c --debug
"""

import argparse, os, re, json
import requests
from bs4 import BeautifulSoup

import weather_monthly_enhanced as wme

BASE = "http://eecmobile1.fortiddns.com"
DATA_PATH = "/eec/Raingauge_Data.aspx"
TARGET_PREFIX = "ctl00$UpdatePanel1"

def save_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def parse_updatepanel_fragment(text: str) -> str:
    if not text or "|" not in text:
        return ""
    parts = text.split("|")
    html_chunks = []
    i = 0
    # pattern: |updatePanel|<id>|<len>|<html>...
    while i < len(parts) - 3:
        if parts[i] == "updatePanel":
            html_chunks.append(parts[i+3])
            i += 4
        else:
            i += 1
    return "\n".join(html_chunks)

def pick_form(soup: BeautifulSoup):
    form = soup.find("form", id="form1") or soup.find("form")
    if not form:
        raise RuntimeError("form not found")
    return form

def hidden(form):
    d = {}
    for name in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION"):
        el = form.find("input", {"name": name})
        if el and el.has_attr("value"):
            d[name] = el["value"]
    d.setdefault("__EVENTTARGET","")
    d.setdefault("__EVENTARGUMENT","")
    return d

def find_result_table(soup: BeautifulSoup):
    # priority ids
    for tid in ("ctl00_ContentPlaceHolder1_gvWOR","GridView1","gvData","ctl00_ContentPlaceHolder1_GridView1"):
        t = soup.find("table", id=tid)
        if t:
            return t, tid
    # by row class
    t = soup.find("table", class_=re.compile("RowStyle_ITC|AltRowStyle_ITC", re.I))
    if t:
        return t, t.get("id") or "(no-id)"
    return None, None

def extract_one_data_tr(table) -> str:
    tr = table.find("tr", class_=re.compile("RowStyle_ITC|AltRowStyle_ITC", re.I))
    return str(tr) if tr else ""

def build_curl(url: str, data: dict, headers: dict):
    # Mask huge fields but keep size
    masked = {}
    for k,v in data.items():
        if k in ("__VIEWSTATE","__EVENTVALIDATION"):
            masked[k] = f"<{k}:{len(v)} bytes>"
        else:
            masked[k] = v
    # build curl
    parts = [f"curl '{url}' -X POST"]
    for hk, hv in headers.items():
        parts.append(f"-H '{hk}: {hv}'")
    parts.append("--data-raw '" + "&".join([f"{requests.utils.quote(k, safe='')}={requests.utils.quote(v, safe='')}" for k,v in data.items()]) + "'")
    return "\n  ".join(parts), masked

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="password", required=True)
    ap.add_argument("--station", required=True, help="e.g., G1001")
    ap.add_argument("--date", required=True, help="DD/MM/YYYY")
    ap.add_argument("--time", required=True, help="HH:MM")
    ap.add_argument("--outdir", default="diag_4c")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    # Login
    sess = wme.login(args.user, args.password, debug=args.debug)

    # === Check 2) GET page fields existence ===
    url = BASE + DATA_PATH
    r0 = sess.get(url, timeout=60)
    save_text(os.path.join(args.outdir, "GET_initial.html"), r0.text)
    soup0 = BeautifulSoup(r0.text, "html.parser")
    form0 = pick_form(soup0)
    hid0 = hidden(form0)

    sm_input = soup0.find("input", {"name": "ctl00$ScriptManager1"})
    has_sm_input = sm_input is not None
    print(f"[CHECK] ScriptManager input present: {has_sm_input}")
    print(f"[CHECK] Hidden fields present: " +
          ", ".join([f"{k}:{'Y' if k in hid0 and hid0[k] else 'N'}" for k in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION")]))

    # === Build POST-B and show fields (Item 3) ===
    ddl_name = "ctl00$ContentPlaceHolder1$dl_RAINGAUGE"
    tb_date  = "ctl00$ContentPlaceHolder1$tbDate"
    tb_time  = "ctl00$ContentPlaceHolder1$tbTime"
    bt_search= "ctl00$ContentPlaceHolder1$btSearch"

    payloadB = {
        **hid0,
        ddl_name: args.station,
        tb_date: args.date,
        tb_time: args.time,
        bt_search: "Search",
        "ctl00$ScriptManager1": f"{TARGET_PREFIX}|{bt_search}",
        "__ASYNCPOST": "true",
    }
    headers = {"X-MicrosoftAjax": "Delta=true"}

    curl_cmd, masked = build_curl(url, payloadB, headers)
    save_text(os.path.join(args.outdir, "POST-B_fields.json"), json.dumps(masked, indent=2, ensure_ascii=False))
    save_text(os.path.join(args.outdir, "POST-B_curl.txt"), curl_cmd)
    print("[INFO] Wrote POST-B fields -> POST-B_fields.json, and cURL -> POST-B_curl.txt")

    # === Do POST-B (no POST-A; WebForms often tolerates direct search) ===
    rB = sess.post(url, data=payloadB, headers=headers, timeout=90)
    rawB = rB.text
    save_text(os.path.join(args.outdir, "POST-B_raw.txt"), rawB)

    frag = parse_updatepanel_fragment(rawB)
    html_to_parse = frag if frag else rawB
    save_text(os.path.join(args.outdir, "POST-B_effective.html"), html_to_parse)

    # === Item 1) print first 500 chars of HTML ===
    head500 = html_to_parse[:500].replace("\n", " ")
    print(f"[HEAD500] {head500}")

    # === Find table and extract one row (Items 4) ===
    soup_eff = BeautifulSoup(html_to_parse, "html.parser")
    table, table_id = find_result_table(soup_eff)
    if table:
        one_tr = extract_one_data_tr(table)
        save_text(os.path.join(args.outdir, "POST-B_one_tr.html"), one_tr if one_tr else "<no-data-row-found>")
        print(f"[TABLE] Found table id={table_id}. One <tr> saved to POST-B_one_tr.html")
        # Also count rows with RowStyle_ITC / AltRowStyle_ITC
        n_rows = len(soup_eff.find_all("tr", class_=re.compile("RowStyle_ITC|AltRowStyle_ITC", re.I)))
        print(f"[TABLE] Row count by class (RowStyle_ITC|AltRowStyle_ITC): {n_rows}")
    else:
        print("[TABLE] No table found")

if __name__ == "__main__":
    main()
