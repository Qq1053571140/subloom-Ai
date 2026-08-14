(() => {
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let mode='hard', file=null, poll=null;
const fileInput=$('#file'), drop=$('#drop'), videoBox=$('#videoBox'), preview=$('#preview');

function toast(t){const x=$('#toast');x.textContent=t;x.classList.add('show');setTimeout(()=>x.classList.remove('show'),1800)}
function setMode(m){
 mode=m; $$('.mode').forEach(x=>x.classList.toggle('active',x.dataset.mode===m));
 $$('.mode-hard').forEach(x=>x.style.display=m==='hard'?'block':'none');
 $$('.mode-dub').forEach(x=>x.style.display=m==='dub'?'block':'none');
 $('#process').textContent=m==='hard'?'识别硬字幕并翻译':m==='speech'?'识别语音并生成字幕':'翻译字幕并生成配音';
}
$$('.mode').forEach(x=>x.onclick=()=>setMode(x.dataset.mode));
function loadFile(f){
 if(!f)return;
 if(!f.type.startsWith('video/') && !/\.(mp4|mov|m4v|webm)$/i.test(f.name)){toast('请选择视频文件');return}
 file=f;preview.src=URL.createObjectURL(f);drop.style.display='none';videoBox.style.display='block';$('#result').style.display='none';$('#status').textContent=`已选择：${f.name}`;
}
fileInput.onchange=e=>loadFile(e.target.files[0]);
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
drop.addEventListener('drop',e=>loadFile(e.dataTransfer.files[0]));
$('#reset').onclick=()=>{file=null;fileInput.value='';preview.removeAttribute('src');preview.load();drop.style.display='grid';videoBox.style.display='none';$('#bar').style.width='0';$('#status').textContent='准备就绪';if(poll)clearInterval(poll)};

async function pollJob(id){
 if(poll)clearInterval(poll);
 poll=setInterval(async()=>{
  try{
   const r=await fetch('/api/jobs/'+id);const j=await r.json();
   $('#status').textContent=j.message||j.status;$('#bar').style.width=(j.progress||0)+'%';
   if(j.status==='done'){
    clearInterval(poll);poll=null;$('#process').disabled=false;
    $('#result').style.display='block';
    $('#download').href=j.video_url;$('#downloadSrt').href=j.srt_url||'#';
    $('#downloadSrt').style.display=j.srt_url?'inline-block':'none';
    $('#resultNote').textContent=j.message||'处理完成';toast('处理完成');
   }else if(j.status==='error'){
    clearInterval(poll);poll=null;$('#process').disabled=false;toast('处理失败');$('#status').textContent='失败：'+(j.error||j.message||'未知错误');
   }
  }catch(e){}
 },1400)
}
$('#process').onclick=async()=>{
 if(!file){toast('请先上传视频');return}
 const fd=new FormData();fd.append('file',file);fd.append('mode',mode);fd.append('source_lang',$('#sourceLang').value);fd.append('target_lang',$('#targetLang').value);
 fd.append('overlay_mode',$('#overlayMode').value);fd.append('crop',$('#crop').value);fd.append('voice',$('#voice').value);fd.append('keep_bg',$('#keepBg').value);
 $('#process').disabled=true;$('#result').style.display='none';$('#bar').style.width='5%';$('#status').textContent='正在上传…';
 try{
  const r=await fetch('/api/process',{method:'POST',body:fd});const j=await r.json();
  if(!r.ok)throw new Error(j.detail||'上传失败');
  $('#status').textContent='任务已创建';pollJob(j.job_id);
 }catch(e){$('#process').disabled=false;$('#status').textContent='失败：'+e.message;toast('无法创建任务')}
};
setMode('hard');
})();