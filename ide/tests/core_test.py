import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.environ.setdefault("DISPLAY", ":99")
import time
import traceback
import tkinter.messagebox as MB
MB.showerror=lambda *a,**k: None; MB.showinfo=lambda *a,**k: None
MB.askyesnocancel=lambda *a,**k: False; MB.askokcancel=lambda *a,**k: True
import ide as V
V.messagebox=MB
V.IDEApp.open_url=lambda self,u: None
import tkinter.font as tkfont
from _fixtures import make_code_workspace
W = make_code_workspace(tempfile.mkdtemp(prefix="idecore"))
P=[];F=[]
def chk(n,c,d=""):
    (P if c else F).append(f"{n} {d}")
    print(("  OK   " if c else "  FAIL ")+n+"  "+str(d),flush=True)
app=V.IDEApp(W)
def term(): return app.panel.term.get("1.0","end")
def main():
  t=lambda: app.editor.text   # re-fetch: set_theme rebuilds the tree
  # ---- files ----
  app.open_file(f"{W}/src/main.py"); app.update(); app.editor.highlight(); app.update()
  chk("open + highlight py", len(t().tag_ranges("keyword"))>0)
  app.open_file(f"{W}/unicode.py"); app.update()
  chk("unicode", "日本語" in t().get("1.0","end"))
  app.open_file(f"{W}/blob.bin"); app.update()
  chk("binary guard", "binary" in t().get("1.0","end").lower())
  t0=time.time(); app.open_file(f"{W}/big.py"); app.update_idletasks()
  app.editor.highlight(); app.update()
  chk("8000-line file fast", time.time()-t0<2.0, f"{time.time()-t0:.2f}s")
  app.open_file(f"{W}/missing_zz.py"); app.update(); chk("missing file safe", True)
  # ---- edit/save ----
  app.open_file(f"{W}/notes.txt"); app.update()
  t().insert("1.0","EDITED "); app.update(); time.sleep(.3); app.update()
  chk("dirty flag", app.current_buffer().get("modified") is True)
  app.save_file(); chk("save to disk", open(f"{W}/notes.txt").read().startswith("EDITED"))
  # ---- tabs ----
  n=len(app.buffers); app.new_file(); app.update()
  chk("new tab", len(app.buffers)==n+1)
  app.close_current_tab(); app.update(); chk("close tab", len(app.buffers)==n)
  # ---- find/replace ----
  open(f"{W}/rep.txt","w").write("alpha beta alpha\n")
  app.open_file(f"{W}/rep.txt"); app.update()
  app.show_find(True); e=app.editor
  e.fe.delete(0,"end"); e.fe.insert(0,"alpha"); e.do_find(); app.update()
  chk("find", len(e._matches)==2, len(e._matches))
  e.re.delete(0,"end"); e.re.insert(0,"Z"); e.replace_all(); app.update()
  chk("replace all", t().get("1.0","end-1c").startswith("Z beta Z"), repr(t().get("1.0","end-1c"))); e.hide_find()
  # ---- workspace search ----
  app.show_sidebar_mode("search"); app.update()
  app.sidebar.s_query.delete(0,"end"); app.sidebar.s_query.insert(0,"searchable_token")
  app.sidebar._run_search(); app.update()
  chk("workspace search", len(app.sidebar._search_hits)>=1, len(app.sidebar._search_hits))
  app.show_sidebar_mode("explorer"); app.update()
  # ---- nav ----
  app.open_file(f"{W}/big.py"); app.update(); app.goto_line(2000); app.update()
  chk("goto line", t().index("insert").startswith("2000"))
  app._index_workspace(); chk("index workspace", len(app.workspace_files)>=6)
  app.open_file(f"{W}/src/main.py"); app.update()
  t().mark_set("insert","end-1c"); t().insert("insert","\nVect"); app.autocomplete(trigger=True); app.update()
  chk("autocomplete", app.completion_active); app.completion_hide()
  t().delete("insert linestart","insert lineend")
  # ---- view ----
  app.zoom(2); app.reset_zoom(); chk("zoom reset 75%", app.status.zoom.cget("text")=="75%")
  for th in ("black","white","grey"): app.set_theme(th); app.update()
  chk("themes", app.theme_name=="grey")
  app.toggle_minimap(); app.toggle_minimap(); chk("minimap", app.editor.minimap_visible)
  app.toggle_sidebar(); app.toggle_sidebar(); chk("sidebar toggle", app.sidebar_visible)
  # ---- save all / watcher ----
  open(f"{W}/ext.py","w").write("original = 1\n")
  app.open_file(f"{W}/ext.py"); app.update()
  open(f"{W}/ext.py","w").write("changed_outside = 9\n"); os.utime(f"{W}/ext.py",None)
  for _ in range(40):
      app.update(); time.sleep(.1)
      if "changed_outside" in t().get("1.0","end"): break
  chk("external reload", "changed_outside" in t().get("1.0","end"))
  t().insert("1.0","LOCAL "); app.update(); time.sleep(.3); app.update()
  open(f"{W}/ext.py","w").write("third = 3\n"); os.utime(f"{W}/ext.py",None)
  for _ in range(30): app.update(); time.sleep(.1)
  chk("conflict guard keeps edits", "LOCAL" in t().get("1.0","end"))
  app.current_buffer()["modified"]=False
  chk("WM_DELETE bound", bool(app.protocol("WM_DELETE_WINDOW")))
  # ---- multi-language ----
  samples={"x.ts":"interface A { b: string }\n","x.go":'package main\nfunc f(){}\n',
           "x.rs":"fn main(){ let x=1; }\n","x.java":"public class A {}\n",
           "x.c":"int main(void){return 0;}\n","x.rb":"class A\n def b\n end\nend\n",
           "x.php":"<?php function f(){} ?>\n","x.sql":"select * from t;\n",
           "x.css":"a{color:red}\n","x.html":"<div id='a'>x</div>\n",
           "x.json":'{"a":1}\n',"x.yml":"a: 1\n","x.md":"# T\n","x.sh":"if true; then echo x; fi\n",
           "x.kt":"fun m(){}\n","x.swift":"func f(){}\n","x.cs":"class A{}\n","x.lua":"local a=1\n"}
  ok=0
  for fn,src in samples.items():
      open(f"{W}/{fn}","w").write(src)
      app.open_file(f"{W}/{fn}"); app.update(); app.editor.highlight(); app.update()
      tot=sum(len(t().tag_ranges(tg))//2 for tg in V.TAG_COLOR)
      if tot>0: ok+=1
      else: print("     no tokens:",fn)
  chk("18 languages highlight", ok==len(samples), f"{ok}/{len(samples)}")
  # ---- run ----
  app.open_file(f"{W}/src/main.py"); app.update(); app.run_file()
  for _ in range(60):
      app.update(); time.sleep(.1)
      if "|v| = 5.0" in term(): break
  chk("F5 run", "|v| = 5.0" in term())
  chk("tasks detected", len(app.all_tasks())>0)
try: main()
except Exception: traceback.print_exc(); F.append("EXCEPTION")
print(f"\n===== PASS {len(P)}   FAIL {len(F)} =====")
for f in F: print("   XX",f)
app.destroy()
shutil.rmtree(W, ignore_errors=True)
