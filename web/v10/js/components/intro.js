// انميشن الدخول الذي يضعه المالك — يعمل داخل صندوق معزول تماماً عن الموقع
export function play(code, secs, preview) {
  return new Promise(resolve => {
    document.getElementById('introFx')?.remove();
    const wrap = document.createElement('div'); wrap.id = 'introFx';
    const csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:";
    const fr = document.createElement('iframe');
    fr.setAttribute('sandbox', 'allow-scripts');
    fr.setAttribute('title', 'انميشن الدخول');
    fr.srcdoc = '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + csp + '"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;height:100%;overflow:hidden;background:transparent}</style></head><body>' + code + '</body></html>';
    const skip = document.createElement('button'); skip.type = 'button'; skip.className = 'btn blur skip'; skip.textContent = preview ? 'إغلاق المعاينة' : 'تخطي';
    wrap.append(fr, skip); document.body.appendChild(wrap);
    let done = false;
    const onMsg = e => { if (e.source === fr.contentWindow && e.data === 'rl:done') finish(); };
    const tm = setTimeout(finish, Math.max(1, +secs || 3) * 1000);
    function finish() { if (done) return; done = true; removeEventListener('message', onMsg); clearTimeout(tm); wrap.classList.add('out'); setTimeout(() => { wrap.remove(); resolve(); }, 500); }
    addEventListener('message', onMsg);
    skip.onclick = finish;
  });
}
