/* 界面多语言（中 / 英）
 *
 * 设计取舍：页面文案大量内联在 app.js 拼的 HTML 里，逐个改成 t('…') 既容易漏、
 * 也容易改坏渲染逻辑。这里改成**渲染后翻译**：
 *   1. 精确词表 DICT（中文原文 → 英文，查找前把连续空白压成一个空格）
 *   2. 动态拼接用 PATTERNS（正则 → 替换）
 *   3. 混合节点按 · | 切段逐段翻（"1.36 KB · 图片 · PNG"）
 *   4. MutationObserver 监听新增节点与属性，innerHTML 重绘后自动再翻一遍
 * 切回中文时用记下的原文还原，不依赖二次翻译。
 */
'use strict';

const LANG_KEY = 'wm.lang';

const DICT = {
  /* ---------- 顶部 ---------- */
  '水印清理工具': 'Watermarks Remover',
  'C2PA · EXIF/XMP · 隐形字符': 'C2PA · EXIF/XMP · invisible chars',
  '连接中…': 'Connecting…',
  'AI 接口': 'AI',
  '引擎未连接': 'Engine offline',
  '引擎状态': 'Engine status',
  '切换深浅色': 'Toggle theme',
  '选 择或拖入文件': 'Choose or drop files',
  '选择或拖入文件': 'Choose or drop files',
  '清理全部未完成的文件': 'Clean every unfinished file',
  '正在处理': 'Working',

  /* ---------- 投放区 ---------- */
  '拖入文件，或点击选择': 'Drop files here, or click to choose',
  '也可以粘贴截图 · 支持整个文件夹': 'Paste a screenshot too · folders supported',
  '也可以粘贴截图': 'Paste a screenshot too',
  '支持整个文件夹': 'folders supported',
  '选择文件夹': 'Choose folder',
  '还没有文件。拖入、点击或粘贴都可以。': 'No files yet — drop, click or paste.',
  '拖拽到此处': 'Drop here',

  /* ---------- 工具栏 ---------- */
  '检测': 'Inspect',
  '清理': 'Clean',
  '打包下载': 'Download ZIP',
  '清空': 'Clear',
  '取消': 'Cancel',
  '关闭': 'Close',
  '保存': 'Save',
  '显示': 'Show',
  '隐藏': 'Hide',
  '对比': 'Compare',
  '重检': 'Re-check',
  '重新清理': 'Re-clean',
  '移除': 'Remove',
  '下载': 'Download',
  '详情': 'Details',
  '对比分割线': 'Compare divider',

  /* ---------- 状态 ---------- */
  '待处理': 'Pending',
  '处理中': 'Working',
  '处理中…': 'Working…',
  '失败': 'Failed',
  '已清理': 'Cleaned',
  '已清理 · 复检通过': 'Cleaned · verified',
  '复检有残留': 'Residue left',
  '未见标记': 'No marks found',
  '检出': 'Detected',
  '已确认': 'confirmed',
  '可能': 'likely',
  '提示': 'info',
  '读取中…': 'Reading…',
  '正在取消…': 'Cancelling…',
  '正在清理': 'Cleaning',
  '正在检测': 'Inspecting',
  '正在打包': 'Building ZIP',
  '打包中…': 'Building…',

  /* ---------- 统计条 ---------- */
  '个文件': 'files',
  '有标记': 'flagged',
  '已清理，输出': 'cleaned, output',
  '输出': 'output',
  '个': 'files',

  /* ---------- 类型 ---------- */
  '图片': 'Image',
  '音视频': 'Audio/Video',
  '文档': 'Document',
  '文本': 'Text',
  '未知': 'Unknown',
  '图片 / 音视频': 'Images / A-V',
  '文本与文档': 'Text & documents',
  '文档（PDF / Office / EPUB）': 'Documents (PDF / Office / EPUB)',
  '服务能力': 'Capabilities',
  '范围': 'Scope',
  '可用': 'available',
  '未部署': 'not deployed',

  /* ---------- 选项面板 ---------- */
  '元数据剥离': 'Metadata',
  '全部剥离（推荐）': 'Strip everything (recommended)',
  '仅剥离 AI 标记，保留相机参数': 'AI marks only, keep camera data',
  '音频水印破坏性重编码': 'Destructive audio re-encode',
  '变速 1.08× + 升调 2 半音 + EQ，会损失音质，输出转 M4A':
    'Tempo 1.08× + pitch +2 semitones + EQ; lossy, output becomes M4A',
  '内嵌图片深度清理': 'Deep-clean embedded images',
  '自动（需要时才重蒸馏）': 'Auto (re-distil when needed)',
  '始终重蒸馏': 'Always re-distil',
  '仅无损模式': 'Lossless only',
  '跳过': 'Skip',
  '文档内文本也做隐形字符清理': 'Clean invisible chars inside documents',
  '关闭只剥元数据，正文原样保留': 'Off = strip metadata only, body untouched',
  '归一化': 'Normalisation',
  '异体空格转普通空格': 'Odd spaces → ASCII space',
  '不换行空格、窄空格 → 普通空格': 'NBSP / thin space → plain space',
  'NFKC 兼容归一化': 'NFKC normalisation',
  '全角字母数字转半角，会改动正文': 'Full-width → half-width; alters the text',
  '同形字归正': 'Homoglyph folding',
  '西里尔/希腊字母转 ASCII，可能误伤俄语正文': 'Cyrillic/Greek → ASCII; may hurt Russian text',
  '激进模式（谨慎）': 'Aggressive (careful)',
  '剥离承载型不可见字符': 'Strip carrier invisible chars',
  '会破坏 emoji、国旗、阿拉伯语连写': 'Breaks emoji, flags, Arabic joining',
  '剥离双向控制符': 'Strip bidi controls',
  '会破坏阿拉伯语 / 希伯来语排版': 'Breaks Arabic / Hebrew layout',
  '恢复默认选项': 'Restore defaults',

  /* ---------- 能力卡片 ---------- */
  'AI 文本重写': 'AI text rewriting',
  '文本水印检测': 'Text-watermark detection',
  '像素级去水印': 'Pixel-level cleaning',
  '未配置': 'Not configured',
  '引擎已配置': 'Configured in engine',
  '修改': 'Change',
  '引擎未连接，以下能力不可用。': 'Engine offline — these are unavailable.',
  '像素级隐形水印（SynthID、Tree-Ring）需要额外 ML 模型，AI 文本的统计水印需要大模型重写后端，本地均未部署。':
    'Pixel-level watermarks (SynthID, Tree-Ring) need extra ML models, and statistical text ' +
    'watermarks need a rewrite backend — neither ships with this image.',
  '检测到 Content Credentials 清单': 'Content Credentials manifest detected',
  '不做：': " Doesn't: ",
  '做什么：': 'Does: ',

  /* ---------- 页脚说明 ---------- */
  '剥离 C2PA / Content Credentials、EXIF / XMP、生成器标记（Midjourney、SD、ComfyUI 等）， 清除文本里的零宽字符、双向控制符与同形字。':
    'Strips C2PA / Content Credentials, EXIF / XMP and generator metadata (Midjourney, SD, ' +
    'ComfyUI …), and removes zero-width characters, bidi controls and homoglyphs from text.',

  /* ---------- 详情面板 ---------- */
  '清理前检出': 'Detected before',
  '复检': 'Verification',
  '体积': 'Size',
  '仍有：': 'Still present:',
  '未发现 C2PA、AI 元数据或隐藏字符': 'No C2PA, AI metadata or hidden characters',
  'C2PA 清单': 'C2PA manifest',
  'AI 元数据': 'AI metadata',
  '大文件未自动复检，可点「重检」对输出再做一次检测':
    'Large file — not auto-verified. Use "Re-check" on the output.',
  '仅 Layer A：隐形字符清理，未做 AI 文本重写':
    'Layer A only: invisible characters, no AI rewrite',
  '错误': 'Error',
  '处理': 'Actions',

  /* ---------- 对比弹窗 ---------- */
  '清理前': 'Before',
  '清理后': 'After',
  '拖动分割线': 'Drag the divider',

  /* ---------- AI 设置弹窗 ---------- */
  'AI 接口设置（可选）': 'AI settings (optional)',
  'AI 接口设置（可选，用于文本 Layer B 改写）': 'AI settings (optional, used for Layer B text rewriting)',
  '启用 AI 文本改写（Layer B）': 'Enable AI text rewriting (Layer B)',
  '不勾选不影响任何其它功能': "Leaving it off doesn't affect anything else",
  '对纯文本 / Markdown / HTML / SVG 做模型改写，用来抹掉 AI 文本的统计水印。':
    'Rewrites plain text / Markdown / HTML / SVG with a model to remove statistical text watermarks.',
  '服务商': 'Provider',
  '模型': 'Model',
  '协议': 'Protocol',
  'OpenAI 兼容（绝大多数服务商）': 'OpenAI-compatible (most providers)',
  'Ollama 原生（/api/chat）': 'Ollama native (/api/chat)',
  '密钥只保存在这台机器的浏览器里': 'The key lives only in this browser',
  '密钥只保存在这台机器的浏览器里，': 'The key lives only in this browser,',
  '不会写进容器、不会落到服务端': 'never written to the container or the server',
  '；每次请求随头部带过去。': '; sent per request in a header.',
  '记住密钥（只存在这台机器的浏览器里）': 'Remember the key (this browser only)',
  '用云端服务商时，': 'With a cloud provider,',
  '被改写的正文会发送给对方': 'the rewritten text is sent to them',
  '；介意的话就把 Base URL 指向本地模型。': '; point the Base URL at a local model if that matters.',
  '改写策略': 'Strategy',
  '自定义改写策略': 'Custom rewrite strategy',
  '自定义：战术@强度,战术@强度': 'Custom: tactic@strength,tactic@strength',
  '策略来自上游引擎：': 'Strategies come from the engine:',
  '换词改写': 'rewording',
  '去 AI 腔': 'de-AI tone',
  '结构重排': 'restructure',
  '回译（最彻底、最慢、也最贵）': 'back-translation (most thorough, slowest, priciest)',
  '回译（最彻底 / 最慢 / 最贵）': 'back-translation (most thorough / slowest / priciest)',
  '改注释与标识符。强度 0–1，越大改得越多。': 'comments/identifiers only. Strength 0–1, higher rewrites more.',
  '需要 transformers，本镜像没装。': 'needs transformers — not installed in this image.',
  '轻度改写（保守）': 'Light (conservative)',
  '标准改写': 'Standard',
  '彻底改写': 'Thorough',
  '改写 + 去 AI 腔': 'Rewrite + de-AI tone',
  '自定义': 'Custom',
  '超时（秒）': 'Timeout (s)',
  '温度': 'Temperature',
  '目标语言': 'Target language',
  '中间语言（回译用）': 'Pivot language (for back-translation)',
  '测试连接': 'Test connection',
  '清除配置': 'Clear settings',
  '正在测试…': 'Testing…',
  '先填 Base URL 和模型名。': 'Fill in the Base URL and model first.',
  '已启用，但 Base URL 或模型名还没填。': 'Enabled, but the Base URL or model is still empty.',
  '未启用。其余功能（元数据剥离、隐形字符清理）不受影响。':
    'Disabled. Metadata stripping and invisible-character cleaning still work.',
  '——元数据剥离、隐形字符清理照常工作。':
    '— metadata stripping and invisible-character cleaning still work.',
  '未知错误': 'unknown error',
  '未配置。配置后文本类文件会额外走一次模型改写。':
    'Not configured. Once set, text files get an extra model pass.',
  '任何提供 /v1/chat/completions 的服务都可以。':
    'Anything that serves /v1/chat/completions works.',
  '本地模型可留空': 'optional for local models',

  /* ---------- 服务商提示语 ---------- */
  '官方接口，需要 API Key。': 'Official endpoint; needs an API key.',
  '国内直连便宜；reasoner 系列会先思考再回答，慢但更稳。':
    'Cheap and direct from mainland China; reasoner models think first — slower but steadier.',
  '长文本友好，适合长文档改写。': 'Good with long text; suits long documents.',
  '注意 base 已含 /v4，路径会自动补全。': 'The base already ends in /v4 — the path is completed for you.',
  'DashScope 的 OpenAI 兼容模式。': "DashScope's OpenAI-compatible mode.",
  '腾讯云 OpenAI 兼容端点。': "Tencent Cloud's OpenAI-compatible endpoint.",
  '星火开放平台。': 'iFlytek Spark open platform.',
  '千帆 v2 兼容端点。': 'Qianfan v2 compatible endpoint.',
  '聚合平台，模型多。': 'Aggregator — lots of models.',
  '一个 Key 调多家模型。': 'One key, many providers.',
  '推理速度极快。': 'Very fast inference.',
  'xAI 官方。': 'Official xAI endpoint.',
  '走 Anthropic 的 OpenAI 兼容端点。': "Anthropic's OpenAI-compatible endpoint.",
  'Gemini 的 OpenAI 兼容层，base 以 /openai 结尾。':
    "Gemini's OpenAI-compatible layer; the base ends in /openai.",
  '本地模型不出网。容器解析不了 host.docker.internal 时会自动改用 Docker 网关地址；若 Ollama 只监听 127.0.0.1，用 llm-relay.py 在 WSL 里桥一道。':
    'Local models never leave your machine. If the container cannot resolve host.docker.internal it ' +
    'falls back to the Docker gateway; if Ollama only listens on 127.0.0.1, bridge it with ' +
    'llm-relay.py inside WSL.',
  '容器与 Windows 主机不共享 loopback，通常到不了 Windows 上的 LM Studio。本地跑请把模型服务装进 WSL/Linux，或直接用云端 API。':
    'The container does not share loopback with the Windows host, so LM Studio there is usually ' +
    'unreachable. Run the model server inside WSL/Linux, or use a cloud API.',
  '任何提供 /v1/chat/completions 的服务都可以。':
    'Anything that serves /v1/chat/completions works.',

  '／策略': ' / strategy',

  /* ---------- 服务商 ---------- */
  'DeepSeek 深度求索': 'DeepSeek',
  '月之暗面 Kimi': 'Moonshot Kimi',
  '智谱 GLM': 'Zhipu GLM',
  '阿里云百炼 Qwen': 'Alibaba DashScope Qwen',
  '腾讯混元': 'Tencent Hunyuan',
  '讯飞星火': 'iFlytek Spark',
  '百度千帆': 'Baidu Qianfan',
  '硅基流动 SiliconFlow': 'SiliconFlow',
  'Ollama（本地，需装在 WSL）': 'Ollama (local, install in WSL)',
  'LM Studio（装在 Windows 主机上）': 'LM Studio (on a Windows host)',
  '自定义（OpenAI 兼容）': 'Custom (OpenAI-compatible)',
};

/* 动态拼接：顺序敏感，先具体后宽泛 */
const PATTERNS = [
  [/^(图片|文档|文本|音视频)：(.+)$/, (m) =>
    ({ 图片: 'Image', 文档: 'Document', 文本: 'Text', 音视频: 'A/V' }[m[1]] + ': ' + m[2])],
  [/^引擎 (.+) · 界面 (.+)$/, (m) => `Engine ${m[1]} · UI ${m[2]}`],
  [/^检出 (\d+) 项$/, (m) => `Detected ${m[1]}`],
  [/^复检有残留 (\d+)$/, (m) => `Residue: ${m[1]}`],
  [/^详情 · (\d+)$/, (m) => `Details · ${m[1]}`],
  [/^清理完成：(\d+) 个文件$/, (m) => `Cleaned ${m[1]} file(s)`],
  [/^检测完成：(\d+) 个文件$/, (m) => `Inspected ${m[1]} file(s)`],
  [/^完成 (\d+) 个，失败 (\d+) 个$/, (m) => `${m[1]} done, ${m[2]} failed`],
  [/^已取消（完成 (\d+) 个）$/, (m) => `Cancelled (${m[1]} done)`],
  [/^已打包 (\d+) 个文件（(.+?)）$/, (m) => `ZIP ready: ${m[1]} file(s) (${m[2]})`],
  [/^打包总量 (.+?) 超过 4 GB，请分批下载（ZIP 不支持 zip64）$/,
    (m) => `Total ${m[1]} exceeds 4 GB — download in batches (no zip64)`],
  [/^打包失败：(.+)$/, (m) => `ZIP failed: ${m[1]}`],
  [/^一次最多 (\d+) 个文件$/, (m) => `At most ${m[1]} files at a time`],
  [/^(.+?) 超过单文件上限 (.+)$/, (m) => `${m[1]} exceeds the per-file limit ${m[2]}`],
  [/^跳过 (\d+) 个无法处理的文件：(.+)$/, (m) => `Skipped ${m[1]} unsupported file(s): ${m[2]}`],
  [/^忽略 (\d+) 个重复文件$/, (m) => `Skipped ${m[1]} duplicate(s)`],
  [/^已粘贴 (\d+) 个文件$/, (m) => `Pasted ${m[1]} file(s)`],
  [/^已添加 (\d+) 个文件$/, (m) => `Added ${m[1]} file(s)`],
  [/^AI 接口已保存：(.+)$/, (m) => `AI settings saved: ${m[1]}`],
  [/^AI 接口已停用$/, () => 'AI disabled'],
  [/^连接失败：(.+)$/, (m) => `Connection failed: ${m[1]}`],
  [/^连接正常：(.+)$/, (m) => `Connected: ${m[1]}`],
  [/^已启用：(.+)$/, (m) => `Enabled: ${m[1]}`],
  [/^引擎 ([\d.]+)$/, (m) => `Engine ${m[1]}`],
  [/^，输出 (.+)$/, (m) => `, output ${m[1]}`],
  [/^仍有：(.*)$/, (m) => `Still present:${m[1]}`],
  [/^个$/, () => 'files'],
  [/^个文件 ·$/, () => 'files ·'],
  [/^ (.+) 个文件$/, (m) => ` ${m[1]} file(s)`],
];

const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'CODE', 'PRE']);

let LANG = 'zh';
let applying = false;

function pickLang() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === 'en' || saved === 'zh') return saved;
  } catch { /* 隐私模式 */ }
  return ((navigator.language || 'zh').toLowerCase().startsWith('zh')) ? 'zh' : 'en';
}

const norm = (s) => s.replace(/\s+/g, ' ').trim();
const nospace = (s) => s.replace(/\s+/g, '');

// HTML 里长段落的换行/缩进会让 norm 后的键和词表差一个空格，
// 所以再建一份「去掉所有空白」的索引兜底
const DICT_NOSPACE = (() => {
  const m = new Map();
  for (const [k, v] of Object.entries(DICT)) m.set(nospace(k), v);
  return m;
})();

/** 单段文字查表：先精确、再模式 */
function lookup(text) {
  const key = norm(text);
  if (!key) return null;
  if (Object.prototype.hasOwnProperty.call(DICT, key)) return DICT[key];
  const loose = DICT_NOSPACE.get(nospace(key));
  if (loose) return loose;
  for (const [re, fn] of PATTERNS) {
    const m = key.match(re);
    if (m) return fn(m);
  }
  return null;
}

/** 整段翻译：整句优先，不行就按 · | 切段逐段翻 */
function translate(raw) {
  if (!raw || !/[\u4e00-\u9fff]/.test(raw)) return null;
  const whole = lookup(raw);
  if (whole != null) return whole;
  const parts = raw.split(/(\s+·\s+|\s*[|｜]\s*|·|\n+)/);
  let changed = false;
  const out = parts.map((p) => {
    if (!/[\u4e00-\u9fff]/.test(p)) return p;
    const seg = lookup(p);
    if (seg == null) return p;
    changed = true;
    return p.replace(p.trim(), seg);
  });
  return changed ? out.join('') : null;
}

const hasCJK = (s) => /[一-鿿]/.test(s || '');

function applyLangTo(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const parent = node.parentNode;
    if (!parent || SKIP_TAGS.has(parent.nodeName)) return;
    const cur = node.nodeValue;
    if (LANG === 'en') {
      // 每次看到中文就更新原文记录：文本节点可能被 textContent 就地改写，
      // 只认第一次记下的原文会永远翻译旧内容
      if (hasCJK(cur)) {
        node.__zhText = cur;
        const hit = translate(cur);
        if (hit != null) {
          const lead = cur.match(/^\s*/)[0];
          const tail = cur.match(/\s*$/)[0];
          node.nodeValue = lead + hit + tail;
        }
      }
    } else if (node.__zhText !== undefined && cur !== node.__zhText) {
      node.nodeValue = node.__zhText;
    }
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  for (const attr of ATTRS) {
    if (!node.hasAttribute || !node.hasAttribute(attr)) continue;
    const key = '__zh_' + attr;
    const cur = node.getAttribute(attr) || '';
    if (LANG === 'en') {
      if (hasCJK(cur)) {           // 动态改过的 title / placeholder 也要跟得上
        node[key] = cur;
        const hit = translate(cur);
        if (hit != null && hit !== cur) node.setAttribute(attr, hit);
      }
    } else if (node[key] !== undefined && cur !== node[key]) {
      node.setAttribute(attr, node[key]);
    }
  }
  for (const child of node.childNodes) applyLangTo(child);
}

function setLang(lang, persist = true) {
  LANG = lang === 'en' ? 'en' : 'zh';
  if (persist) {
    try { localStorage.setItem(LANG_KEY, LANG); } catch { /* 隐私模式 */ }
  }
  document.documentElement.lang = LANG === 'en' ? 'en' : 'zh-CN';
  applying = true;
  applyLangTo(document.body || document.documentElement);
  if (LANG === 'en') {
    const hit = translate(document.__zhTitle || document.title);
    if (hit) {
      if (document.__zhTitle === undefined) document.__zhTitle = document.title;
      document.title = hit;
    }
  } else if (document.__zhTitle) {
    document.title = document.__zhTitle;
  }
  applying = false;
  for (const btn of document.querySelectorAll('[data-lang-btn]')) {
    btn.textContent = LANG === 'en' ? '中文' : 'EN';
    // 按钮上写的是「点了会切到什么」，提示也跟着一致
    btn.title = LANG === 'en' ? 'Switch to Chinese' : '切换到英文';
    btn.setAttribute('aria-label', btn.title);
  }
  // 让页面逻辑重绘那些自己拼过字符串的地方（统计条、能力卡片…）
  document.dispatchEvent(new CustomEvent('wm:lang', { detail: { lang: LANG } }));
}

function watchDynamic() {
  const obs = new MutationObserver((records) => {
    if (applying || LANG !== 'en') return;
    applying = true;
    try {
      for (const rec of records) {
        if (rec.type === 'attributes') {
          applyLangTo(rec.target);
          continue;
        }
        for (const node of rec.addedNodes) applyLangTo(node);
      }
    } finally {
      applying = false;
    }
  });
  obs.observe(document.body, {
    childList: true, subtree: true, attributes: true, attributeFilter: ATTRS,
  });
}

function initI18n() {
  setLang(pickLang(), false);
  watchDynamic();
  for (const btn of document.querySelectorAll('[data-lang-btn]')) {
    btn.addEventListener('click', () => setLang(LANG === 'en' ? 'zh' : 'en'));
  }
}

function applyNow() {
  const wasApplying = applying;
  applying = true;
  try {
    applyLangTo(document.body || document.documentElement);
  } finally {
    applying = wasApplying;
  }
}

window.WM_I18N = {
  setLang, applyNow,
  get lang() { return LANG; },
  t: translate,
  isEn: () => LANG === 'en',
};

if (document.body) initI18n();
else document.addEventListener('DOMContentLoaded', initI18n, { once: true });
