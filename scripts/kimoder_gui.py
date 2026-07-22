"""
KimoDer GUI - DearPyGui control panel for Kimodo+Cascadeur backend.
Start/Stop buttons, status indicators, all logs printed to the
console window with [backend]/[demo] tags (EveryNyan pattern).
Launched by Run_KimoDer.ps1 via kimodo_env python.exe.
Version: 2.0.0
Author:  Soror L.'. L.'.
"""

import os, queue, subprocess, sys, textwrap, threading, time, webbrowser
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent; sys.path.insert(0, str(SCRIPT_DIR))
import backend_ctl as bc
import dearpygui.dearpygui as dpg
SC="status_circle"; ST="status_text"; DC="demo_circle"; DST="demo_text"; IT="backend_info"; VT="vram_text"; RT="ram_text"; DT="demo_status"; LG="log_area"; LK="cascadeur_link"
_q=queue.Queue(); _sd=threading.Event()
_st={"ok":False,"warming_up":False,"busy":False,"warmup_error":"","device":"-","text_encoder_profile":"-","loaded_datasets":[],"clients":{}}
_ds={"running":False,"pid":0,"port":0,"ready":False}; _owned=False; _logbuf=[]; LB=8000
def ct(t,g):
    u=g.upper(); sym=" "
    if "ERROR" in u or "TRACEBACK" in u or "FAIL" in u: sym="!"
    elif "WARN" in u: sym="*"
    elif "READY" in u or "loaded" in g or "OK" in g[:4]: sym="+"
    elif ">>>" in g[:4]: sym=">"
    elif "STATUS" in u[:10]: sym="."
    line=f"[{t.center(19)}] {sym} {g}"
    print(line,flush=True)
    _q.put(("log",line))
def sc(): return ((230,70,70),"ERROR") if _st["warmup_error"] else ((110,110,110),"DOWN") if not _st["ok"] else ((240,200,60),"WARMING") if _st["warming_up"] else ((90,160,250),"BUSY") if _st["busy"] else ((80,210,100),"READY")
def ap():
    c,l=sc()
    if dpg.does_item_exist(SC): dpg.configure_item(SC,fill=c)
    if dpg.does_item_exist(ST): dpg.set_value(ST,l); dpg.configure_item(ST,color=c)
    if dpg.does_item_exist(IT): dpg.set_value(IT,f"device: {_st['device']}   encoder: {_st['text_encoder_profile']}   datasets: {', '.join(_st['loaded_datasets']) or '-'}")
    r=_st["ok"] or _st["warming_up"]
    for t in ("btn_start_nf4","btn_start_off"):
        if dpg.does_item_exist(t): dpg.configure_item(t,enabled=not r)
    if dpg.does_item_exist("btn_stop"): dpg.configure_item("btn_stop",enabled=r)
    if dpg.does_item_exist(DC):
        if not _ds["running"]: dc,dl=(110,110,110),"STOPPED"
        elif _ds.get("ready"): dc,dl=(80,210,100),"READY"
        elif _ds["running"]: dc,dl=(240,200,60),"LOADING"
        else: dc,dl=(110,110,110),"STOPPED"
        dpg.configure_item(DC,fill=dc)
        if dpg.does_item_exist(DST): dpg.set_value(DST,dl); dpg.configure_item(DST,color=dc)
    if dpg.does_item_exist(DT):
        if _ds["running"]: dpg.set_value(DT,f"port :{_ds['port']}  pid {_ds['pid']}")
        else: dpg.set_value(DT,"")
    if dpg.does_item_exist(LK):
        import time as _t
        cl=_st.get("clients",{})
        ts=cl.get("cascadeur")
        if ts and (_t.time()-ts)<20:
            ago=int(_t.time()-ts)
            dpg.set_value(LK,f"link: cascadeur ({ago}s ago)")
            dpg.configure_item(LK,color=(80,210,100))
        else:
            dpg.set_value(LK,"link: offline")
            dpg.configure_item(LK,color=(110,110,110))
    if dpg.does_item_exist("btn_demo_stop"): dpg.configure_item("btn_demo_stop",enabled=_ds["running"])
_wrap_cache={"chars":0}
def _render_log(force=False):
    if not dpg.does_item_exist(LG): return
    try: w=dpg.get_item_rect_size(LG)[0]
    except Exception: return
    chars=max(40,int((w-40)/7))
    if not force and chars==_wrap_cache["chars"]: return
    _wrap_cache["chars"]=chars
    out=[]
    for line in _logbuf:
        out.extend(textwrap.wrap(line,width=chars,replace_whitespace=False,drop_whitespace=False) or [""])
    if len(out)>800: out=out[-800:]
    dpg.set_value(LG,"\n".join(out))
def dq():
    for _ in range(200):
        try: k,p=_q.get_nowait()
        except: break
        if k=="state": _st.update(p); ap()
        elif k=="demo_state": _ds.update(p); ap()
        elif k=="vram" and dpg.does_item_exist(VT): dpg.set_value(VT,p)
        elif k=="ram" and dpg.does_item_exist(RT): dpg.set_value(RT,p)
        elif k=="log":
            _logbuf.append(p)
            if len(_logbuf)>400: del _logbuf[:200]
            _render_log(force=True)
def tf(fn,tg):
    off=0; first=True
    while not _sd.is_set():
        try:
            lp=fn()
            if lp.is_file():
                sz=lp.stat().st_size
                if first: off=sz; first=False
                if sz<off: off=sz
                if sz>off:
                    with open(lp,"r",encoding="utf-8",errors="replace") as f: f.seek(off); ck=f.read()
                    off=lp.stat().st_size
                    for ln in ck.splitlines():
                        ln=ln.strip('\x00').rstrip()
                        if ln: ct(tg,ln)
        except: pass
        _sd.wait(0.5)
def hw():
    was=False; fails=0
    while not _sd.is_set():
        s=bc.health()
        if s and s.get("ok"):
            was=True
            if fails>=3: ct("GUI","+ backend reachable")
            fails=0; _q.put(("state",{"ok":True,"warming_up":bool(s.get("warming_up")),"busy":bool(s.get("busy")),"warmup_error":s.get("warmup_error") or "","device":s.get("device") or "-","text_encoder_profile":s.get("text_encoder_profile") or "-","loaded_datasets":s.get("loaded_datasets") or [],"clients":s.get("clients") or {}}))
        else:
            fails+=1
            if was and fails==3: ct("GUI","* backend unreachable"); was=False
            if fails>=3: _q.put(("state",{"ok":False,"warming_up":False,"busy":False,"warmup_error":"","device":"-","text_encoder_profile":"-","loaded_datasets":[],"clients":{}}))
        a,p,pt=bc.demo_status()
        dr=False
        if a and pt:
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{pt}",timeout=2)
                dr=True
            except: pass
        _q.put(("demo_state",{"running":a,"pid":p,"port":pt,"ready":dr}))
        _sd.wait(2.0)
def mw():
    while not _sd.is_set():
        try:
            o=subprocess.run(["nvidia-smi","--query-gpu=memory.used,memory.total,utilization.gpu","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=5,creationflags=bc.hidden_flags())
            if o.returncode==0 and o.stdout.strip():
                u,t,ut=[x.strip() for x in o.stdout.strip().split(",")[0:3]]
                _q.put(("vram",f"VRAM {u}/{t} MiB   GPU {ut}%"))
        except: pass
        try:
            import psutil; vm=psutil.virtual_memory()
            _q.put(("ram",f"RAM {vm.used/(1024**3):.1f}/{vm.total/(1024**3):.1f} GB ({vm.percent}%)"))
        except: pass
        _sd.wait(3.0)
def sb(p):
    def w():
        lab="LLAMA NF4" if p=="llama" else "LLAMA OFF"
        ct("GUI",f">>> starting backend ({lab}) ...")
        rc=bc.start(profile=p,status_cb=lambda m:ct("GUI",f"STATUS: {m}"))
        ct("GUI",">>> backend is ready." if rc==0 else ">>> backend failed to start.")
    threading.Thread(target=w,daemon=True).start()
def stb():
    def w():
        ct("GUI",">>> stopping backend ...")
        bc.stop(status_cb=lambda m:ct("GUI",f"STATUS: {m}"))
        ct("GUI",">>> backend stopped.")
    threading.Thread(target=w,daemon=True).start()
def sdm():
    def w():
        global _owned
        a,pid,port=bc.demo_status()
        if a: ct("GUI",f">>> demo already running on :{port}, opening browser."); webbrowser.open(f"http://127.0.0.1:{port}"); return
        ct("GUI",">>> starting demo (model load takes 1-2 min) ...")
        pid,port=bc.start_demo(status_cb=lambda m:ct("GUI",f"STATUS: {m}"))
        if not pid: ct("GUI",">>> demo failed to start."); return
        _owned=True; url=f"http://127.0.0.1:{port}"
        import urllib.request; dl=time.time()+240
        while time.time()<dl:
            try:
                with urllib.request.urlopen(url,timeout=2) as r:
                    if r.status==200: break
            except: pass
            time.sleep(2)
        else: ct("GUI",f">>> demo did not respond on {url} within 240s."); return
        ct("GUI",f">>> demo ready at {url}"); webbrowser.open(url)
    threading.Thread(target=w,daemon=True).start()
def spd():
    def w():
        global _owned
        ct("GUI",">>> stopping demo ...")
        bc.stop_demo(status_cb=lambda m:ct("GUI",f"STATUS: {m}"))
        _owned=False; ct("GUI",">>> demo stopped.")
    threading.Thread(target=w,daemon=True).start()
def olf():
    try: os.startfile(str(bc.runtime_dir()))
    except: pass
def bg():
    dpg.create_context()
    with dpg.theme() as gt:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,(25,25,35))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,(20,22,26))
            dpg.add_theme_color(dpg.mvThemeCol_Button,(45,55,70))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,(65,80,100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,(85,100,120))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,(40,42,50))
            dpg.add_theme_color(dpg.mvThemeCol_Text,(220,220,220))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,6)
    dpg.bind_theme(gt)
    with dpg.window(tag="main_window",label="KimoDer Control",autosize=True,no_resize=False,no_collapse=True):
        with dpg.group(horizontal=True):
            dpg.add_text("KimoDer v2.3.0",color=(255,200,100))
            dpg.add_text("  |  by Soror L.'. L.'.",color=(140,145,155))
            dpg.add_text("    ")
            dpg.add_text("VRAM -",tag=VT,color=(180,185,195))
            dpg.add_text("RAM -",tag=RT,color=(180,185,195))
        dpg.add_separator()

        # ---- Cascadeur Backend ----
        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            with dpg.drawlist(width=20,height=20):
                dpg.draw_circle(center=(10,10),radius=7,tag=SC,fill=(110,110,110))
            dpg.add_text("Cascadeur Backend  (port 9552)",color=(255,200,100))
            dpg.add_text("  ")
            dpg.add_text("DOWN",tag=ST,color=(110,110,110))
        dpg.add_text("device: -",tag=IT,color=(160,165,175),indent=24)
        dpg.add_spacer(height=2)
        with dpg.group(indent=24):
            dpg.add_button(label="Start (LLAMA NF4)",tag="btn_start_nf4",callback=lambda:sb("llama"))
            dpg.add_button(label="Start (LLAMA OFF)",tag="btn_start_off",callback=lambda:sb("fallback"))
            dpg.add_button(label="Stop Backend",tag="btn_stop",callback=stb)
            dpg.add_text("link: offline",tag=LK,color=(110,110,110))
        dpg.add_separator()

        # ---- Kimodo Viser ----
        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            with dpg.drawlist(width=20,height=20):
                dpg.draw_circle(center=(10,10),radius=7,tag=DC,fill=(110,110,110))
            dpg.add_text("Kimodo Viser",color=(255,200,100))
            dpg.add_text("  ")
            dpg.add_text("STOPPED",tag=DST,color=(110,110,110))
        with dpg.group(indent=24):
            dpg.add_text("",tag=DT,color=(160,165,175))
        with dpg.group(indent=24):
            dpg.add_button(label="Start Viser",tag="btn_demo_start",callback=sdm)
            dpg.add_button(label="Stop Viser",tag="btn_demo_stop",callback=spd)
            dpg.add_button(label="Log Folder",callback=olf)
        dpg.add_separator()

        # ---- Log ----
        dpg.add_input_text(tag=LG,multiline=True,readonly=True,width=-1,height=220,tracked=True)
    dpg.create_viewport(title="KimoDer -- Kimodo+Cascadeur Control",width=700,height=640)
    dpg.setup_dearpygui(); dpg.show_viewport(); dpg.set_primary_window("main_window",True)
def co():
    global _owned; _sd.set()
    if _owned:
        try: bc.stop_demo(status_cb=lambda m:None)
        except: pass
def main():
    if not bc.is_installed(): print("[GUI] Environment not installed."); return 1
    ct("GUI","KimoDer GUI starting...")
    ct("GUI",f"Repo root: {bc.repo_root()}")
    for p in (bc.log_path(), bc.demo_log_path()):
        try: p.write_text("",encoding="utf-8")
        except: pass
    bg()
    for w in [threading.Thread(target=tf,args=(bc.log_path,"Cascadeur BackEnd"),daemon=True),
              threading.Thread(target=tf,args=(bc.demo_log_path,"Kimodo Viser"),daemon=True),
              threading.Thread(target=hw,daemon=True),
              threading.Thread(target=mw,daemon=True)]: w.start()
    try:
        while dpg.is_dearpygui_running(): dq(); _render_log(); dpg.render_dearpygui_frame()
    finally: co(); dpg.destroy_context()
    return 0
if __name__=="__main__": sys.exit(main())
