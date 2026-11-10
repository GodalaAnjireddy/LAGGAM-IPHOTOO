import os, json, uuid, shutil, io, threading, time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv("PHOTOO_DATA","./data")).resolve()
DATA.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="LAGGAM IPHOTOO")
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")

def event_dir(eid):
    p=DATA/eid
    if not p.is_dir(): raise HTTPException(404,"Event not found")
    return p
def read_event(eid):
    p=event_dir(eid)
    return json.loads((p/"event.json").read_text()),p

@app.get("/",response_class=HTMLResponse)
def home():
    return (ROOT/"static"/"index.html").read_text()

@app.post("/api/events")
def create_event(name:str=Form(...),date:str=Form(""),venue:str=Form("")):
    eid=uuid.uuid4().hex[:8].upper()
    p=DATA/eid; (p/"photos").mkdir(parents=True); (p/"faces").mkdir()
    ev={"id":eid,"name":name.strip(),"date":date,"venue":venue}
    (p/"event.json").write_text(json.dumps(ev),encoding="utf-8")
    return {"event":ev,"guest_url":f"/event/{eid}","admin_url":f"/admin/{eid}"}

@app.get("/event/{eid}",response_class=HTMLResponse)
def guest(eid):
    ev,_=read_event(eid)
    page=(ROOT/"static"/"guest.html").read_text()
    return page.replace("__EVENT__",json.dumps(ev).replace("</","<\\/")).replace("__ID__",eid)

@app.get("/admin/{eid}",response_class=HTMLResponse)
def admin(eid):
    ev,_=read_event(eid)
    page=(ROOT/"static"/"admin.html").read_text()
    return page.replace("__EVENT__",json.dumps(ev).replace("</","<\\/")).replace("__ID__",eid)

@app.get("/api/events/{eid}/qr")
def qr(eid):
    import qrcode
    # QR URL uses public origin configured at deploy time
    origin=os.getenv("PUBLIC_BASE_URL","").rstrip("/")
    if not origin: raise HTTPException(400,"Set PUBLIC_BASE_URL to deployed website URL")
    img=qrcode.make(origin+f"/event/{eid}")
    b=io.BytesIO(); img.save(b,format="PNG"); b.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(b,media_type="image/png")

@app.post("/api/events/{eid}/upload")
async def upload(eid,file:UploadFile=File(...)):
    _,p=read_event(eid); content=await file.read()
    if len(content)>25*1024*1024: raise HTTPException(413,"Image max 25 MB")
    try: Image.open(io.BytesIO(content)).verify()
    except Exception: raise HTTPException(400,"Invalid image")
    ext=Path(file.filename or "photo.jpg").suffix.lower()
    if ext not in [".jpg",".jpeg",".png",".webp"]: ext=".jpg"
    name=uuid.uuid4().hex+ext
    (p/"photos"/name).write_bytes(content)
    return {"ok":True,"name":name}

@app.get("/api/events/{eid}/photos")
def list_photos(eid):
    _,p=read_event(eid)
    return [{"name":f.name,"url":f"/api/events/{eid}/photos/{f.name}"} for f in sorted((p/"photos").iterdir()) if f.is_file()]

@app.get("/api/events/{eid}/photos/{name}")
def get_photo(eid,name):
    _,p=read_event(eid); f=p/"photos"/Path(name).name
    if not f.is_file(): raise HTTPException(404)
    return FileResponse(f,filename=f.name)

@app.post("/api/events/{eid}/face-search")
async def face_search(eid,selfie:UploadFile=File(...)):
    _,p=read_event(eid)
    raw=await selfie.read()
    try: img=Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception: raise HTTPException(400,"Invalid selfie")
    try:
        import numpy as np
        from insightface.app import FaceAnalysis
        model=FaceAnalysis(name="buffalo_l",providers=["CPUExecutionProvider"])
        model.prepare(ctx_id=-1,det_size=(640,640))
        query_faces=model.get(np.asarray(img)[:,:,::-1])
        if not query_faces: return {"matches":[],"message":"No face found. Take a clear front-facing selfie."}
        q=query_faces[0].embedding
        matches=[]
        for f in (p/"photos").iterdir():
            try:
                arr=np.asarray(Image.open(f).convert("RGB"))[:,:,::-1]
                for face in model.get(arr):
                    score=float(np.dot(q,face.embedding)/(np.linalg.norm(q)*np.linalg.norm(face.embedding)+1e-9))
                    if score>=float(os.getenv("FACE_THRESHOLD","0.38")):
                        matches.append({"name":f.name,"url":f"/api/events/{eid}/photos/{f.name}","score":round(score,3)})
            except Exception: continue
        matches=sorted({x["name"]:x for x in matches}.values(),key=lambda x:x["score"],reverse=True)
        return {"matches":matches[:100],"message":f"{len(matches)} matching photos"}
    except ImportError:
        raise HTTPException(503,"Face AI unavailable. Install optional insightface + onnxruntime.")

@app.post("/api/events/{eid}/sync-folder")
def sync_folder(eid,folder:str=Form(...)):
    # Use only on Windows/local photographer laptop. Cloud cannot read laptop paths.
    source=Path(folder)
    if not source.is_dir(): raise HTTPException(400,"Folder does not exist")
    _,p=read_event(eid); dest=p/"photos"; count=0
    for f in source.iterdir():
        if f.suffix.lower() in [".jpg",".jpeg",".png",".webp"] and f.is_file():
            target=dest/f.name
            if not target.exists():
                try: shutil.copy2(f,target); count+=1
                except Exception: pass
    return {"copied":count}
