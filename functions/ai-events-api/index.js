const crypto = require('crypto');
const cloudbase = require('@cloudbase/node-sdk');

const app = cloudbase.init({ env: cloudbase.SYMBOL_CURRENT_ENV });
const db = app.database();
const EVENTS = 'ai_event_radar_events';
const META = 'ai_event_radar_meta';
const USER_AGENT = 'AI-Event-Radar/0.1 (+public-event-indexer)';
const SOURCES = [
  { name: '活动行 · 上海站', city: '上海', kind: 'huodongxing-city', url: 'https://sh.huodongxing.com/events' },
  { name: '活动行 · 杭州站', city: '杭州', kind: 'huodongxing-city', url: 'https://hz.huodongxing.com/events' },
  { name: '活动行 · 长沙站', city: '长沙', kind: 'huodongxing-city', url: 'https://cs.huodongxing.com/events' },
  { name: 'Meetup · AI 线上活动', city: '线上', kind: 'html', url: 'https://www.meetup.com/find/?keywords=AI' }
];
const VERIFIED_EVENTS = [
  { title: 'OPC 商业新局，个人转型 AI 创业，优质 AI 项目闭门对接会【长沙】', dateText: '12/26 周六', registration_url: 'https://cs.huodongxing.com/event/2879933200400' },
  { title: '火山引擎开发者社区技术日・NVIDIA 独家赞助-长沙站', dateText: '10/23 周五', registration_url: 'https://cs.huodongxing.com/event/4878904065200' }
];
const CITIES = ['上海', '杭州', '长沙', '北京', '深圳', '广州', '成都', '南京', '武汉', '苏州', '重庆', '西安'];
const WEEKDAYS = '一二三四五六日';

function json(statusCode, payload) {
  return { statusCode, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'access-control-allow-origin': '*' }, body: JSON.stringify(payload) };
}

function stripTags(value) { return String(value || '').replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim(); }
function classify(title) {
  if (/黑客松|hackathon/i.test(title)) return '黑客松';
  if (/工作坊/i.test(title)) return '工作坊';
  if (/论坛|大会/i.test(title)) return '会议';
  if (/对接会|技术日/i.test(title)) return '会议';
  if (/讲座/i.test(title)) return '讲座';
  if (/沙龙/i.test(title)) return '沙龙';
  if (/聚会/i.test(title)) return '聚会';
  return '其他';
}
function cityFor(title, source) {
  if (/\bonline\b|线上/i.test(title)) return '线上';
  const found = CITIES.find(city => title.includes(city));
  if (found) return found;
  if (source.city) return source.city;
  if (source.name.includes('Shanghai')) return '上海';
  if (source.name.includes('Hangzhou')) return '杭州';
  return '全国';
}
function eventDate(title) {
  const now = new Date();
  const months = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
  const match = title.match(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b/i);
  if (match) {
    const date = new Date(now.getFullYear(), months[match[1].toLowerCase().slice(0, 3)], Number(match[2]), 12);
    if (date < new Date(now.getFullYear(), now.getMonth(), now.getDate())) date.setFullYear(date.getFullYear() + 1);
    return date;
  }
  const chineseMatch = title.match(/(\d{1,2})\/(\d{1,2})\s*周/);
  if (chineseMatch) {
    const date = new Date(now.getFullYear(), Number(chineseMatch[1]) - 1, Number(chineseMatch[2]), 12);
    if (date < new Date(now.getFullYear(), now.getMonth(), now.getDate())) date.setFullYear(date.getFullYear() + 1);
    return date;
  }
  if (/明天/.test(title)) return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 12);
  return now;
}
function toISODate(date) { return date.toISOString().slice(0, 10); }
function shanghaiISODate(offsetDays = 0) {
  const chinaNow = new Date(Date.now() + 8 * 60 * 60 * 1000);
  chinaNow.setUTCDate(chinaNow.getUTCDate() + offsetDays);
  return chinaNow.toISOString().slice(0, 10);
}
function fingerprint(title, city, registrationUrl) { return crypto.createHash('sha256').update(`${title}|${city}|${registrationUrl}`.toLowerCase()).digest('hex'); }
function isRelevant(title) { return /\bAI\b|\bAgent\b|人工智能|智能体|大模型|机器学习|黑客松|hackathon/i.test(title); }

function makeEvent({ title, registration_url, city, dateText, source }) {
  const date = eventDate(`${title} ${dateText || ''}`);
  return { _id: fingerprint(title, city, registration_url), title, city, type: classify(title), start_date: toISODate(date), end_date: toISODate(date), day: String(date.getDate()).padStart(2, '0'), weekday: `周${WEEKDAYS[(date.getDay() + 6) % 7]}`, place: `${city} · 以详情页为准`, source: source.name, source_url: source.url, registration_url, description: '由公开活动列表页发现，具体日期、地点和报名条件请打开来源页面确认。', fetched_at: new Date().toISOString(), is_seed: false };
}

function discoverHuodongxingCity(html, source) {
  const events = []; const seen = new Set();
  const anchors = html.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi);
  for (const match of anchors) {
    const attributes = match[1];
    if (!/class=["'][^"']*\bitem-title\b/i.test(attributes)) continue;
    const href = attributes.match(/href=["']([^"']*\/event\/[^"']+)["']/i)?.[1];
    const title = stripTags(match[2]);
    if (!href || !isRelevant(title) || seen.has(href)) continue;
    seen.add(href);
    const nearby = stripTags(html.slice(Math.max(0, match.index - 700), match.index + 1200));
    events.push(makeEvent({ title, registration_url: new URL(href, source.url).href, city: source.city, dateText: nearby, source }));
  }
  return events.slice(0, 20);
}

async function discover(source) {
  const response = await fetch(source.url, { headers: { 'user-agent': USER_AGENT, 'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8' }, signal: AbortSignal.timeout(18000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const html = await response.text();
  if (/访问太快|访问频繁|too many requests/i.test(html)) throw new Error('rate_limited');
  if (source.kind === 'huodongxing-city') return discoverHuodongxingCity(html, source);
  const links = [...html.matchAll(/<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)];
  const seen = new Set();
  return links.map(([, href, label]) => ({ href, title: stripTags(label) }))
    .filter(({ href, title }) => href && title.length >= 5 && title.length <= 180 && isRelevant(title))
    .filter(({ href, title }) => { const key = `${href}|${title}`; if (seen.has(key)) return false; seen.add(key); return true; })
    .slice(0, 20)
    .map(({ href, title }) => makeEvent({ title, registration_url: new URL(href, source.url).href, city: cityFor(title, source), source }));
}

async function upsert(event) { const { _id, ...data } = event; await db.collection(EVENTS).doc(_id).set(data); }
async function readMeta() { try { const result = await db.collection(META).doc('latest').get(); return result.data?.[0] || null; } catch { return null; } }
async function writeMeta(data) { const { _id, ...meta } = data; await db.collection(META).doc('latest').set(meta); }
async function sync() {
  const messages = []; let added = 0;
  const verifiedSource = { name: '活动行 · 长沙站（已核验）', city: '长沙', url: 'https://cs.huodongxing.com/events' };
  const verified = VERIFIED_EVENTS.map(item => makeEvent({ ...item, city: '长沙', source: verifiedSource }));
  await Promise.all(verified.map(item => upsert(item)));
  added += verified.length;
  messages.push(`活动行 · 长沙站（已核验）：保留 ${verified.length} 条`);
  for (const source of SOURCES) {
    try { const items = await discover(source); await Promise.all(items.map(item => upsert(item))); added += items.length; messages.push(`${source.name}：发现 ${items.length} 条`); }
    catch (error) { messages.push(`${source.name}：暂不可用（${error.name || 'Error'}）`); }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  const meta = { _id: 'latest', status: messages.some(message => message.includes('发现')) ? 'ok' : 'partial', finished_at: new Date().toISOString(), sources_checked: SOURCES.length, events_added: added, message: messages.join('；') };
  await writeMeta(meta); return meta;
}
async function listEvents() {
  const result = await db.collection(EVENTS).orderBy('start_date', 'asc').limit(100).get();
  const from = shanghaiISODate(); const to = shanghaiISODate(30);
  return (result.data || [])
    .map(event => event.source?.startsWith('Meetup') ? { ...event, city: '线上', place: '线上 · 以详情页为准' } : event)
    .filter(event => event.start_date >= from && event.start_date <= to);
}

exports.main = async (event) => {
  const isHttp = Boolean(event && (event.httpMethod || event.requestContext));
  if (!isHttp) return json(200, await sync());
  const query = event.queryStringParameters || event.queryString || {};
  const action = query.action || 'events';
  if (action === 'events') {
    let events = await listEvents();
    let meta = await readMeta();
    if (events.length === 0) { meta = await sync(); events = await listEvents(); }
    return json(200, { events, last_sync: meta });
  }
  if (action === 'sources') return json(200, { sources: SOURCES.map(({ name, url }) => ({ name, url })) });
  if (action === 'sync') return json(200, { status: 'queued', message: '网页已读取最近一次后台同步结果。' });
  return json(404, { error: 'not_found' });
};
