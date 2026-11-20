import { displayText } from './workspace-text.js';

// Deliberately render a small Markdown subset with DOM nodes, never model HTML.
function inline(parent, value) {
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g;
  let offset = 0;
  for (const match of value.matchAll(pattern)) {
    parent.append(document.createTextNode(value.slice(offset, match.index)));
    const token = match[0];
    let node;
    if (token.startsWith('`')) { node = document.createElement('code'); node.textContent = token.slice(1, -1); }
    else if (token.startsWith('**')) { node = document.createElement('strong'); node.textContent = token.slice(2, -2); }
    else {
      const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      try {
        const url = new URL(parts[2]);
        if (!['https:', 'http:'].includes(url.protocol)) throw Error('Unsupported link');
        node = document.createElement('a'); node.href = url.href; node.rel = 'noopener noreferrer'; node.target = '_blank'; node.textContent = parts[1];
      } catch { node = document.createTextNode(token); }
    }
    parent.append(node); offset = match.index + token.length;
  }
  parent.append(document.createTextNode(value.slice(offset)));
}

export function renderMessageText(root, value, formatted = true) {
  const text = displayText(value);
  root.replaceChildren();
  if (!formatted) { root.textContent = text; return; }
  const lines = text.split('\n');
  let paragraph = [], list = null;
  const flush = () => {
    if (paragraph.length) { const p = document.createElement('p'); inline(p, paragraph.join('\n')); root.append(p); paragraph = []; }
    list = null;
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush(); const language = line.trim().slice(3).trim(); const codeLines = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) codeLines.push(lines[i]);
      const pre = document.createElement('pre'), code = document.createElement('code');
      code.textContent = codeLines.join('\n'); pre.append(code);
      if (language) pre.setAttribute('aria-label', language + ' code'); root.append(pre); continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    const item = /^\s*(?:([-*])|\d+\.)\s+(.+)$/.exec(line);
    if (heading) { flush(); const h = document.createElement('h' + Math.min(heading[1].length + 1, 6)); inline(h, heading[2]); root.append(h); }
    else if (item) {
      const tag = item[1] ? 'UL' : 'OL';
      if (!list || list.tagName !== tag) { flush(); list = document.createElement(tag); root.append(list); }
      const li = document.createElement('li'); inline(li, item[2]); list.append(li);
    } else if (!line.trim()) flush();
    else if (/^>\s?/.test(line)) { flush(); const quote = document.createElement('blockquote'); inline(quote, line.replace(/^>\s?/, '')); root.append(quote); }
    else { if (list) flush(); paragraph.push(line); }
  }
  flush();
}
