"""Lightweight built-in web UI for CLI mode (no Node.js required).

Serves a self-contained SPA at ``/`` that provides:
- Dashboard with course list
- Chat interface with SSE streaming
- File upload for content ingestion
- System health status
- Dark mode toggle with localStorage persistence
- Mobile-responsive sidebar

This UI is registered only when ``SERVE_BUILTIN_UI`` is not ``"false"``.
In Docker deployments the full Next.js frontend runs separately.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenTutor Zenus</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={darkMode:'class',theme:{extend:{colors:{brand:'#6366f1','brand-dark':'#818cf8'}}}}</script>
<style>
  .msg-user{background:#eef2ff;border-radius:12px 12px 2px 12px}
  .msg-bot{background:#f8fafc;border-radius:12px 12px 12px 2px}
  .dark .msg-user{background:#312e81}
  .dark .msg-bot{background:#1e293b}
  .prose pre{background:#1e293b;color:#e2e8f0;padding:12px;border-radius:8px;overflow-x:auto;font-size:13px}
  .prose code:not(pre code){background:#e2e8f0;padding:1px 5px;border-radius:4px;font-size:13px}
  .dark .prose code:not(pre code){background:#334155}
  .prose ul{list-style:disc;padding-left:1.5em}.prose ol{list-style:decimal;padding-left:1.5em}
  .prose h1,.prose h2,.prose h3{font-weight:600;margin:0.8em 0 0.3em}
  .prose h1{font-size:1.3em}.prose h2{font-size:1.15em}.prose h3{font-size:1.05em}
  .prose p{margin:0.4em 0}.prose blockquote{border-left:3px solid #6366f1;padding-left:12px;color:#64748b}
  .prose a{color:#6366f1;text-decoration:underline}
  .dark .prose a{color:#818cf8}
  .spinner{width:18px;height:18px;border:2px solid #cbd5e1;border-top-color:#6366f1;border-radius:50%;animation:spin .6s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  #chat-input:focus{outline:none;box-shadow:0 0 0 2px #6366f1}
  @media(max-width:768px){#sidebar{position:fixed;left:-100%;top:0;z-index:40;height:100%;transition:left .2s ease}
    #sidebar.open{left:0}#sidebar-overlay{display:none}#sidebar-overlay.open{display:block}}
</style>
</head>
<body class="h-full bg-gray-50 text-gray-900 dark:bg-gray-900 dark:text-gray-100 flex">

<!-- Mobile overlay -->
<div id="sidebar-overlay" class="fixed inset-0 bg-black/40 z-30 md:hidden" onclick="toggleSidebar()"></div>

<!-- Sidebar -->
<aside id="sidebar" class="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col h-full shrink-0">
  <div class="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
    <div>
      <h1 class="text-lg font-bold text-brand dark:text-brand-dark">OpenTutor <span class="text-xs font-normal text-gray-400">Zenus</span></h1>
      <p class="text-xs text-gray-400 mt-0.5" id="status-text">Connecting...</p>
    </div>
    <button onclick="toggleDark()" class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400" title="Toggle dark mode" id="dark-btn">
      <svg id="sun-icon" class="w-4 h-4 hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.66 7.66l-.71-.71M4.05 4.05l-.71-.71M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
      <svg id="moon-icon" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>
    </button>
  </div>
  <div class="p-3">
    <button onclick="showNewCourse()" class="w-full py-2 px-3 bg-brand text-white text-sm rounded-lg hover:bg-indigo-600 transition">+ New Course</button>
  </div>
  <nav id="course-list" class="flex-1 overflow-y-auto px-2 space-y-1"></nav>
  <div class="p-3 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-400">
    <a href="/docs" target="_blank" class="hover:text-brand">API Docs</a> ·
    <span id="llm-status">LLM: --</span>
  </div>
</aside>

<!-- Main -->
<main class="flex-1 flex flex-col h-full min-w-0">
  <!-- Mobile header -->
  <div class="md:hidden flex items-center gap-3 px-4 py-2 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
    <button onclick="toggleSidebar()" class="p-1">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/></svg>
    </button>
    <span class="font-semibold text-sm text-brand dark:text-brand-dark">OpenTutor</span>
  </div>

  <!-- Welcome / empty state -->
  <div id="welcome" class="flex-1 flex items-center justify-center">
    <div class="text-center max-w-md px-4">
      <div class="text-5xl mb-4">📚</div>
      <h2 class="text-xl font-semibold mb-2">Welcome to OpenTutor</h2>
      <p class="text-gray-500 dark:text-gray-400 text-sm mb-6">Create a course and upload study materials to get started. The AI tutor will generate notes, quizzes, and flashcards from your content.</p>
      <button onclick="showNewCourse()" class="py-2 px-5 bg-brand text-white rounded-lg hover:bg-indigo-600 transition text-sm">Create Your First Course</button>
    </div>
  </div>

  <!-- Chat view (hidden by default) -->
  <div id="chat-view" class="flex-1 flex flex-col h-full hidden">
    <header class="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-center justify-between">
      <div>
        <h2 id="course-title" class="font-semibold text-sm"></h2>
        <p class="text-xs text-gray-400" id="course-subtitle"></p>
      </div>
      <label class="flex items-center gap-2 text-xs text-gray-500 cursor-pointer hover:text-brand transition">
        <span>Upload</span>
        <input type="file" id="file-upload" class="hidden" accept=".pdf,.pptx,.docx,.md,.txt" onchange="uploadFile(this)">
      </label>
    </header>
    <div id="messages" class="flex-1 overflow-y-auto px-4 py-4 space-y-3"></div>
    <form onsubmit="sendMessage(event)" class="px-4 py-3 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 flex gap-2">
      <input id="chat-input" class="flex-1 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-3 py-2 text-sm" placeholder="Ask your tutor anything... (Ctrl+Enter)" autocomplete="off">
      <button type="submit" id="send-btn" class="px-4 py-2 bg-brand text-white rounded-lg text-sm hover:bg-indigo-600 transition disabled:opacity-50" disabled>Send</button>
    </form>
  </div>
</main>

<!-- New Course Modal -->
<div id="modal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 hidden">
  <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-sm mx-4">
    <h3 class="font-semibold mb-3">New Course</h3>
    <input id="course-name" class="w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-3 py-2 text-sm mb-3" placeholder="Course name (e.g., Calculus 101)">
    <div class="flex justify-end gap-2">
      <button onclick="hideModal()" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">Cancel</button>
      <button onclick="createCourse()" class="px-4 py-2 bg-brand text-white text-sm rounded-lg hover:bg-indigo-600">Create</button>
    </div>
  </div>
</div>

<script>
const API='/api';
let currentCourse=null,streaming=false;

// ── Helpers ──
function $(id){return document.getElementById(id)}
function show(id){$(id).classList.remove('hidden')}
function hide(id){$(id).classList.add('hidden')}
function safeLink(url){
  try{
    const u=new URL(url,window.location.origin);
    const protocol=(u.protocol||'').toLowerCase();
    if(protocol==='http:'||protocol==='https:'||protocol==='mailto:')return u.href;
  }catch(_e){}
  return null;
}

// ── Dark mode ──
function initDark(){
  const dark=localStorage.getItem('ot-dark')==='true';
  if(dark)document.documentElement.classList.add('dark');
  updateDarkIcons();
}
function toggleDark(){
  document.documentElement.classList.toggle('dark');
  localStorage.setItem('ot-dark',document.documentElement.classList.contains('dark'));
  updateDarkIcons();
}
function updateDarkIcons(){
  const dark=document.documentElement.classList.contains('dark');
  $('sun-icon').classList.toggle('hidden',!dark);
  $('moon-icon').classList.toggle('hidden',dark);
}
initDark();

// ── Mobile sidebar ──
function toggleSidebar(){
  $('sidebar').classList.toggle('open');
  $('sidebar-overlay').classList.toggle('open');
}

// ── Markdown renderer (no dependencies) ──
function md(text){
  if(!text)return '';
  let h=text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g,(_,lang,code)=>`<pre><code>${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\!\[([^\]]*)\]\(([^)]+)\)/g,(_,alt,url)=>{
      const src=safeLink(url);
      return src?`<img src="${src}" alt="${alt}" style="max-width:100%;border-radius:8px">`:`<span>[${alt}]</span>`;
    })
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,(_,label,url)=>{
      const href=safeLink(url);
      return href?`<a href="${href}" target="_blank" rel="noopener">${label}</a>`:`<span>${label}</span>`;
    })
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>')
    .replace(/^## (.+)$/gm,'<h2>$1</h2>')
    .replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>')
    .replace(/^[-*] (.+)$/gm,'<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm,'<li>$1</li>')
    .replace(/\n{2,}/g,'</p><p>')
    .replace(/\n/g,'<br>');
  h=h.replace(/(<li>[\s\S]*?<\/li>)/g,'<ul>$1</ul>');
  return '<p>'+h+'</p>';
}

// ── API ──
async function api(path,opts={}){
  const res=await fetch(API+path,{headers:{'Content-Type':'application/json'},...opts});
  if(!res.ok)throw new Error(`API ${res.status}`);
  return res.json();
}

// ── Health ──
async function checkHealth(){
  try{
    const h=await api('/health');
    $('status-text').textContent=h.status==='ok'?'System ready':'System: '+h.status;
    $('status-text').className='text-xs mt-0.5 '+(h.status==='ok'?'text-green-500':'text-amber-500');
    $('llm-status').textContent='LLM: '+(h.llm_available?h.llm_primary:'none');
  }catch(e){
    $('status-text').textContent='Offline';
    $('status-text').className='text-xs mt-0.5 text-red-500';
  }
}

// ── Courses ──
async function loadCourses(){
  try{
    const courses=await api('/courses/');
    const list=$('course-list');
    list.innerHTML='';
    if(courses.length===0){show('welcome');hide('chat-view');return}
    courses.forEach(c=>{
      const el=document.createElement('button');
      el.className='w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-gray-100 dark:hover:bg-gray-700 transition truncate '+(currentCourse&&currentCourse.id===c.id?'bg-indigo-50 dark:bg-indigo-900/30 text-brand dark:text-brand-dark font-medium':'text-gray-700 dark:text-gray-300');
      el.textContent=c.name||'Untitled';
      el.onclick=()=>{selectCourse(c);if(window.innerWidth<768)toggleSidebar()};
      list.appendChild(el);
    });
    if(!currentCourse&&courses.length>0)selectCourse(courses[0]);
  }catch(e){console.error('loadCourses',e)}
}

function selectCourse(c){
  currentCourse=c;
  hide('welcome');show('chat-view');
  $('course-title').textContent=c.name||'Untitled';
  $('course-subtitle').textContent=(c.content_node_count||0)+' content nodes';
  $('messages').innerHTML='';
  $('send-btn').disabled=false;
  loadCourses(); // refresh selected state
  addBotMessage('Hello! I\'m your AI tutor for **'+c.name+'**. Ask me anything about the course material, or upload a file to get started.');
}

// ── New course ──
function showNewCourse(){show('modal');$('course-name').value='';$('course-name').focus()}
function hideModal(){hide('modal')}
async function createCourse(){
  const name=$('course-name').value.trim();
  if(!name)return;
  hideModal();
  try{
    const c=await api('/courses/',{method:'POST',body:JSON.stringify({name})});
    currentCourse=c;
    await loadCourses();
    selectCourse(c);
  }catch(e){alert('Failed to create course: '+e.message)}
}

// ── Upload ──
async function uploadFile(input){
  const file=input.files[0];
  if(!file||!currentCourse)return;
  const fd=new FormData();
  fd.append('file',file);
  fd.append('course_id',currentCourse.id);
  addBotMessage('Uploading **'+file.name+'**...');
  try{
    const res=await fetch(API+'/content/upload',{method:'POST',body:fd});
    if(!res.ok){
      const payload=await res.json().catch(()=>({}));
      const detail=payload.detail||payload.message||'';
      let hint='Upload failed';
      if(res.status===401)hint='Upload failed: authentication required';
      else if(res.status===403)hint='Upload failed: permission denied';
      else if(res.status===404)hint='Upload failed: target course not found';
      else if(res.status===422)hint='Upload failed: invalid file or request parameters';
      throw new Error(hint+(detail?` (${detail})`:` (HTTP ${res.status})`));
    }
    await res.json();
    addBotMessage('Uploaded! Content is being processed. You can start chatting while it processes.');
    await loadCourses();
  }catch(e){addBotMessage('Upload error: '+e.message)}
  input.value='';
}

// ── Chat ──
function addUserMessage(text){
  const div=document.createElement('div');
  div.className='msg-user px-4 py-2.5 max-w-[80%] ml-auto text-sm';
  div.textContent=text;
  $('messages').appendChild(div);
  $('messages').scrollTop=$('messages').scrollHeight;
}

function addBotMessage(text){
  const div=document.createElement('div');
  div.className='msg-bot px-4 py-2.5 max-w-[85%] text-sm prose dark:text-gray-200';
  div.innerHTML=md(text);
  $('messages').appendChild(div);
  $('messages').scrollTop=$('messages').scrollHeight;
  return div;
}

async function sendMessage(e){
  e.preventDefault();
  const input=$('chat-input');
  const text=input.value.trim();
  if(!text||!currentCourse||streaming)return;

  addUserMessage(text);
  input.value='';
  streaming=true;
  $('send-btn').disabled=true;

  const botDiv=document.createElement('div');
  botDiv.className='msg-bot px-4 py-2.5 max-w-[85%] text-sm prose dark:text-gray-200';
  botDiv.innerHTML='<div class="spinner"></div>';
  $('messages').appendChild(botDiv);
  $('messages').scrollTop=$('messages').scrollHeight;

  let fullText='';
  try{
    const res=await fetch(API+'/chat/',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        course_id:currentCourse.id,
        message:text,
      }),
    });

    const reader=res.body.getReader();
    const decoder=new TextDecoder();
    let buffer='';

    while(true){
      const{done,value}=await reader.read();
      if(done)break;
      buffer+=decoder.decode(value,{stream:true});

      const lines=buffer.split('\n');
      buffer=lines.pop()||'';

      for(const line of lines){
        if(line.startsWith('data: ')){
          try{
            const payload=JSON.parse(line.slice(6));
            if(payload.content){
              fullText+=payload.content;
              botDiv.innerHTML=md(fullText);
              $('messages').scrollTop=$('messages').scrollHeight;
            }
            if(payload.error){
              fullText+='\n\n**Error:** '+payload.error;
              botDiv.innerHTML=md(fullText);
            }
          }catch(pe){/* non-JSON SSE line */}
        }
      }
    }
    if(!fullText)botDiv.innerHTML=md('*(No response received)*');
  }catch(err){
    botDiv.innerHTML=md('**Connection error:** '+err.message);
  }
  streaming=false;
  $('send-btn').disabled=false;
  $('chat-input').focus();
}

// ── Init ──
(async()=>{
  await checkHealth();
  await loadCourses();
  setInterval(checkHealth,30000);
  // Ctrl+Enter sends
  $('chat-input').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();$('send-btn').form.requestSubmit()}
  });
  // Enter also sends (without shift)
  $('chat-input').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey&&!e.ctrlKey&&!e.metaKey){e.preventDefault();$('send-btn').form.requestSubmit()}
  });
  // Escape closes modal
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape')hideModal();
  });
  // Enter in course name input creates course
  $('course-name').addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();createCourse()}
  });
})();
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Serve the built-in lightweight web UI."""
    return _INDEX_HTML
