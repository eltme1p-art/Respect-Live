// إشعارات المتصفح (Web Push)
import { S, api, post } from './api.js?v=__BUILD__';
import { toast, ok, bad } from './ui.js?v=__BUILD__';

export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const b64 = s => { s = s.replace(/-/g, '+').replace(/_/g, '/'); s += '='.repeat((4 - s.length % 4) % 4); const r = atob(s); return Uint8Array.from(r, c => c.charCodeAt(0)); };

export async function pushStatus() {
  if (!pushSupported()) return false;
  try { const reg = await navigator.serviceWorker.ready; S.pushOn = !!(await reg.pushManager.getSubscription()); } catch (e) { S.pushOn = false; }
  return S.pushOn;
}
export async function enablePush() {
  if (!pushSupported()) { toast(/iphone|ipad/i.test(navigator.userAgent) ? 'على آيفون: ثبّت الموقع على الشاشة الرئيسية أولاً ثم فعّل الإشعارات' : 'المتصفح لا يدعم الإشعارات', 'bad'); return false; }
  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { toast('لم تسمح بالإشعارات — فعّلها من إعدادات المتصفح', 'bad'); return false; }
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api('/api/push/key');
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
    await post('/api/push/subscribe', sub.toJSON());
    S.pushOn = true; ok('فعّلنا الإشعارات على هذا الجهاز'); return true;
  } catch (e) { bad(e); return false; }
}
export async function disablePush() {
  try {
    const reg = await navigator.serviceWorker.ready; const sub = await reg.pushManager.getSubscription();
    if (sub) { await post('/api/push/unsubscribe', { endpoint: sub.endpoint }); await sub.unsubscribe(); }
    S.pushOn = false; ok('أوقفنا الإشعارات على هذا الجهاز'); return true;
  } catch (e) { bad(e); return false; }
}
export async function testPush() { try { await post('/api/push/test'); ok('أرسلنا إشعاراً تجريبياً'); } catch (e) { bad(e); } }
