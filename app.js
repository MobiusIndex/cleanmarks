/* 水印清理工具 —— 页面逻辑
 *
 * 数据流：文件只在浏览器里停留；清理请求把 File 作为请求体直发（二进制），
 * 服务端换成引擎要的 base64 信封，结果以二进制 + X-Wm-Report 头返回。
 * 页面因此从不自己拼 base64，也不会因为大文件卡住主线程。
 */
'use strict';

const $ = (id) => document.getElementById(id);
const API = '/api';

const S = {
  meta: null,
  items: [],
  seq: 0,
  run: null,        // {ctrl, kind, total, done, failed, cancelled}
  zip: false,       // 打包中（和 run 互斥，共用进度条）
  zipTotal: 0,
  compare: null,
};

const PREF_KEY = 'wm.prefs.v2';
const DEFAULT_PREFS = {
  metaMode: 'strip',
  audioChain: false,
  normSpace: true,
  nfkc: false,
  homoglyph: false,
  emojiGlue: false,
  bidi: false,
  deepImages: 'auto',
  docLayerA: true,
  theme: 'auto',
};
let P = { ...DEFAULT_PREFS };

const DEEP_MODES = ['auto', 'always', 'lossless', 'never'];
const META_MODES = ['strip', 'keep'];

const AUDIO_EXTS = new Set(['mp3', 'wav', 'flac', 'm4a']);
const TEXT_LIKE = new Set(['md', 'markdown', 'mdx', 'html', 'htm', 'svg']);
// 明确不可能被处理的二进制容器，直接在入队时挡掉；其余交给服务端判定
// （没有扩展名的截图可以靠文件头认出来，普通 .zip/.exe 认不出就是 415）。
const SKIP_EXTS = new Set(['exe', 'dll', 'so', 'dylib', 'msi', 'apk', 'ipa', 'iso', 'dmg',
  'rar', '7z', 'zip', 'tar', 'gz', 'xz', 'bz2', 'bin', 'dat', 'db', 'sqlite', 'tmp',
  'sys', 'pyc', 'class', 'jar', 'lnk', 'msix', 'cab']);
const KIND_CN = { image: '图片', av: '音视频', container: '文档', text: '文本', unknown: '未知' };
const CONF_CN = { confirmed: '已确认', probable: '可能', informational: '提示' };

/* ------------------------------------------------------------ 小工具 */

const fmt = (b) => {
  if (b == null) return '—';
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(b < 10240 ? 2 : 0) + ' KB';
  if (b < 1073741824) return (b / 1048576).toFixed(b < 10485760 ? 2 : 1) + ' MB';
  return (b / 1073741824).toFixed(2) + ' GB';
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));
const extOf = (name) => (name.includes('.') ? name.split('.').pop().toLowerCase() : '');
const b64url = (s) => {
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const unb64 = (s) => {
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
};

function toast(msg, kind = '', ms = 3600) {
  const box = $('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .2s, transform .2s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(4px)';
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/* ------------------------------------------------------------ 偏好 */

function loadPrefs() {
  let raw = {};
  try { raw = JSON.parse(localStorage.getItem(PREF_KEY) || '{}') || {}; } catch { raw = {}; }
  // 只接受与默认值同类型的项（旧版本残留的字符串/对象不该进请求体）
  const clean = {};
  for (const [k, def] of Object.entries(DEFAULT_PREFS)) {
    const v = raw[k];
    if (def === undefined) continue;
    if (typeof v === typeof def || (v === null && def === null)) clean[k] = v;
  }
  P = { ...DEFAULT_PREFS, ...clean };
  if (!DEEP_MODES.includes(P.deepImages)) P.deepImages = DEFAULT_PREFS.deepImages;
  if (!META_MODES.includes(P.metaMode)) P.metaMode = DEFAULT_PREFS.metaMode;
  syncPrefsToUI();
}

function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(P)); } catch { /* 隐私模式 */ }
}

function syncPrefsToUI() {
  $('metaMode').value = P.metaMode;
  $('audioChain').checked = !!P.audioChain;
  $('normSpace').checked = !!P.normSpace;
  $('nfkc').checked = !!P.nfkc;
  $('homoglyph').checked = !!P.homoglyph;
  $('emojiGlue').checked = !!P.emojiGlue;
  $('bidi').checked = !!P.bidi;
  $('deepImages').value = P.deepImages;
  $('docLayerA').checked = !!P.docLayerA;
}

function applyTheme() {
  const t = P.theme;
  if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}

function bindPrefs() {
  const map = {
    metaMode: 'value', audioChain: 'checked', normSpace: 'checked', nfkc: 'checked',
    homoglyph: 'checked', emojiGlue: 'checked', bidi: 'checked', deepImages: 'value',
    docLayerA: 'checked',
  };
  for (const [id, prop] of Object.entries(map)) {
    $(id).addEventListener('change', () => {
      P[id] = $(id)[prop];
      savePrefs();
      updateStats();
    });
  }
  $('resetPrefs').addEventListener('click', () => {
    P = { ...DEFAULT_PREFS, theme: P.theme };
    savePrefs();
    syncPrefsToUI();
    updateStats();
    toast('已恢复默认选项');
  });
  $('themeBtn').addEventListener('click', () => {
    const isDark = document.documentElement.dataset.theme === 'dark'
      || (!document.documentElement.dataset.theme
        && window.matchMedia('(prefers-color-scheme: dark)').matches);
    P.theme = isDark ? 'light' : 'dark';
    savePrefs();
    applyTheme();
  });
}

/* ------------------------------------------------------------ AI 接口（可选） */

/* 各家 OpenAI 兼容端点的 base_url 与常用模型。协议统一走 OpenAI 兼容，
   服务端会自动补 /v1/chat/completions（v2/v4/openai 后缀也能正确拼接）。 */
const PROVIDERS = [
  { id: 'openai', name: 'OpenAI', base: 'https://api.openai.com', models: ['gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4o'], hint: '官方接口，需要 API Key。' },
  { id: 'deepseek', name: 'DeepSeek 深度求索', base: 'https://api.deepseek.com', models: ['deepseek-chat', 'deepseek-reasoner'], hint: '国内直连便宜；reasoner 系列会先思考再回答，慢但更稳。' },
  { id: 'moonshot', name: '月之暗面 Kimi', base: 'https://api.moonshot.cn', models: ['kimi-k2-turbo-preview', 'moonshot-v1-128k'], hint: '长文本友好，适合长文档改写。' },
  { id: 'zhipu', name: '智谱 GLM', base: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-4-flash', 'glm-4-plus', 'glm-4-air'], hint: '注意 base 已含 /v4，路径会自动补全。' },
  { id: 'qwen', name: '阿里云百炼 Qwen', base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-plus', 'qwen-max', 'qwen-turbo'], hint: 'DashScope 的 OpenAI 兼容模式。' },
  { id: 'hunyuan', name: '腾讯混元', base: 'https://api.hunyuan.cloud.tencent.com/v1', models: ['hunyuan-turbos', 'hunyuan-t1'], hint: '腾讯云 OpenAI 兼容端点。' },
  { id: 'spark', name: '讯飞星火', base: 'https://spark-api-open.xf-yun.com/v1', models: ['x1.5', '4.0Ultra'], hint: '星火开放平台。' },
  { id: 'qianfan', name: '百度千帆', base: 'https://qianfan.baidubce.com/v2', models: ['ernie-4.0-8k', 'ernie-speed-8k'], hint: '千帆 v2 兼容端点。' },
  { id: 'siliconflow', name: '硅基流动 SiliconFlow', base: 'https://api.siliconflow.cn/v1', models: ['Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V3'], hint: '聚合平台，模型多。' },
  { id: 'openrouter', name: 'OpenRouter', base: 'https://openrouter.ai/api/v1', models: ['deepseek/deepseek-chat', 'anthropic/claude-sonnet-4.5'], hint: '一个 Key 调多家模型。' },
  { id: 'groq', name: 'Groq', base: 'https://api.groq.com/openai/v1', models: ['llama-3.3-70b-versatile', 'qwen-qwq-32b'], hint: '推理速度极快。' },
  { id: 'xai', name: 'xAI Grok', base: 'https://api.x.ai/v1', models: ['grok-4', 'grok-3-mini'], hint: 'xAI 官方。' },
  { id: 'anthropic', name: 'Anthropic Claude', base: 'https://api.anthropic.com/v1', models: ['claude-sonnet-4-5', 'claude-haiku-4-5'], hint: '走 Anthropic 的 OpenAI 兼容端点。' },
  { id: 'gemini', name: 'Google Gemini', base: 'https://generativelanguage.googleapis.com/v1beta/openai', models: ['gemini-2.5-flash', 'gemini-2.5-pro'], hint: 'Gemini 的 OpenAI 兼容层，base 以 /openai 结尾。' },
  { id: 'ollama', name: 'Ollama（本地，需装在 WSL）', base: 'http://host.docker.internal:11434', models: ['qwen3:8b', 'llama3.1:8b'], hint: '本地模型不出网。容器解析不了 host.docker.internal 时会自动改用 Docker 网关地址；若 Ollama 只监听 127.0.0.1，用 llm-relay.py 在 WSL 里桥一道。' },
  { id: 'lmstudio', name: 'LM Studio（Windows，本机够不到）', base: 'http://host.docker.internal:1234', models: ['local-model'], hint: '实测：WSL 与 Windows 不共享 loopback，容器到不了 Windows 上的 LM Studio。本地跑请把模型服务装到 WSL，或直接用云端 API。' },
  { id: 'custom', name: '自定义（OpenAI 兼容）', base: '', models: [], hint: '任何提供 /v1/chat/completions 的服务都可以。' },
];

const STRATEGIES = [
  { id: 'p04', label: '轻度改写（保守）', spec: 'paraphrase@0.4' },
  { id: 'p08', label: '标准改写', spec: 'paraphrase@0.8' },
  { id: 'p10', label: '彻底改写', spec: 'paraphrase@1.0' },
  { id: 'h08', label: '去 AI 腔', spec: 'humanize@0.8' },
  { id: 'ph', label: '改写 + 去 AI 腔', spec: 'paraphrase@0.6,humanize@0.6' },
  { id: 'st', label: '结构重排', spec: 'structural@0.8' },
  { id: 'bt', label: '回译（最彻底 / 最慢 / 最贵）', spec: 'backtranslate@0.8' },
  { id: 'custom', label: '自定义', spec: '' },
];

const LLM_KEY = 'wm.llm.v1';
const LLM_DEFAULT = {
  enabled: false, provider: 'custom', base_url: '', model: '', api_key: '',
  backend: 'openai-compatible', strategy: 'paraphrase@0.8',
  lang: 'English', original_lang: 'Chinese', timeout: 120, temperature: 0.9,
  remember: true,
};
let LLM = { ...LLM_DEFAULT };

const providerById = (id) => PROVIDERS.find((p) => p.id === id) || PROVIDERS[PROVIDERS.length - 1];

function loadLLM() {
  try {
    const raw = JSON.parse(localStorage.getItem(LLM_KEY) || '{}');
    LLM = { ...LLM_DEFAULT, ...raw };
  } catch { LLM = { ...LLM_DEFAULT }; }
  // 「不记住密钥」时上次存的 key 不恢复
  if (!LLM.remember) LLM.api_key = '';
}

function saveLLM() {
  const store = { ...LLM };
  if (!store.remember) store.api_key = '';
  try { localStorage.setItem(LLM_KEY, JSON.stringify(store)); } catch { /* 隐私模式 */ }
}

function llmPayload() {
  return {
    enabled: true,
    backend: LLM.backend,
    base_url: LLM.base_url,
    model: LLM.model,
    api_key: LLM.api_key,
    strategy: LLM.strategy,
    lang: LLM.lang,
    original_lang: LLM.original_lang,
    timeout: Number(LLM.timeout) || 120,
    temperature: Number(LLM.temperature),
    provider: providerById(LLM.provider).name,
  };
}

/** 只有文本类文件才走 Layer B；图片/音视频/文档与 AI 接口无关。 */
function llmFor(it) {
  if (!LLM.enabled || !LLM.base_url || !LLM.model) return null;
  if (it.kind === 'text') return llmPayload();
  if (it.kind === 'container' && TEXT_LIKE.has(it.ext)) return llmPayload();
  return null;
}

function llmLabel() {
  if (!LLM.enabled) return '未配置';
  const p = providerById(LLM.provider);
  return `${p.name}${LLM.model ? ' · ' + LLM.model : ''}`;
}

function fillLLMForm() {
  $('llmEnabled').checked = !!LLM.enabled;
  $('llmProvider').value = LLM.provider;
  $('llmBase').value = LLM.base_url;
  $('llmModel').value = LLM.model;
  $('llmKey').value = LLM.api_key;
  $('llmRemember').checked = LLM.remember !== false;
  $('llmProtocol').value = LLM.backend;
  $('llmLang').value = LLM.lang;
  $('llmOrigLang').value = LLM.original_lang;
  $('llmTimeout').value = LLM.timeout;
  $('llmTemp').value = LLM.temperature;
  const known = STRATEGIES.find((s) => s.spec && s.spec === LLM.strategy);
  if (known) { $('llmStrategy').value = known.id; $('llmStrategyCustom').value = ''; }
  else { $('llmStrategy').value = 'custom'; $('llmStrategyCustom').value = LLM.strategy || ''; }
  syncProviderHints();
  syncModelHints();
  updateLLMStatus();
}

function syncProviderHints() {
  const p = providerById($('llmProvider').value);
  $('llmProviderHint').textContent = p.hint || '';
}

function syncModelHints() {
  const p = providerById($('llmProvider').value);
  $('llmModels').innerHTML = (p.models || []).map((m) => `<option value="${esc(m)}">`).join('');
}

function readLLMForm() {
  const spec = $('llmStrategy').value === 'custom'
    ? ($('llmStrategyCustom').value || '').trim()
    : (STRATEGIES.find((s) => s.id === $('llmStrategy').value) || {}).spec || '';
  return {
    enabled: $('llmEnabled').checked,
    provider: $('llmProvider').value,
    base_url: $('llmBase').value.trim().replace(/\/+$/, ''),
    model: $('llmModel').value.trim(),
    api_key: $('llmKey').value.trim(),
    backend: $('llmProtocol').value,
    strategy: spec,
    lang: $('llmLang').value.trim() || 'English',
    original_lang: $('llmOrigLang').value.trim() || 'Chinese',
    timeout: Number($('llmTimeout').value) || 120,
    temperature: Number($('llmTemp').value),
    remember: $('llmRemember').checked,
  };
}

function updateLLMStatus() {
  const box = $('llmStatus');
  if (!LLM.enabled) {
    box.className = 'status-line';
    box.textContent = '未启用。其余功能（元数据剥离、隐形字符清理）不受影响。';
  } else if (!LLM.base_url || !LLM.model) {
    box.className = 'status-line bad';
    box.textContent = '已启用，但 Base URL 或模型名还没填。';
  } else {
    box.className = 'status-line ok';
    box.textContent = `已启用：${llmLabel()}｜策略 ${LLM.strategy || '未设置'}`;
  }
  $('llmDot').hidden = !LLM.enabled;
}

async function testLLM() {
  const box = $('llmStatus');
  const cfg = readLLMForm();
  if (!cfg.base_url || !cfg.model) {
    box.className = 'status-line bad';
    box.textContent = '先填 Base URL 和模型名。';
    return;
  }
  box.className = 'status-line';
  box.textContent = '正在测试…';
  try {
    const res = await fetch(API + '/llm/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...cfg, enabled: true }),
    });
    const j = await res.json();
    if (j.ok) {
      box.className = 'status-line ok';
      box.textContent = `连接正常：${j.model}｜${j.latency_ms} ms｜${j.endpoint}`;
    } else {
      box.className = 'status-line bad';
      box.textContent = '连接失败：' + (j.error || '未知错误');
    }
  } catch (e) {
    box.className = 'status-line bad';
    box.textContent = '连接失败：' + e.message;
  }
}

function bindLLM() {
  const sel = $('llmProvider');
  sel.innerHTML = PROVIDERS.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  $('llmStrategy').innerHTML = STRATEGIES.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join('');

  $('llmBtn').addEventListener('click', () => {
    fillLLMForm();
    $('llmDialog').showModal();
  });
  $('llmClose').addEventListener('click', () => $('llmDialog').close());
  $('llmShowKey').addEventListener('click', () => {
    const input = $('llmKey');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    $('llmShowKey').textContent = show ? '隐藏' : '显示';
  });
  sel.addEventListener('change', () => {
    const p = providerById(sel.value);
    if (p.base) {
      $('llmBase').value = p.base;
      if (p.models && p.models.length) $('llmModel').value = p.models[0];
    }
    syncProviderHints();
    syncModelHints();
  });
  $('llmTest').addEventListener('click', testLLM);
  $('llmSave').addEventListener('click', () => {
    LLM = readLLMForm();
    saveLLM();
    updateLLMStatus();
    fillLLMForm();
    renderCaps();
    if (LLM.enabled && (!LLM.base_url || !LLM.model)) {
      // 缺这两项时 llmFor() 会返回 null，文本只会走 Layer A——必须说出来
      toast('已保存，但缺少 Base URL 或模型名，AI 改写不会生效', 'bad', 5200);
      return;
    }
    toast(LLM.enabled ? `AI 接口已保存：${llmLabel()}` : 'AI 接口已停用', LLM.enabled ? 'ok' : '');
  });
  $('llmClear').addEventListener('click', () => {
    LLM = { ...LLM_DEFAULT };
    saveLLM();
    fillLLMForm();
    renderCaps();
    toast('已清除 AI 接口配置');
  });
}

/* ------------------------------------------------------------ 元信息 */

async function loadMeta() {
  try {
    const r = await fetch(API + '/meta', { cache: 'no-store' });
    S.meta = await r.json();
  } catch (e) {
    S.meta = null;
  }
  renderCaps();
  renderFmt();
  updateStatus();
  updateStats();
}

function updateStatus() {
  const el = $('status');
  const ok = S.meta && S.meta.ok;
  el.className = 'pill ' + (ok ? 'on' : 'off');
  el.lastElementChild.textContent = ok
    ? `${S.meta.core_version || '运行中'}`
    : '引擎未连接';
  el.title = ok
    ? `引擎 ${S.meta.core_version} · 界面 ${S.meta.web_version}`
    : '无法连接清洗引擎（wr-core）';
  $('coreVer').textContent = ok ? 'v' + (S.meta.core_version || '?') : '离线';
}

function renderCaps() {
  const box = $('caps');
  if (!S.meta || !S.meta.ok) {
    box.innerHTML = '<div class="sub">引擎未连接，以下能力不可用。</div>';
    return;
  }
  const caps = S.meta.capabilities || {};
  const tools = caps.tools || {};
  const pix = caps.pixel_backends || {};
  const det = caps.text_detectors || {};
  const rows = [
    ['exiftool', !!tools.exiftool],
    ['qpdf', !!tools.qpdf],
    ['ghostscript', !!tools.ghostscript],
    ['ffmpeg', !!tools.ffmpeg],
    ['c2patool', !!tools.c2patool],
  ];
  let html = rows.map(([n, on]) => `<div class="cap-row"><span class="n">${n}</span>
    <span class="v ${on ? 'on' : 'off'}">${on ? '可用' : '缺失'}</span></div>`).join('');
  const anyPix = Object.values(pix).some(Boolean);
  html += `<div class="cap-row"><span class="n">像素级去水印</span>
    <span class="v ${anyPix ? 'on' : 'off'}">${anyPix ? '可用' : '未部署'}</span></div>`;
  const anyDet = Object.values(det).some(Boolean);
  html += `<div class="cap-row"><span class="n">文本水印检测</span>
    <span class="v ${anyDet ? 'on' : 'off'}">${anyDet ? '可用' : '未部署'}</span></div>`;
  const llmOn = !!LLM.enabled;
  const llmText = llmOn ? (LLM.base_url && LLM.model ? '已配置' : '待完善')
    : (S.meta.text_layer_b ? '引擎已配置' : '未配置');
  html += `<div class="cap-row"><span class="n">AI 文本重写</span>
    <span class="v ${llmOn ? 'on' : 'off'}">${llmText}</span></div>`;
  if (llmOn) {
    html += `<div class="cap-row" role="button" tabindex="0" style="cursor:pointer" id="capsLlmRow">
      <span class="n" style="font-family:var(--font);color:var(--text-2)">${esc(llmLabel())}</span>
      <span class="v on" style="cursor:pointer">修改</span></div>`;
  }
  box.innerHTML = html;
  const row = $('capsLlmRow');
  if (row) {
    const open = () => { fillLLMForm(); $('llmDialog').showModal(); };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
    });
  }

  // 引擎没这个能力就把对应控件关掉，别让用户点了才发现报错。
  const opts = S.meta.clean_options || {};
  if ('remove_audio_watermark' in opts) {
    $('audioChain').disabled = false;
  } else {
    // 只禁用、不改勾选：P.audioChain 仍是 true 的话，勾掉会让界面和实际发送的
    // 选项对不上（下一次 savePrefs 又把 true 写回去）
    $('audioChain').disabled = true;
  }
  if ('deep_images' in opts) {
    $('deepImages').disabled = false;
  } else {
    $('deepImages').disabled = true;
  }
  if ('also_layer_a_text' in opts) $('docLayerA').disabled = false;
  else $('docLayerA').disabled = true;
}

function renderFmt() {
  const box = $('fmt');
  const kinds = (S.meta && S.meta.kinds) || null;
  const groups = [
    ['图片', kinds ? kinds.image : 'png jpg webp avif heic bmp gif tiff'],
    ['文档', kinds ? kinds.container : 'pdf docx xlsx pptx odt epub svg html md'],
    ['文本', 'txt json yaml csv py js …'],
    ['音视频', kinds ? kinds.av : 'mp4 mov mp3 wav flac m4a'],
  ];
  box.innerHTML = groups.map(([label, list]) => {
    const arr = Array.isArray(list) ? list : String(list).split(/\s+/);
    const head = arr.slice(0, 3).join(' · ');
    return `<span title="${esc(arr.join(' '))}">${label}：${esc(head)}${arr.length > 3 ? ' …' : ''}</span>`;
  }).join('');
}

/* ------------------------------------------------------------ 分类 */

function kindOf(name) {
  const ext = extOf(name);
  const kinds = S.meta && S.meta.kinds;
  if (kinds) {
    if (kinds.image.includes(ext)) return 'image';
    if (kinds.av.includes(ext)) return 'av';
    if (kinds.container.includes(ext)) return 'container';
    if (kinds.text.includes(ext)) return 'text';
    return 'unknown';
  }
  if (/^(png|jpe?g|webp|avif|hei[cf]|bmp|gif|tiff?)$/.test(ext)) return 'image';
  if (/^(mp4|mov|m4v|m4a|wav|mp3|flac)$/.test(ext)) return 'av';
  if (/^(pdf|docx|xlsx|pptx|odt|epub|svg|html?|md|markdown|mdx)$/.test(ext)) return 'container';
  if (ext) return 'text';
  return 'unknown';
}

/* ------------------------------------------------------------ 入队 */

function addFiles(files) {
  const maxInput = (S.meta && S.meta.limits && S.meta.limits.max_input) || 256 * 1024 * 1024;
  const maxCount = (S.meta && S.meta.limits && S.meta.limits.max_batch) || 200;
  const bad = [];
  let dup = 0;
  let added = 0;
  for (const f of files) {
    if (!f || typeof f.size !== 'number') continue;
    const name = f.name || `image-${Date.now()}.png`;
    const ext0 = extOf(name);
    if (SKIP_EXTS.has(ext0)) { bad.push(name); continue; }
    const kind = kindOf(name);
    if (f.size === 0) { bad.push(name); continue; }
    if (f.size > maxInput) {
      toast(`${name} 超过单文件上限 ${fmt(maxInput)}`, 'bad');
      continue;
    }
    if (S.items.length >= maxCount) {
      toast(`一次最多 ${maxCount} 个文件`, 'bad');
      break;
    }
    const dkey = `${f.webkitRelativePath || name}|${f.size}|${f.lastModified || 0}`;
    if (S.items.some((it) => it.dkey === dkey)) { dup++; continue; }
    S.items.push({
      id: ++S.seq,
      file: f,
      dkey,
      name,
      size: f.size,
      ext: extOf(name),
      kind,
      status: 'ready',
      report: null,
      after: null,
      blob: null,
      outSize: null,
      outURL: null,
      error: null,
      open: false,
      url: kind === 'image' && /^(png|jpe?g|webp|avif|gif|bmp)$/.test(extOf(name))
        ? URL.createObjectURL(f) : null,
    });
    added++;
  }
  if (bad.length) {
    toast(`跳过 ${bad.length} 个无法处理的文件：${bad.slice(0, 3).join('、')}${bad.length > 3 ? ' …' : ''}`, 'bad', 5200);
  }
  if (dup) toast(`忽略 ${dup} 个重复文件`);
  if (added) {
    renderList();
    updateStats();
  }
  return added;
}

async function walkEntry(entry, out) {
  if (!entry) return;
  if (entry.isFile) {
    await new Promise((res) => entry.file((f) => { out.push(f); res(); }, res));
    return;
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch;
    do {
      batch = await new Promise((res) => reader.readEntries(res, () => res([])));
      for (const e of batch) await walkEntry(e, out);
    } while (batch.length);
  }
}

/* ------------------------------------------------------------ 渲染 */

function renderList() {
  const list = $('list');
  if (!S.items.length) {
    list.innerHTML = '<li class="item empty">还没有文件。拖入、点击或粘贴都可以。</li>';
    return;
  }
  const seen = new Set(S.items.map((it) => it.id));
  for (const el of Array.from(list.children)) {
    if (el.dataset.id && !seen.has(Number(el.dataset.id))) el.remove();
  }
  const empty = list.querySelector('.empty');
  if (empty) empty.remove();
  for (const it of S.items) {
    if (!it.el) {
      const li = document.createElement('li');
      li.className = 'item';
      li.dataset.id = String(it.id);
      li.innerHTML = cardShell(it);
      list.appendChild(li);
      it.el = li;
      setThumb(it);
    }
    refresh(it);
  }
}

function setThumb(it) {
  const thumb = it.el && it.el.querySelector('.thumb');
  if (!thumb) return;
  if (it.url) {
    const img = document.createElement('img');
    img.src = it.url;
    img.alt = '';
    img.loading = 'lazy';
    thumb.textContent = '';
    thumb.appendChild(img);
  } else {
    thumb.textContent = it.ext
      ? it.ext.toUpperCase().slice(0, 5)
      : ({ image: 'IMG', av: 'AV', container: 'DOC', text: 'TXT' }[it.kind] || '?');
  }
}

function cardShell(it) {
  return `<div class="thumb"></div><div class="body"></div>`;
}

function refresh(it) {
  if (!it.el) return;
  // 记住卡片里当前焦点在哪个动作上，重绘后还回去（键盘用户不该被重绘踢出去）
  const active = document.activeElement;
  const focusKey = active && it.el.contains(active)
    ? (active.dataset.act || active.dataset.role || null) : undefined;
  const body = it.el.querySelector('.body');
  it.el.className = 'item'
    + (it.status === 'working' ? ' busy' : '')
    + (it.status === 'error' ? ' bad' : '');
  body.innerHTML = cardBody(it);
  wire(it);
  if (focusKey) {
    const again = body.querySelector(`[data-act="${focusKey}"]`);
    if (again) again.focus();
  }
}

function statusChip(it) {
  if (it.status === 'working') return '<span class="chip run dot"><i></i>处理中</span>';
  if (it.status === 'error') return '<span class="chip bad">失败</span>';
  const marks = marksOf(it.report);
  if (it.status === 'cleaned') {
    const resid = it.after ? marksOf(it.after) : [];
    const dirty = resid.length || (it.after && (it.after.has_c2pa || it.after.has_ai_metadata));
    if (!it.after) return '<span class="chip ok">已清理</span>';
    const flags = (it.after.has_c2pa ? 1 : 0) + (it.after.has_ai_metadata ? 1 : 0);
    return dirty
      ? `<span class="chip hit">复检有残留 ${resid.length + flags}</span>`
      : '<span class="chip ok">已清理 · 复检通过</span>';
  }
  if (it.status === 'checked') {
    const dirty = marks.length || it.report?.has_c2pa || it.report?.has_ai_metadata
      || (it.report?.suspicious_total > 0);
    return dirty
      ? `<span class="chip hit">检出 ${marks.length || 1} 项</span>`
      : '<span class="chip ok">未见标记</span>';
  }
  return '<span class="chip">待处理</span>';
}

function marksOf(rep) {
  if (!rep) return [];
  // 引擎对纯文本返回 hits[]，对容器返回 layer_a_hits[] + findings[]，两套都要认。
  const out = [];
  const seen = new Set();
  const push = (item) => {
    const key = item.text + '|' + item.conf;
    if (item.text && !seen.has(key)) { seen.add(key); out.push(item); }
  };
  const hits = Array.isArray(rep.layer_a_hits) && rep.layer_a_hits.length
    ? rep.layer_a_hits
    : (Array.isArray(rep.hits) ? rep.hits : []);
  for (const h of hits) {
    if (!h || typeof h !== 'object') continue;
    const cp = String(h.codepoint || '');
    push({
      text: `${cp} ${shortLabel(h.label, cp)} ×${h.count || 1}`.replace(/\s+/g, ' ').trim(),
      conf: h.confidence || 'probable',
    });
  }
  if (Array.isArray(rep.findings) && rep.findings.length) {
    rep.findings.forEach((f, i) => {
      if (!f || /^unsupported format/i.test(f)) return;
      push({ text: tidyFinding(f), conf: (rep.findings_confidence || [])[i] || 'probable' });
    });
  }
  if (out.length) return out;
  const st = rep.stats;
  if (st && (st.removed || st.replaced)) {
    const list = [];
    for (const [k, v] of Object.entries(st.removed || {})) {
      list.push({ text: `${k} ×${v}`, conf: 'confirmed' });
    }
    for (const [k, v] of Object.entries(st.replaced || {})) {
      list.push({ text: `${k} → 等价字符 ×${v}`, conf: 'confirmed' });
    }
    return list;
  }
  return [];
}

function shortLabel(label, cp) {
  if (!label) return '';
  return String(label).replace(new RegExp('^' + String(cp || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*'), '')
    .replace(/\s*\((Cf|Zs|Mn|Cc)\)\s*$/, '');
}

function tidyFinding(f) {
  // 引擎有的行会写成 "layer-a: U+200B U+200B ZERO WIDTH SPACE (Cf) x1 (...)"
  return String(f)
    .replace(/^(layer-a)(\s*\([^)]*\))?:\s+/, '$1：')
    .replace(/(U\+[0-9A-F]{4,6}) \1 /, '$1 ')
    .trim();
}

function actionsHTML(it) {
  const b = (act, label, cls = '') =>
    `<button class="btn sm ${cls}" data-act="${act}">${label}</button>`;
  const out = [];
  if (it.status !== 'working') {
    if (it.blob) {
      out.push(b('inspect', '重检'));
      out.push(b('save', '下载', 'primary'));
      if (it.kind === 'image' && it.url) out.push(b('compare', '对比'));
      out.push(b('clean', '重新清理'));
    } else {
      out.push(b('inspect', it.status === 'ready' ? '检测' : '重检'));
      out.push(b('clean', '清理', 'primary'));
    }
    out.push(b('remove', '移除', 'ghost'));
  }
  return `<div class="acts">${out.join('')}</div>`;
}

function detailHTML(it) {
  const rep = it.report;
  const rows = [];
  const marks = marksOf(rep);
  const pre = it.status === 'cleaned' ? '清理前检出' : '检出';
  if (marks.length) {
    rows.push(`<div class="dline"><span class="k">${pre}</span><div class="v"><div class="flist">${
      marks.slice(0, 12).map((m) => `<div class="fitem ${m.conf === 'informational' ? 'info' : ''}">${
        esc(m.text)}<span style="color:var(--text-3)">· ${esc(CONF_CN[m.conf] || m.conf)}</span></div>`).join('')
    }${marks.length > 12 ? `<div class="fitem info">…另有 ${marks.length - 12} 项</div>` : ''}</div></div></div>`);
  }
  if (rep && rep.has_c2pa) {
    rows.push('<div class="dline"><span class="k">C2PA</span><div class="v">检测到 Content Credentials 清单</div></div>');
  }
  if (rep && Array.isArray(rep.actions) && rep.actions.length) {
    rows.push(`<div class="dline"><span class="k">处理</span><div class="v">${
      rep.actions.slice(0, 8).map((a) => esc(a)).join('<br>')}</div></div>`);
  }
  if (it.status === 'cleaned' && !it.after && it.size > 16 * 1024 * 1024) {
    rows.push(`<div class="dline"><span class="k">复检</span><div class="v">大文件未自动复检，可点「重检」对输出再做一次检测</div></div>`);
  }
  if (it.after) {
    const resid = marksOf(it.after);
    const clean = !resid.length && !it.after.has_c2pa && !it.after.has_ai_metadata;
    const why = [];
    if (resid.length) why.push(resid.slice(0, 6).map((m) => esc(m.text)).join('；'));
    if (it.after.has_c2pa) why.push('C2PA 清单');
    if (it.after.has_ai_metadata) why.push('AI 元数据');
    rows.push(`<div class="dline"><span class="k">复检</span><div class="v">${
      clean ? '未发现 C2PA、AI 元数据或隐藏字符' : '仍有：' + why.join('；')
    }</div></div>`);
  }
  if (it.blob) {
    rows.push(`<div class="dline"><span class="k">体积</span><div class="v"><code>${
      fmt(it.size)}</code> → <code>${fmt(it.blob.size)}</code></div></div>`);
  }
  if (it.report && it.report.layer_a_only) {
    rows.push('<div class="dline"><span class="k">范围</span><div class="v">仅 Layer A：隐形字符清理，未做 AI 文本重写</div></div>');
  }
  if (it.report && it.report.layer_b) {
    const lb = it.report.layer_b;
    const lbStrategy = Array.isArray(lb.strategy) ? lb.strategy.join(', ') : String(lb.strategy ?? '');
    rows.push(`<div class="dline"><span class="k">Layer B</span><div class="v">${
      esc(lbStrategy || '模型改写')
    }${lb.model ? ' · ' + esc(lb.model) : ''}${
      (lb.steps || []).length ? ' · ' + lb.steps.length + ' 步' : ''}</div></div>`);
  }
  if (it.error) {
    rows.push(`<div class="dline"><span class="k">错误</span><div class="v" style="color:var(--danger)">${esc(it.error)}</div></div>`);
  }
  if (!rows.length) return '';
  return `<details class="more"${it.open ? ' open' : ''}><summary>详情${marks.length ? ` · ${marks.length}` : ''}</summary>
    <div class="detail">${rows.join('')}</div></details>`;
}

function cardBody(it) {
  const size = it.blob
    ? `${fmt(it.size)} → <b style="color:var(--brand-strong)">${fmt(it.blob.size)}</b>`
    : fmt(it.size);
  // ext 来自文件名（用户可控），必须转义后再进 innerHTML
  const extTag = it.ext ? ' · ' + esc(it.ext.toUpperCase()) : '';
  const meta = `${size} · ${esc(KIND_CN[it.kind] || it.kind)}${extTag}`;
  const lbChip = it.report && it.report.layer_b
    ? '<span class="chip run dot" title="用了配置的 AI 接口做模型改写"><i></i>Layer B</span>' : '';
  return `<div class="row1">
      <span class="nm" title="${esc(it.name)}">${esc(it.name)}</span>
      <span class="meta">${meta}</span>
      <span class="push"></span>
      ${statusChip(it)}${lbChip}
    </div>
    ${detailHTML(it)}
    ${actionsHTML(it)}`;
}

function wire(it) {
  const body = it.el.querySelector('.body');
  body.querySelectorAll('[data-act]').forEach((btn) => {
    btn.addEventListener('click', () => onAction(btn.dataset.act, it));
  });
  const det = body.querySelector('details.more');
  if (det) det.addEventListener('toggle', () => { it.open = det.open; });
}

/* ------------------------------------------------------------ 统计 */

function updateStats() {
  const n = S.items.length;
  const done = S.items.filter((i) => i.status === 'cleaned').length;
  const hit = S.items.filter((i) => {
    const m = marksOf(i.report);
    return m.length || i.report?.has_c2pa || i.report?.has_ai_metadata;
  }).length;
  const totalIn = S.items.reduce((a, i) => a + i.size, 0);
  const totalOut = S.items.reduce((a, i) => a + (i.blob ? i.blob.size : 0), 0);
  const busy = !!S.run || !!S.zip;      // 打包和批量任务共用一套忙碌状态

  const stats = $('stats');
  if (!n) {
    stats.textContent = '';
  } else {
    stats.innerHTML = `<b>${n}</b> 个文件 <span class="sep">·</span> ${fmt(totalIn)}`
      + (hit ? ` <span class="sep">·</span> 有标记 <b>${hit}</b> 个` : '')
      + (done ? ` <span class="sep">·</span> 已清理 <b>${done}</b>，输出 ${fmt(totalOut)}` : '');
  }

  const anyReady = S.items.some((i) => i.status !== 'working');
  $('inspectBtn').disabled = busy || !anyReady;
  $('cleanBtn').disabled = busy || !anyReady;
  $('zipBtn').disabled = busy || !S.items.some((i) => i.blob);
  const zipLabel = $('zipBtn').lastChild;
  if (S.zip && zipLabel) zipLabel.textContent = ' 打包中…';
  $('clearBtn').disabled = busy || !n;
  $('cleanBtn').title = busy ? '正在处理' : '清理全部未完成的文件';
}

/* ------------------------------------------------------------ 请求 */

function coreOptions(o, kind) {
  const allowed = S.meta && S.meta.clean_options;
  if (!allowed || kind === 'text') return o;
  const out = {};
  for (const [k, v] of Object.entries(o)) if (k in allowed) out[k] = v;
  // 键对了值也可能不对：deep_images 只认 auto/always/lossless/never，
  // localStorage 里的脏值原样发过去会让整单 400
  const modes = S.meta && S.meta.limits && S.meta.limits.deep_image_modes;
  if ('deep_images' in out && Array.isArray(modes) && !modes.includes(out.deep_images)) {
    out.deep_images = 'auto';
  }
  if ('strategy' in out && typeof out.strategy !== 'string') delete out.strategy;
  if ('style' in out && typeof out.style !== 'string') delete out.style;
  return out;
}

function optionsFor(it) {
  const o = {};
  if (it.kind === 'image' || it.kind === 'av') {
    o.keep_non_ai_metadata = P.metaMode === 'keep';
  }
  if (it.kind === 'av' && P.audioChain && AUDIO_EXTS.has(it.ext)) {
    o.remove_audio_watermark = true;
  }
  if (it.kind === 'container') {
    o.deep_images = P.deepImages;
    o.also_layer_a_text = !!P.docLayerA;
  }
  if (it.kind === 'container' || it.kind === 'text' || TEXT_LIKE.has(it.ext)) {
    o.normalize_spaces = !!P.normSpace;
  }
  if (it.kind === 'text' || TEXT_LIKE.has(it.ext)) {
    if (P.nfkc) o.nfkc = true;
    if (P.homoglyph) o.aggressive_homoglyphs = true;
    if (P.emojiGlue) o.strip_emoji_glue = true;
    if (P.bidi) o.strip_bidi = true;
  }
  return coreOptions(o, it.kind);
}

async function rawFetch(path, file, name, options, signal, llm) {
  const headers = {
    'Content-Type': 'application/octet-stream',
    'X-Wm-Name': b64url(name),
  };
  if (options) headers['X-Wm-Options'] = b64url(JSON.stringify(options));
  if (llm) headers['X-Wm-Llm'] = b64url(JSON.stringify(llm));
  const res = await fetch(API + path, { method: 'POST', body: file, headers, signal });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j && j.error) msg = j.error;
    } catch { /* 非 JSON */ }
    throw new Error(msg);
  }
  return res;
}

function readReport(res) {
  const raw = res.headers.get('X-Wm-Report');
  if (!raw) return null;
  try { return JSON.parse(unb64(raw)); } catch { return null; }
}

function readOutName(res, fallback) {
  const raw = res.headers.get('X-Wm-Out-Name');
  if (!raw) return fallback;
  try { return unb64(raw.replace(/-/g, '+').replace(/_/g, '/') + '=='.slice(0, (4 - raw.length % 4) % 4)); }
  catch { return fallback; }
}

/* ------------------------------------------------------------ 动作 */

async function onAction(act, it) {
  if (act === 'remove') {
    if (it.status === 'working') return;
    if (it.url) URL.revokeObjectURL(it.url);
    if (it.outURL) URL.revokeObjectURL(it.outURL);
    it.el?.remove();
    S.items = S.items.filter((x) => x !== it);
    renderList();
    updateStats();
    return;
  }
  if (act === 'save') { saveBlob(it); return; }
  if (act === 'compare') { openCompare(it); return; }
  if (S.run) { toast('正在处理中，先等这一批完成'); return; }
  if (act === 'inspect') await runBatch('inspect', [it]);
  if (act === 'clean') await runBatch('clean', [it]);
}

function cleanedName(name) {
  const m = name.match(/^(.*?)(\.[^.\\/]+)?$/);
  const base = m[1] || '';
  const ext = m[2] || '';
  if (!base) return `${name}.cleaned`;      // .bashrc → .bashrc.cleaned
  return `${base}.cleaned${ext}`;
}

function saveBlob(it) {
  if (!it.blob) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(it.blob);
  a.download = it.outName || cleanedName(it.name);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

async function inspectOne(it, signal) {
  const prev = it.status;
  // 已经清理过的条目，再点「重检」意思是对输出再做一次检测（复检），
  // 不能拿原始文件去测——那会把状态打回「检出」并覆盖掉清理结果的报告。
  const verify = prev === 'cleaned' && !!it.blob;
  it.status = 'working';
  refresh(it);
  try {
    const src = verify
      ? new File([it.blob], it.name, { type: it.blob.type || 'application/octet-stream' })
      : it.file;
    const res = await rawFetch('/raw/inspect', src, it.name, null, signal);
    const j = await res.json();
    if (verify) {
      it.after = j.report || null;
      it.status = 'cleaned';
    } else {
      it.report = j.report || {};
      if (j.kind && j.kind !== it.kind) { it.kind = j.kind; setThumb(it); }
      it.status = 'checked';
    }
    it.error = null;
  } catch (e) {
    // 被取消时回到原来的状态，别把已经清理好的条目退成「待处理」
    it.status = signal.aborted ? prev : 'error';
    if (!signal.aborted) it.error = e.message;
    refresh(it);
    return false;
  }
  refresh(it);
  return true;
}

async function cleanOne(it, signal) {
  const prev = it.status;
  it.status = 'working';
  it.error = null;
  it.after = null;          // 复检结果属于上一次输出，先清掉
  refresh(it);
  try {
    const res = await rawFetch('/raw/clean', it.file, it.name, optionsFor(it), signal, llmFor(it));
    const blob = await res.blob();
    const rep = readReport(res);
    const kindHdr = res.headers.get('X-Wm-Kind');
    if (kindHdr && kindHdr !== it.kind) {
      it.kind = kindHdr;
      if (it.kind === 'image' && !it.url) it.url = URL.createObjectURL(it.file);
      setThumb(it);
    }
    if (it.outURL) URL.revokeObjectURL(it.outURL);
    it.blob = blob;
    it.outName = readOutName(res, cleanedName(it.name));
    it.outURL = it.kind === 'image' ? URL.createObjectURL(blob) : null;
    if (!S.items.includes(it)) {
      // 处理过程中被「移除」了：别留下没人回收的 object URL
      if (it.outURL) { URL.revokeObjectURL(it.outURL); it.outURL = null; }
      it.blob = null;
      return true;
    }
    it.report = rep || it.report || {};
    it.status = 'cleaned';
    refresh(it);

    // 复检：引擎顺手报过 detect_after 的就直接用，省掉把输出再传一遍；
    // 超过 16MB 也不自动复检（等于双倍流量），留给用户点卡片上的「重检」。
    const inline = rep && (Array.isArray(rep.post_findings)
      || 'still_has_c2pa' in rep || 'still_has_ai_metadata' in rep);
    if (inline) {
      it.after = {
        findings: rep.post_findings || [],
        has_c2pa: !!rep.still_has_c2pa,
        has_ai_metadata: !!rep.still_has_ai_metadata,
      };
      refresh(it);
    } else if (it.size <= 16 * 1024 * 1024) {
      try {
        const vf = new File([blob], it.name, { type: blob.type || 'application/octet-stream' });
        const vres = await rawFetch('/raw/inspect', vf, it.name, null, signal);
        const vj = await vres.json();
        it.after = vj.report || null;
        refresh(it);
      } catch { /* 复检失败不影响输出 */ }
    }
    return true;
  } catch (e) {
    it.status = signal.aborted ? prev : 'error';
    if (!signal.aborted) {
      it.error = e.message;
      // 失败时不能还挂着上一次的 blob：卡片写着「失败」却给一个能下载的旧结果
      if (it.outURL) { URL.revokeObjectURL(it.outURL); it.outURL = null; }
      it.blob = null;
      it.outName = null;
      it.after = null;
    }
    refresh(it);
    return false;
  }
}

async function runBatch(kind, subset) {
  if (S.run) return;
  // 全量运行时跳过已清理的条目（它们的原件已经被处理过，再跑只会覆盖结果）；
  // 针对单个文件的按钮则不受此限制。
  const pool = subset || S.items.filter((it) => it.status !== 'cleaned');
  const targets = pool.filter((it) => it.status !== 'working');
  if (!targets.length) {
    toast(kind === 'clean' && S.items.some((i) => i.status === 'cleaned')
      ? '所有文件都已清理。要重跑请点单条卡片的「清理」。'
      : '没有需要处理的文件');
    return;
  }

  const ctrl = new AbortController();
  S.run = { ctrl, kind, total: targets.length, done: 0, failed: 0, cancelled: false };
  $('prog').hidden = false;
  $('progLabel').textContent = kind === 'clean' ? '正在清理' : '正在检测';
  $('progCount').textContent = `0 / ${targets.length}`;
  $('progPct').textContent = '0%';
  $('fill').style.width = '0%';
  $('prog').setAttribute('aria-valuenow', '0');
  $('cancelBtn').hidden = false;
  updateStats();

  const limit = kind === 'clean' ? 2 : 4;
  let cursor = 0;

  const worker = async () => {
    while (true) {
      if (ctrl.signal.aborted) return;
      const i = cursor++;
      if (i >= targets.length) return;
      const it = targets[i];
      // 排队期间用户点了「移除」：别再花一次引擎调用，也别产出孤儿 blob
      if (!S.items.includes(it)) { S.run.done++; updateStats(); continue; }
      const ok = kind === 'clean'
        ? await cleanOne(it, ctrl.signal)
        : await inspectOne(it, ctrl.signal);
      S.run.done++;
      if (!ok) S.run.failed++;
      if (!ctrl.signal.aborted) {
        const pct = Math.round((S.run.done / S.run.total) * 100);
        $('fill').style.width = pct + '%';
        $('prog').setAttribute('aria-valuenow', String(pct));
        $('progPct').textContent = pct + '%';
        $('progCount').textContent = `${S.run.done} / ${S.run.total}`;
      }
      updateStats();
    }
  };

  // 任何一条 worker 抛错都不能把 S.run 留成非空——那会让清理/检测/打包/清空
  // 全部变灰、进度条卡住，点取消也救不回来（只有 abort，没有清状态）。
  let summary;
  try {
    await Promise.all(Array.from({ length: Math.min(limit, targets.length) }, worker));
  } finally {
    summary = { ...S.run };
    S.run = null;
    $('cancelBtn').hidden = true;
    if (!S.zip) $('prog').hidden = true;
    updateStats();
    renderList();
  }

  const { done, failed, cancelled } = summary;
  if (cancelled) toast(`已取消（完成 ${Math.max(0, done - failed)} 个）`);
  else if (failed) toast(`完成 ${done} 个，失败 ${failed} 个`, 'bad');
  else toast(kind === 'clean' ? `清理完成：${done} 个文件` : `检测完成：${done} 个文件`, 'ok');
}

/* ------------------------------------------------------------ 对比 */

function setSplit(pct) {
  const v = Math.max(0, Math.min(100, pct));
  $('vwClip').value = v;
  $('vwAfter').style.clipPath = `inset(0 0 0 ${v}%)`;   // after 保留右半边
  $('vwDivider').style.left = v + '%';
}

function openCompare(it) {
  if (!it.url || !it.blob) return;
  if (!it.outURL) it.outURL = URL.createObjectURL(it.blob);
  $('vwTitle').textContent = it.name;
  $('vwBefore').src = it.url;
  $('vwAfter').src = it.outURL;
  setSplit(50);
  const old = it.report?.bytes_in ?? it.size;
  const now = it.blob.size;
  const delta = old ? Math.round((now - old) / old * 100) : 0;
  $('vwMeta').innerHTML = `<span>${fmt(old)} → ${fmt(now)}</span>`
    + `<span>${delta >= 0 ? '+' : ''}${delta}%</span>`
    + `<span>${it.after ? (marksOf(it.after).length ? '复检：仍有残留' : '复检：通过') : ''}</span>`;
  $('viewer').showModal();
}

function closeCompare() {
  $('viewer').close();
  $('vwBefore').removeAttribute('src');
  $('vwAfter').removeAttribute('src');
  $('vwTitle').textContent = '对比';
  $('vwMeta').innerHTML = '';
}

/* ------------------------------------------------------------ ZIP */

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

async function crcOfBlob(blob) {
  let crc = 0xFFFFFFFF;
  const reader = blob.stream().getReader();
  let buf = new Uint8Array(0);
  const step = 1 << 20;
  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      const merged = new Uint8Array(buf.length + value.length);
      merged.set(buf); merged.set(value, buf.length);
      buf = merged;
    }
    let off = 0;
    while (buf.length - off >= step) {
      const slice = buf.subarray(off, off + step);
      for (let i = 0; i < slice.length; i++) crc = CRC_TABLE[(crc ^ slice[i]) & 0xFF] ^ (crc >>> 8);
      off += step;
    }
    buf = buf.slice(off);
    if (done) break;
  }
  for (let i = 0; i < buf.length; i++) crc = CRC_TABLE[(crc ^ buf[i]) & 0xFF] ^ (crc >>> 8);
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

function dosTime(d) {
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
    date: ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  };
}

async function buildZip(entries, onProgress) {
  const enc = new TextEncoder();
  const now = dosTime(new Date());
  const parts = [];
  const central = [];
  let offset = 0;
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const nameBytes = enc.encode(e.name);
    const crc = await crcOfBlob(e.blob);
    const size = e.blob.size;
    const local = new Uint8Array(30 + nameBytes.length);
    const dv = new DataView(local.buffer);
    dv.setUint32(0, 0x04034b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 0x0800, true);       // 文件名用 UTF-8
    dv.setUint16(8, 0, true);            // 存储（不压缩）
    dv.setUint16(10, now.time, true);
    dv.setUint16(12, now.date, true);
    dv.setUint32(14, crc, true);
    dv.setUint32(18, size, true);
    dv.setUint32(22, size, true);
    dv.setUint16(26, nameBytes.length, true);
    dv.setUint16(28, 0, true);
    local.set(nameBytes, 30);
    parts.push(local, e.blob);
    central.push({ nameBytes, crc, size, offset });
    offset += local.length + size;
    if (onProgress) onProgress((i + 1) / entries.length);
  }
  const cdParts = [];
  let cdSize = 0;
  for (const c of central) {
    const buf = new Uint8Array(46 + c.nameBytes.length);
    const dv = new DataView(buf.buffer);
    dv.setUint32(0, 0x02014b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 20, true);
    dv.setUint16(8, 0x0800, true);
    dv.setUint16(10, 0, true);
    dv.setUint16(12, now.time, true);
    dv.setUint16(14, now.date, true);
    dv.setUint32(16, c.crc, true);
    dv.setUint32(20, c.size, true);
    dv.setUint32(24, c.size, true);
    dv.setUint16(28, c.nameBytes.length, true);
    dv.setUint16(30, 0, true);
    dv.setUint16(32, 0, true);
    dv.setUint16(34, 0, true);
    dv.setUint16(36, 0, true);
    dv.setUint32(38, 0, true);
    dv.setUint32(42, c.offset, true);
    buf.set(c.nameBytes, 46);
    cdParts.push(buf);
    cdSize += buf.length;
  }
  const end = new Uint8Array(22);
  const dv = new DataView(end.buffer);
  dv.setUint32(0, 0x06054b50, true);
  dv.setUint16(8, central.length, true);
  dv.setUint16(10, central.length, true);
  dv.setUint32(12, cdSize, true);
  dv.setUint32(16, offset, true);
  return new Blob([...parts, ...cdParts, end], { type: 'application/zip' });
}

async function downloadZip() {
  const items = S.items.filter((it) => it.blob);
  if (!items.length) { toast('还没有清理完成的文件'); return; }
  if (S.run || S.zip) { toast('正在处理中'); return; }
  const totalBytes = items.reduce((a, it) => a + it.blob.size + 256, 0);
  if (totalBytes > 0xFFFFFFFF) {
    // 这里的 ZIP 是手写的 store 模式 + 32 位偏移，没有 zip64：超 4GB 会写出
    // CRC 正确但中央目录错位的坏包，宁可拒绝
    toast(`打包总量 ${fmt(totalBytes)} 超过 4 GB，请分批下载（ZIP 不支持 zip64）`, 'bad', 6000);
    return;
  }
  S.zip = true;
  S.zipTotal = items.length;
  updateStats();
  const label = $('zipBtn').lastChild;
  const old = label.textContent;
  label.textContent = ' 打包中…';
  try {
    const used = new Set();
    const entries = items.map((it) => {
      let name = it.outName || cleanedName(it.name);
      while (used.has(name)) name = name.replace(/(\.[^.]+)?$/, (m) => '_2' + (m || ''));
      used.add(name);
      return { name, blob: it.blob };
    });
    const zip = await buildZip(entries, (p) => {
      $('prog').hidden = false;
      $('progLabel').textContent = '正在打包';
      $('progCount').textContent = `${Math.round(p * entries.length)} / ${entries.length}`;
      $('progPct').textContent = Math.round(p * 100) + '%';
      $('fill').style.width = Math.round(p * 100) + '%';
      $('cancelBtn').hidden = true;
    });
    const url = URL.createObjectURL(zip);
    const a = document.createElement('a');
    const d = new Date();
    const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}-${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`;
    a.href = url;
    a.download = `cleaned-${stamp}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast(`已打包 ${entries.length} 个文件（${fmt(zip.size)}）`, 'ok');
  } catch (e) {
    toast('打包失败：' + e.message, 'bad');
  } finally {
    S.zip = false;
    S.zipTotal = 0;
    $('prog').hidden = !S.run;
    label.textContent = old;
    updateStats();
  }
}

/* ------------------------------------------------------------ 事件 */

function bindEvents() {
  const drop = $('drop');
  // 只认「点在自己身上」的点击。投放区里还有两个隐藏 input 和一个目录按钮：
  // 程序化触发的 input.click() 会冒泡回投放区，不拦就会再开一次选择框。
  drop.addEventListener('click', (e) => {
    const t = e.target;
    if (t === $('pick') || t === $('pickDir') || (t.closest && t.closest('#pickDirBtn'))) return;
    $('pick').click();
  });
  $('pickDirBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    $('pickDir').click();
  });
  drop.addEventListener('keydown', (e) => {
    // 只处理投放区自己拿到焦点的情况；里面的「选择文件夹」是真按钮，
    // 不加这句会把它的 Enter/Space 吞掉，键盘用户永远打不开目录选择。
    if (e.target !== drop) return;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('pick').click(); }
  });
  $('pick').addEventListener('change', (e) => {
    addFiles([...e.target.files]);
    e.target.value = '';
  });
  $('pickDir').addEventListener('change', (e) => {
    addFiles([...e.target.files]);
    e.target.value = '';
  });

  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => {
    e.preventDefault();
    drop.classList.add('hot');
  }));
  ['dragleave', 'dragend'].forEach((t) => drop.addEventListener(t, (e) => {
    // 拖到内部子元素上也会触发 dragleave（target 是子元素），
    // 只有真正离开整个投放区才收高亮
    if (e.target === drop || !drop.contains(e.relatedTarget)) drop.classList.remove('hot');
  }));
  drop.addEventListener('drop', async (e) => {
    e.preventDefault();
    drop.classList.remove('hot');
    const dt = e.dataTransfer;
    if (!dt) return;
    const entries = [...(dt.items || [])]
      .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
      .filter(Boolean);
    if (entries.some((x) => x.isDirectory)) {
      const files = [];
      for (const en of entries) await walkEntry(en, files);
      addFiles(files);
    } else {
      addFiles([...dt.files]);
    }
  });

  // 阻止浏览器把拖到页面别处的文件直接打开
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  window.addEventListener('paste', (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (!files.length) return;
    // 剪贴板里的截图没有扩展名，补一个
    files.forEach((f) => {
      if (!f.name || !extOf(f.name)) {
        Object.defineProperty(f, 'name', {
          value: `paste-${Date.now()}.png`,
          configurable: true,
        });
      }
    });
    if (addFiles(files)) toast(`已粘贴 ${files.length} 个文件`);
  });

  $('inspectBtn').addEventListener('click', () => runBatch('inspect'));
  $('cleanBtn').addEventListener('click', () => runBatch('clean'));
  $('zipBtn').addEventListener('click', downloadZip);
  $('clearBtn').addEventListener('click', () => {
    if (S.run) return;
    S.items.forEach((it) => {
      if (it.url) URL.revokeObjectURL(it.url);
      if (it.outURL) URL.revokeObjectURL(it.outURL);
    });
    S.items = [];
    $('list').innerHTML = '';
    renderList();
    updateStats();
  });
  $('cancelBtn').addEventListener('click', () => {
    if (!S.run) return;
    S.run.cancelled = true;
    S.run.ctrl.abort();
    $('cancelBtn').hidden = true;
    $('progLabel').textContent = '正在取消…';
  });

  $('viewer').addEventListener('close', () => {
    $('vwBefore').src = '';
    $('vwAfter').src = '';
  });
  $('vwClose').addEventListener('click', closeCompare);
  $('vwClip').addEventListener('input', (e) => setSplit(Number(e.target.value)));

  // 直接在图上拖动分割线，比只能拖滑块顺手
  const cmp = document.querySelector('.compare');
  let dragging = false;
  const pos = (e) => {
    const r = cmp.getBoundingClientRect();
    setSplit(((e.clientX - r.left) / r.width) * 100);
  };
  cmp.addEventListener('pointerdown', (e) => {
    dragging = true;
    cmp.setPointerCapture(e.pointerId);
    pos(e);
  });
  cmp.addEventListener('pointermove', (e) => { if (dragging) pos(e); });
  cmp.addEventListener('pointerup', () => { dragging = false; });
  cmp.addEventListener('pointercancel', () => { dragging = false; });

  window.addEventListener('beforeunload', (e) => {
    if (S.run || S.zip) { e.preventDefault(); e.returnValue = ''; }
  });
}

/* ------------------------------------------------------------ 启动 */

async function boot() {
  loadPrefs();
  applyTheme();
  loadLLM();
  bindPrefs();
  bindLLM();
  updateLLMStatus();
  bindEvents();
  renderList();
  await loadMeta();
  setInterval(loadMeta, 60000);
}

boot();
