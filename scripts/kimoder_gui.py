"""
KimoDer GUI - DearPyGui control panel for Kimodo+Cascadeur backend.
Start/Stop buttons, status indicators, all logs printed to the
console window with [backend]/[demo] tags (EveryNyan pattern).
Launched by Run_KimoDer.ps1 via kimodo_env python.exe.
Version: 2.0.0
Author:  Soror L.'. L.'.
"""

import os, queue, subprocess, sys, threading, time, webbrowser
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent; sys.path.insert(0, str(SCRIPT_DIR))
import backend_ctl as bc
import dearpygui.dearpygui as dpg
SC="status_circle"; ST="status_text"; DC="demo_circle"; DST="demo_text"
IT="backend_info"; VT="vram_text"; RT="ram_text"; DT="demo_status"; LG="log_area"
_q=queue.Queue(); _sd=threading.Event()
_st={"ok":False,"warming_up":False,"busy":False,"warmup_error":"","device":"-","text_encoder_profile":"-","loaded_datasets":[]}
_ds={"running":False,"pid":0,"port":0,"ready":False}; _owned=False; _log=[]; ML=2000
def ct(t,g,color=None):
    print(f"[{t}] {g}",flush=True)
    _q.put(("log", f"[{t}] {g}", color or _cl(g)))
def _cl(ln):
    u=ln.upper()
    if "TRACEBACK" in u or "ERROR" in u or "EXCEPTION" in u: return (235,110,110)
    if "WARN" in u: return (230,200,90)
    if "STATUS:" in u: return (120,220,250)
    if "ready" in ln.lower(): return (130,230,140)
    return (185,185,185)
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
        if _ds["running"]: dpg.set_value(DT,f"  port :{_ds['port']} (pid {_ds['pid']})")
        else: dpg.set_value(DT,"")
    if dpg.does_item_exist("btn_demo_stop"): dpg.configure_item("btn_demo_stop",enabled=_ds["running"])
def dq():
    for _ in range(200):
        try: k,p,*a=_q.get_nowait()
        except: break
        if k=="state": _st.update(p); ap()
        elif k=="demo_state": _ds.update(p); ap()
        elif k=="vram" and dpg.does_item_exist(VT): dpg.set_value(VT,p)
        elif k=="ram" and dpg.does_item_exist(RT): dpg.set_value(RT,p)
        elif k=="log":
            ln,clr=p,a[0] if a else _cl(p)
            if dpg.does_item_exist(LG):
                item=dpg.add_text(ln,parent=LG,color=clr,wrap=0)
                _log.append(item)
                if len(_log)>ML:
                    old=_log[:len(_log)-ML]; del _log[:len(_log)-ML]
                    for o in old:
                        if dpg.does_item_exist(o): dpg.delete_item(o)
                if dpg.get_value("autoscroll_chk"): dpg.set_y_scroll(LG,1e9)
def tf(fn,tg):
    off=0
    while not _sd.is_set():
        try:
            lp=fn()
            if lp.is_file():
                sz=lp.stat().st_size
                if sz<off: off=0
                if sz>off:
                    with open(lp,"r",encoding="utf-8",errors="replace") as f: f.seek(off); ck=f.read()
                    off=lp.stat().st_size
                    for ln in ck.splitlines():
                        ln=ln.rstrip()
                        if ln: ct(tg,ln)
        except: pass
        _sd.wait(0.5)
def hw():
    w=False
    while not _sd.is_set():
        s=bc.health()
        if s and s.get("ok"):
            w=True; _q.put(("state",{"ok":True,"warming_up":bool(s.get("warming_up")),"busy":bool(s.get("busy")),"warmup_error":s.get("warmup_error") or "","device":s.get("device") or "-","text_encoder_profile":s.get("text_encoder_profile") or "-","loaded_datasets":s.get("loaded_datasets") or []}))
        else:
            if w: ct("gui","--- backend unreachable ---"); w=False
            _q.put(("state",{"ok":False,"warming_up":False,"busy":False,"warmup_error":"","device":"-","text_encoder_profile":"-","loaded_datasets":[]}))
        a,p,pt=bc.demo_status()
        demo_ready=False
        if a and pt:
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{pt}",timeout=2)
                demo_ready=True
            except: pass
        _q.put(("demo_state",{"running":a,"pid":p,"port":pt,"ready":demo_ready}))
        _sd.wait(1.0)
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
        ct("gui",f">>> starting backend ({lab}) ...")
        rc=bc.start(profile=p,status_cb=lambda m:ct("gui",f"STATUS: {m}"))
        ct("gui",">>> backend is ready." if rc==0 else ">>> backend failed to start.")
    threading.Thread(target=w,daemon=True).start()
def stb():
    def w():
        ct("gui",">>> stopping backend ...")
        bc.stop(status_cb=lambda m:ct("gui",f"STATUS: {m}"))
        ct("gui",">>> backend stopped.")
    threading.Thread(target=w,daemon=True).start()
def sdm():
    def w():
        global _owned
        a,pid,port=bc.demo_status()
        if a: ct("gui",f">>> demo already running on :{port}, opening browser."); webbrowser.open(f"http://127.0.0.1:{port}"); return
        ct("gui",">>> starting demo (model load takes 1-2 min) ...")
        pid,port=bc.start_demo(status_cb=lambda m:ct("gui",f"STATUS: {m}"))
        if not pid: ct("gui",">>> demo failed to start."); return
        _owned=True; url=f"http://127.0.0.1:{port}"
        import urllib.request; dl=time.time()+240
        while time.time()<dl:
            try:
                with urllib.request.urlopen(url,timeout=2) as r:
                    if r.status==200: break
            except: pass
            time.sleep(2)
        else: ct("gui",f">>> demo did not respond on {url} within 240s."); return
        ct("gui",f">>> demo ready at {url}"); webbrowser.open(url)
    threading.Thread(target=w,daemon=True).start()
def spd():
    def w():
        global _owned
        ct("gui",">>> stopping demo ...")
        bc.stop_demo(status_cb=lambda m:ct("gui",f"STATUS: {m}"))
        _owned=False; ct("gui",">>> demo stopped.")
    threading.Thread(target=w,daemon=True).start()
def olf():
    try: os.startfile(str(bc.runtime_dir()))
    except: pass
def bg():
    dpg.create_context()
    with dpg.theme() as gt:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,(24,26,30))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,(20,22,26))
            dpg.add_theme_color(dpg.mvThemeCol_Button,(45,60,90))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,(60,80,120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,(75,100,150))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,(35,38,45))
            dpg.add_theme_color(dpg.mvThemeCol_Text,(215,218,224))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,5)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,8)
    dpg.bind_theme(gt)
    with dpg.window(tag="main_window",label="KimoDer Control",autosize=True,no_resize=False,no_collapse=True):
        with dpg.group(horizontal=True):
            dpg.add_text("KimoDer v2.0.0",color=(140,160,220))
            dpg.add_text("  |  by Soror L.'. L.'.",color=(110,115,125))
        dpg.add_separator()
        with dpg.group(horizontal=True):
            with dpg.drawlist(width=26,height=26):
                dpg.draw_circle(center=(13,13),radius=9,tag=SC,fill=(110,110,110),color=(0,0,0,0))
            dpg.add_text("DOWN",tag=ST,color=(110,110,110))
        dpg.add_text("device: -",tag=IT)
        dpg.add_text("VRAM -",tag=VT); dpg.add_text("RAM -",tag=RT)
        dpg.add_separator()
        dpg.add_text("Backend (port 9552):",color=(140,145,155))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Start (LLAMA NF4)",tag="btn_start_nf4",callback=lambda:sb("llama"))
            dpg.add_button(label="Start (LLAMA OFF)",tag="btn_start_off",callback=lambda:sb("fallback"))
            dpg.add_button(label="Stop Backend",tag="btn_stop",callback=stb)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            with dpg.drawlist(width=26,height=26):
                dpg.draw_circle(center=(13,13),radius=9,tag=DC,fill=(110,110,110),color=(0,0,0,0))
            dpg.add_text("STOPPED",tag=DST,color=(110,110,110))
            dpg.add_text("",tag=DT)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Start Web Demo",tag="btn_demo_start",callback=sdm)
            dpg.add_button(label="Stop Demo",tag="btn_demo_stop",callback=spd)
            dpg.add_button(label="Log Folder",callback=olf)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("Log:",color=(140,145,155))
            dpg.add_checkbox(label="Autoscroll",tag="autoscroll_chk",default_value=True)
        with dpg.child_window(tag=LG,border=True,height=280,horizontal_scrollbar=True): pass
    dpg.create_viewport(title="KimoDer -- Kimodo+Cascadeur Control",width=720,height=740)
    dpg.setup_dearpygui(); dpg.show_viewport(); dpg.set_primary_window("main_window",True)
def co():
    global _owned; _sd.set()
    if _owned:
        try: bc.stop_demo(status_cb=lambda m:None)
        except: pass
def main():
    if not bc.is_installed(): print("[gui] Environment not installed."); return 1
    print("[gui] KimoDer GUI starting...",flush=True)
    print(f"[gui] Repo root: {bc.repo_root()}",flush=True)
    print(f"[gui] Backend log: {bc.log_path()}",flush=True)
    print(f"[gui] Demo log: {bc.demo_log_path()}",flush=True)
    bg()
    for w in [threading.Thread(target=tf,args=(bc.log_path,"backend"),daemon=True),
              threading.Thread(target=tf,args=(bc.demo_log_path,"demo"),daemon=True),
              threading.Thread(target=hw,daemon=True),
              threading.Thread(target=mw,daemon=True)]: w.start()
    try:
        while dpg.is_dearpygui_running(): dq(); dpg.render_dearpygui_frame()
    finally: co(); dpg.destroy_context()
    return 0
if __name__=="__main__": sys.exit(main())
