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
MB.showerror=lambda *a,**k: None; MB.askyesno=lambda *a,**k: True
import ide as V
V.messagebox=MB
from _fixtures import make_fs_workspace
W = make_fs_workspace(tempfile.mkdtemp(prefix="idefs"))
P=[];F=[]
def chk(n,c,d=""):
    (P if c else F).append(f"{n} {d}"); print(("  OK   " if c else "  FAIL ")+n+"  "+str(d),flush=True)
app=V.IDEApp(W); fs=app.fs
def main():
    app.update()
    # ---------- OPEN EDITORS gone ----------
    names=[]
    def walk(n=""):
        for k in app.sidebar.tree.get_children(n):
            names.append(app.sidebar.tree.item(k,"text").strip()); walk(k)
    walk()
    chk("OPEN EDITORS removed", not any("OPEN EDITORS" in x for x in names), names[:4])
    chk("tree still lists files", any("b.txt" in x for x in names))
    # ---------- create ----------
    fs.create_file("new1.py","x=1\n"); app.update()
    chk("create_file", os.path.isfile(f"{W}/new1.py"))
    fs.create_folder("pkg/sub"); app.update()
    chk("create_folder nested", os.path.isdir(f"{W}/pkg/sub"))
    fs.create_file("pkg/sub/deep.txt","d"); app.update()
    chk("create in subfolder", os.path.isfile(f"{W}/pkg/sub/deep.txt"))
    try:
        fs.create_file("new1.py"); chk("duplicate name rejected", False)
    except FileExistsError: chk("duplicate name rejected", True)
    # ---------- read / write ----------
    fs.write("new1.py","y=2\n"); chk("write+read", fs.read("new1.py")=="y=2\n")
    chk("list", "b.txt" in fs.list("."))
    chk("tree listing", any(p.endswith("deep.txt") for p in fs.tree()))
    # ---------- rename with an open buffer ----------
    app.open_file(f"{W}/b.txt"); app.update()
    fs.rename("b.txt","renamed.txt"); app.update(); time.sleep(.3); app.update()
    chk("rename on disk", os.path.isfile(f"{W}/renamed.txt") and not os.path.exists(f"{W}/b.txt"))
    chk("open buffer retargeted", any(( b.get("path") or "").endswith("renamed.txt") for b in app.buffers),
        [os.path.basename(b.get("path") or "") for b in app.buffers])
    chk("tab label updated", any(b["name"]=="renamed.txt" for b in app.buffers))
    # ---------- rename a folder containing an open file ----------
    app.open_file(f"{W}/src/a.py"); app.update()
    fs.rename("src","source"); app.update(); time.sleep(.3); app.update()
    chk("folder rename", os.path.isdir(f"{W}/source"))
    chk("nested buffer retargeted",
        any(os.path.normcase(b.get("path") or "").endswith(
            os.path.normcase(os.path.join("source", "a.py")))
            for b in app.buffers),
        [b.get("path") for b in app.buffers if b.get("path")])
    # ---------- copy / duplicate / move ----------
    fs.copy("new1.py", dst_dir="pkg"); app.update()
    chk("copy into folder", os.path.isfile(f"{W}/pkg/new1.py"))
    d=fs.copy("new1.py", dst_dir="."); app.update()
    chk("duplicate auto-renames", os.path.basename(d)=="new1 copy.py", os.path.basename(d))
    fs.move("new1 copy.py","pkg/sub"); app.update()
    chk("move", os.path.isfile(f"{W}/pkg/sub/new1 copy.py"))
    # ---------- delete ----------
    fs.delete("pkg/sub/new1 copy.py"); app.update()
    chk("delete file", not os.path.exists(f"{W}/pkg/sub/new1 copy.py"))
    app.open_file(f"{W}/pkg/new1.py"); app.update()
    before=len(app.buffers)
    fs.delete("pkg"); app.update(); time.sleep(.4); app.update()
    chk("delete folder recursive", not os.path.exists(f"{W}/pkg"))
    chk("buffers of deleted files closed", len(app.buffers)<before,
        f"{before} -> {len(app.buffers)}")
    # ---------- sandbox ----------
    for bad in ("../escape.txt","/etc/passwd","../../tmp/x", "src/../../out.txt"):
        try:
            fs.create_file(bad,"x"); chk(f"blocked {bad}", False)
        except PermissionError: chk(f"blocked {bad}", True)
        except Exception as e: chk(f"blocked {bad}", False, type(e).__name__)
    try:
        fs.delete("."); chk("root delete blocked", False)
    except PermissionError: chk("root delete blocked", True)
    # ---------- context menu builds ----------
    class E: x=y=10; x_root=y_root=100
    sb=app.sidebar
    kids=sb.tree.get_children(sb.root_node)
    if kids:
        bb=sb.tree.bbox(kids[0])
        if bb:
            e=E(); e.y=bb[1]+bb[3]//2
            tgt=sb._ctx_target(e)
            chk("ctx target resolves row", tgt[0].startswith(W), os.path.basename(tgt[0]))
    # actually build and post the menu - callability proves nothing
    try:
        import tkinter as tk
        posted={}
        orig=tk.Menu.tk_popup
        def fake(self,*a,**k): posted["labels"]=[self.entrycget(i,"label")
            for i in range(self.index("end")+1)
            if self.type(i)=="command"]
        tk.Menu.tk_popup=fake
        e=E(); e.y=bb[1]+bb[3]//2
        sb._ctx_menu(e)
        tk.Menu.tk_popup=orig
        labs=posted.get("labels",[])
        chk("ctx menu opens", len(labs)>=10, f"{len(labs)} items")
        need=["New File…","New Folder…","Rename…","Delete","Copy Path",
              "Copy Relative Path","Paste","Open in Integrated Terminal",
              "Reveal in File Explorer","Find in Folder…"]
        miss=[x for x in need if x not in labs]
        chk("menu has required items", not miss, miss or labs[:3])
    except Exception as ex:
        chk("ctx menu opens", False, repr(ex)[:80])
    chk("F2/Del bound", bool(sb.tree.bind("<F2>")) and bool(sb.tree.bind("<Delete>")))
    chk("right-click bound", bool(sb.tree.bind("<Button-3>")))
    # ---------- helpers ----------
    app.copy_path(os.path.join(W, "renamed.txt"), True)
    chk("copy relative path", app.clipboard_get()=="renamed.txt", app.clipboard_get())
    app.copy_path(os.path.join(W, "renamed.txt"), False)
    chk("copy absolute path",
        os.path.normcase(app.clipboard_get())
        == os.path.normcase(os.path.abspath(os.path.join(W, "renamed.txt"))),
        app.clipboard_get())
    app.open_in_terminal(f"{W}/source"); app.update()
    chk("open in terminal sets cwd", app.term_cwd.endswith("source"), app.term_cwd)
    app.find_in_folder(f"{W}/source"); app.update()
    chk("find in folder sets scope", app.sidebar.search_scope.endswith("source"))
    app.show_sidebar_mode("explorer"); app.update()
    # ---------- agent-style background thread ----------
    import threading
    err={}
    def bg():
        try: fs.create_file("from_thread.py","# agent wrote this\n")
        except Exception as ex: err["e"]=ex
    t=threading.Thread(target=bg); t.start(); t.join()
    for _ in range(20): app.update(); time.sleep(.05)
    chk("agent thread write", os.path.isfile(f"{W}/from_thread.py") and not err, err)
try: main()
except Exception: traceback.print_exc(); F.append("EXCEPTION")
print(f"\n===== PASS {len(P)}   FAIL {len(F)} =====")
for f in F: print("   XX",f)
app.destroy()
shutil.rmtree(W, ignore_errors=True)
