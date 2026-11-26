"""
capacity_cache_V2_patched.py — fetch disk pool (logika sama dengan versi production V4).

Perubahan dari versi production:
  - URL master dan token TIDAK lagi ditulis di file ini; dibaca dari environment / web/.env
    (NBU_TBS_URL, NBU_TBS_TOKEN, NBU_BSD_URL, NBU_BSD_TOKEN, NBU_BRN_URL, NBU_BRN_TOKEN).
  - Logika fetch, transform, dan export tidak diubah.
"""
import requests, urllib3, os, json, traceback
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv opsional; env var biasa tetap dipakai
    load_dotenv = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, ".env"))
CACHE_DIR=os.path.join(BASE_DIR,"cache")
REPORT_DIR=os.path.join(BASE_DIR,"report")
LOG_DIR=os.path.join(BASE_DIR,"logs")
for d in [CACHE_DIR,REPORT_DIR,LOG_DIR]:
    os.makedirs(d,exist_ok=True)

LOG_FILE=os.path.join(LOG_DIR,"update_capacity_log.txt")
HEART=os.path.join(LOG_DIR,"heartbeat.txt")


def _master(key, name, default_url):
    return {
        "name": name,
        "base_url": os.environ.get(f"NBU_{key}_URL", default_url),
        "token": os.environ.get(f"NBU_{key}_TOKEN", ""),
    }


MASTERS={
    "tbs": _master("TBS", "TBS", "https://tbsnbuvpapp1/netbackup"),
    "bsd": _master("BSD", "BSD", "https://bsdnbuvpapp1.telkomsel.co.id/netbackup"),
    "brn": _master("BRN", "BRN", "https://brnnbuvpapp1.telkomsel.co.id/netbackup"),
}

LIMIT=50
NO_PROXY={"http":None,"https":None}

def headers(tok):
    return {"Accept":"application/vnd.netbackup+json;version=11.0","Authorization": f"Bearer {tok}"}
def b2tb(v): return round(v/(1024**4),2)

def fetch_master(master):
    if not master["token"]:
        raise RuntimeError(f"token NBU untuk {master['name']} belum di-set (web/.env)")
    out=[]; offset=0
    while True:
        url=f"{master['base_url']}/storage/disk-pools"
        r=requests.get(url,headers=headers(master["token"]),
                       params={"page[limit]":LIMIT,"page[offset]":offset},
                       verify=False,timeout=30,proxies=NO_PROXY)
        r.raise_for_status()
        js=r.json()
        data=js.get("data",[])
        if not data: break
        for item in data:
            a=item["attributes"]
            if a.get("sType")!="PureDisk":
                continue
            usable=a.get("usableSizeBytes",0)
            avail=a.get("availableSpaceBytes",0)
            used=a.get("usedCapacityBytes",0)
            pct=round((used/usable)*100,2) if usable else 0
            site = master["name"]
            rel = item.get("relationships", {})
            ss = rel.get("storageServers", {}).get("data", [])
            if ss:
                sid = ss[0].get("id","")
                if ":" in sid:
                    host = sid.split(":",1)[1].split(".",1)[0]
                    site = host[:3].upper()
            name=a.get("name","")
            if any(x in name for x in ["brnnbupapp1","brnnbupapp2","brnnbupapp3","nbubrnlpapp1"]):
                continue
            out.append({
                "Site":site,
                "Master":master["name"],
                "Disk Pool Name":a.get("name"),
                "Usable (TB)":b2tb(usable),
                "Available (TB)":b2tb(avail),
                "Used (TB)":b2tb(used),
                "Usage (%)":pct
            })
        if len(data)<LIMIT: break
        offset+=LIMIT
    return out



def export_excel(rows):
    from collections import defaultdict
    from openpyxl.styles import Alignment
    wb=Workbook()
    ws=wb.active
    ws.title="Capacity Report"
    headers=["Site","Master","Disk Pool Name","Usable (TB)","Available (TB)","Used (TB)","Usage (%)"]
    for i,h in enumerate(headers,1):
        c=ws.cell(row=1,column=i,value=h)
        c.font=Font(bold=True)
        c.fill=PatternFill("solid",start_color="4F81BD")
    for r in rows:
        ws.append([r[h] for h in headers])
    ws.freeze_panes="A2"
    ws.auto_filter.ref=ws.dimensions

    sw=wb.create_sheet("Summary Capacity")
    now=datetime.now()
    hm=now.hour*100+now.minute
    if 800<=hm<=1500: shift=1
    elif 1501<=hm<=2300: shift=2
    else: shift=3
    title=f"Shift {shift} {now.strftime('%d %B %Y')}"
    sw.merge_cells("A1:E1")
    c=sw["A1"]; c.value=title; c.font=Font(bold=True,size=14); c.alignment=Alignment(horizontal="center")
    hdr=["Site","Total Capacity (TB)","Used Capacity (TB)","Free Capacity (TB)","Used Percentage (%)"]
    for i,h in enumerate(hdr,1):
        cc=sw.cell(row=2,column=i,value=h)
        cc.font=Font(bold=True)
        cc.fill=PatternFill("solid",start_color="4F81BD")
    grp=defaultdict(lambda:[0,0,0])
    for r in rows:
        grp[r["Site"]][0]+=r["Usable (TB)"]
        grp[r["Site"]][1]+=r["Used (TB)"]
        grp[r["Site"]][2]+=r["Available (TB)"]
    row=3
    for s in sorted(grp):
        total,used,free=grp[s]
        pct=round((used/total)*100,2) if total else 0
        sw.append([s,round(total,2),round(used,2),round(free,2),pct])
    out=os.path.join(REPORT_DIR,"capacity_report.xlsx")
    wb.save(out)
    print(out)

def main():
    with open(HEART,"a") as f: f.write(str(datetime.now())+"\n")
    allrows=[]
    try:
        for m in MASTERS.values():
            allrows.extend(fetch_master(m))
        allrows=sorted(allrows,key=lambda x:(x["Master"],x["Disk Pool Name"]))
        with open(os.path.join(CACHE_DIR,"capacity_cache.json"),"w") as f:
            json.dump(allrows,f,indent=2)
        export_excel(allrows)
        with open(LOG_FILE,"a") as f:f.write(f"{datetime.now()} SUCCESS\n")
    except Exception:
        with open(LOG_FILE,"a") as f:f.write(traceback.format_exc())

if __name__=="__main__":
    main()
