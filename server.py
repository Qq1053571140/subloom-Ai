import os, re, json, uuid, shutil, subprocess, threading, time, math
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE=Path(__file__).resolve().parent
STATIC=BASE/"static"; WORK=BASE/"work"; WORK.mkdir(exist_ok=True)
app=FastAPI(title="SubLoom AI")
app.mount("/static",StaticFiles(directory=str(STATIC)),name="static")
app.mount("/files",StaticFiles(directory=str(WORK)),name="files")
JOBS={}

LANG_MAP={
 "zh-CN":"zh-CN","en":"en","ja":"ja","ko":"ko","fr":"fr","es":"es","de":"de","it":"it","pt":"pt","ar":"ar","ru":"ru"
}
TESS_LANG={"zh-CN":"chi_sim","en":"eng","ja":"jpn","ko":"kor","fr":"fra","es":"spa","de":"deu","it":"ita","pt":"por","ar":"ara","ru":"rus"}

def run(cmd):
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if p.returncode!=0: raise RuntimeError(p.stderr[-2400:])
 return p.stdout

def ffprobe_duration(p):
 x=run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(p)]).strip()
 return float(x)

def srt_time(sec):
 ms=max(0,int(sec*1000));h=ms//3600000;ms%=3600000;m=ms//60000;ms%=60000;s=ms//1000;ms%=1000
 return f"{h:02}:{m:02}:{s:02},{ms:03}"

def clean_ocr(s):
 s=re.sub(r"\s+","",s or "")
 s=re.sub(r"[^\u3400-\u9fffA-Za-z0-9，。！？,.!?：:；;“”\"'（）()《》【】…\-]","",s)
 return s.strip()

def similarity(a,b):
 a=set(clean_ocr(a));b=set(clean_ocr(b))
 if not a or not b:return 0
 return 2*len(a&b)/(len(a)+len(b))

def translate_text(text,target):
 if not text:return ""
 try:
  from deep_translator import GoogleTranslator
  target2={"zh-CN":"zh-CN"}.get(target,target)
  return GoogleTranslator(source="auto",target=target2).translate(text)
 except Exception:
  return text

def write_srt(items,path,key="translated"):
 with open(path,"w",encoding="utf-8") as f:
  for i,x in enumerate(items,1):
   f.write(f"{i}\n{srt_time(x['start'])} --> {srt_time(x['end'])}\n{x.get(key) or x.get('text','')}\n\n")

def extract_hardsubs(video,source_lang,crop,job):
 import cv2, pytesseract
 cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS) or 25;dur=(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)/fps
 interval=0.75;items=[];current=None;t=0
 tess=TESS_LANG.get(source_lang,"chi_sim") if source_lang!="auto" else "chi_sim+eng"
 while t<dur:
  cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
  if not ok:break
  h,w=frame.shape[:2];y=int(h*(1-float(crop)));roi=frame[y:h,0:w]
  gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY);gray=cv2.resize(gray,None,fx=1.7,fy=1.7,interpolation=cv2.INTER_CUBIC)
  txt=clean_ocr(pytesseract.image_to_string(gray,lang=tess,config="--psm 6"))
  if len(txt)>=2:
   if current and similarity(txt,current["text"])>.72: current["end"]=min(dur,t+interval)
   else:
    current={"start":t,"end":min(dur,t+interval),"text":txt};items.append(current)
  t+=interval
  JOBS[job]["progress"]=min(42,int(8+34*(t/max(dur,.1))));JOBS[job]["message"]=f"OCR 扫描 {int(t)}/{int(dur)} 秒 · {len(items)} 段"
 cap.release()
 return items

def transcribe(video,source_lang,job):
 # CPU-friendly model by default; set WHISPER_MODEL=small for higher quality
 from faster_whisper import WhisperModel
 model_name=os.getenv("WHISPER_MODEL","base")
 model=WhisperModel(model_name,device="cpu",compute_type="int8")
 lang=None if source_lang=="auto" else {"zh-CN":"zh","en":"en","ja":"ja","ko":"ko","fr":"fr","es":"es","de":"de","it":"it","pt":"pt","ar":"ar","ru":"ru"}.get(source_lang)
 segs,_=model.transcribe(str(video),language=lang,vad_filter=True)
 items=[]
 for s in segs:
  text=(s.text or "").strip()
  if text:items.append({"start":float(s.start),"end":float(s.end),"text":text})
 JOBS[job]["progress"]=45;JOBS[job]["message"]=f"语音识别完成 · {len(items)} 段"
 return items

def translate_items(items,target,job,startp=46,endp=62):
 n=max(1,len(items))
 for i,x in enumerate(items):
  x["translated"]=translate_text(x["text"],target)
  JOBS[job]["progress"]=int(startp+(endp-startp)*(i+1)/n);JOBS[job]["message"]=f"翻译 {i+1}/{len(items)}"
 return items

def font_path():
 for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
  if Path(p).exists():return p
 return None

def burn_subtitles(video,srt,out,overlay_mode,crop,job):
 # ASS via subtitle filter; cover bottom area when requested
 vf=[]
 if overlay_mode=="cover":
  # cover bottom region with dark translucent band
  y=f"ih*(1-{float(crop)})"
  h=f"ih*{float(crop)}"
  vf.append(f"drawbox=x=0:y={y}:w=iw:h={h}:color=black@0.82:t=fill")
 style="FontName=Noto Sans CJK SC,FontSize=19,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV="+("35" if overlay_mode=="cover" else "95")
 # escape path for ffmpeg subtitles
 sp=str(srt).replace("\\","/").replace(":","\\:")
 vf.append(f"subtitles='{sp}':force_style='{style}'")
 JOBS[job]["progress"]=72;JOBS[job]["message"]="正在渲染字幕"
 run(["ffmpeg","-y","-i",str(video),"-vf",",".join(vf),"-c:v","libx264","-preset","veryfast","-crf","20","-c:a","aac","-movflags","+faststart",str(out)])

def make_dub_audio(items,target,out_audio,job):
 from gtts import gTTS
 from pydub import AudioSegment
 total=max([x["end"] for x in items],default=1)
 canvas=AudioSegment.silent(duration=int(total*1000)+500)
 lang={"zh-CN":"zh-cn","en":"en","ja":"ja","ko":"ko","fr":"fr","es":"es","de":"de","it":"it","pt":"pt","ar":"ar","ru":"ru"}.get(target,"en")
 tmpdir=out_audio.parent/"tts";tmpdir.mkdir(exist_ok=True)
 n=max(1,len(items))
 for i,x in enumerate(items):
  txt=x.get("translated") or x.get("text","")
  if not txt:continue
  mp3=tmpdir/f"{i}.mp3";gTTS(txt,lang=lang).save(str(mp3))
  seg=AudioSegment.from_file(mp3)
  slot=max(350,int((x["end"]-x["start"])*1000))
  if len(seg)>slot:
   # simple speedup by frame-rate trick, capped to keep intelligible
   ratio=min(1.8,len(seg)/slot)
   seg=seg._spawn(seg.raw_data,overrides={"frame_rate":int(seg.frame_rate*ratio)}).set_frame_rate(seg.frame_rate)
  seg=seg[:slot]
  canvas=canvas.overlay(seg,position=int(x["start"]*1000))
  JOBS[job]["progress"]=int(63+17*(i+1)/n);JOBS[job]["message"]=f"生成配音 {i+1}/{len(items)}"
 canvas.export(out_audio,format="mp3")

def mux_dub(video,srt,dub,out,overlay_mode,crop,keep_bg,job):
 sp=str(srt).replace("\\","/").replace(":","\\:")
 vf=[]
 if overlay_mode=="cover":
  vf.append(f"drawbox=x=0:y=ih*(1-{float(crop)}):w=iw:h=ih*{float(crop)}:color=black@0.82:t=fill")
 style="FontName=Noto Sans CJK SC,FontSize=19,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=35"
 vf.append(f"subtitles='{sp}':force_style='{style}'")
 JOBS[job]["progress"]=84;JOBS[job]["message"]="正在合成新音轨和字幕"
 if keep_bg=="yes":
  # Lower original track heavily and mix with dub. This does not do vocal isolation; production upgrade can add Demucs.
  fc="[0:a]volume=0.18[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=longest:normalize=0[a]"
  run(["ffmpeg","-y","-i",str(video),"-i",str(dub),"-filter_complex",fc,"-map","0:v","-map","[a]","-vf",",".join(vf),"-c:v","libx264","-preset","veryfast","-crf","20","-c:a","aac","-shortest","-movflags","+faststart",str(out)])
 else:
  run(["ffmpeg","-y","-i",str(video),"-i",str(dub),"-map","0:v","-map","1:a","-vf",",".join(vf),"-c:v","libx264","-preset","veryfast","-crf","20","-c:a","aac","-shortest","-movflags","+faststart",str(out)])

def worker(job,video,mode,source_lang,target_lang,overlay_mode,crop,voice,keep_bg):
 try:
  d=WORK/job;d.mkdir(exist_ok=True)
  JOBS[job].update(status="processing",progress=6,message="开始分析视频")
  if mode=="hard": items=extract_hardsubs(video,source_lang,crop,job)
  else: items=transcribe(video,source_lang,job)
  if not items: raise RuntimeError("没有识别到可处理的字幕/语音。可尝试扩大字幕扫描区域或确认视频里有清晰语音。")
  items=translate_items(items,target_lang,job)
  srt=d/"translated.srt";write_srt(items,srt)
  out=d/"result.mp4"
  if mode=="dub":
   dub=d/"dub.mp3";make_dub_audio(items,target_lang,dub,job);mux_dub(video,srt,dub,out,"cover",crop,keep_bg,job)
  else:
   burn_subtitles(video,srt,out,overlay_mode if mode=="hard" else "above",crop,job)
  (d/"segments.json").write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding="utf-8")
  JOBS[job].update(status="done",progress=100,message="处理完成",video_url=f"/files/{job}/result.mp4",srt_url=f"/files/{job}/translated.srt")
 except Exception as e:
  JOBS[job].update(status="error",progress=100,message="处理失败",error=str(e))

@app.get("/",response_class=HTMLResponse)
def home(): return (BASE/"index.html").read_text(encoding="utf-8")

@app.post("/api/process")
async def process(file:UploadFile=File(...),mode:str=Form(...),source_lang:str=Form("auto"),target_lang:str=Form("en"),overlay_mode:str=Form("cover"),crop:str=Form("0.40"),voice:str=Form("female"),keep_bg:str=Form("yes")):
 if mode not in {"hard","speech","dub"}:raise HTTPException(400,"invalid mode")
 job=uuid.uuid4().hex[:14];d=WORK/job;d.mkdir()
 ext=Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
 inp=d/f"input{ext}"
 size=0
 with open(inp,"wb") as out:
  while True:
   chunk=await file.read(1024*1024)
   if not chunk:break
   size+=len(chunk)
   if size>350*1024*1024:raise HTTPException(413,"MVP 单文件最大 350MB")
   out.write(chunk)
 JOBS[job]={"status":"queued","progress":3,"message":"上传完成，等待处理"}
 threading.Thread(target=worker,args=(job,inp,mode,source_lang,target_lang,overlay_mode,crop,voice,keep_bg),daemon=True).start()
 return {"job_id":job}

@app.get("/api/jobs/{job}")
def get_job(job:str):
 if job not in JOBS:raise HTTPException(404,"job not found")
 return JOBS[job]

@app.get("/health")
def health():return {"ok":True}
