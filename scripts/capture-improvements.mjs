import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
const require = createRequire(process.env.LOOPDESK_BROWSER_PACKAGE || import.meta.url);
const { chromium } = require('playwright');
const phase = process.argv[2];
if (!['before','after'].includes(phase)) throw new Error('Use before or after');
const browser = await chromium.launch({headless:true});
const page = await browser.newPage();
const base = process.env.LOOPDESK_URL || 'http://127.0.0.1:5055';
await fs.mkdir('artifacts', {recursive:true});
async function capture(name, route) {
  await page.goto(base + route);
  for (const [width,height] of [[1440,900],[390,844]]) {
    await page.setViewportSize({width,height});
    await page.screenshot({path:`artifacts/improvement-2026-10-27-${phase}-${name}-${width}.png`,fullPage:true});
  }
}
try {
  await capture('landing','/');
  await page.getByRole('button',{name:'Try demo'}).click();
  await page.goto(base+'/opportunities?view=list');
  const detail = new URL(await page.locator('tbody a').first().getAttribute('href'),base).pathname;
  const orgEdit = '/organisations/'+(await page.request.get(base+'/organisations').then(r=>r.text())).match(/\/organisations\/([^/]+)\/edit/)[1]+'/edit';
  const contactEdit = '/contacts/'+(await page.request.get(base+'/contacts').then(r=>r.text())).match(/\/contacts\/([^/]+)\/edit/)[1]+'/edit';
  const routes = {overview:'/dashboard',pipeline:'/opportunities',list:'/opportunities?view=list',organisations:'/organisations',contacts:'/contacts',followups:'/follow-ups',reports:'/reports',connection:'/integrations/followdesk','scope-import':'/scope-import',detail,
    'new-organisation':'/organisations/new','new-contact':'/contacts/new','new-opportunity':'/opportunities/new','edit-organisation':orgEdit,'edit-contact':contactEdit,'edit-opportunity':detail+'/edit','scope-history':detail+'/scopes',error:'/missing-page'};
  for (const [name,route] of Object.entries(routes)) await capture(name,route);
  await page.setViewportSize({width:1024,height:900});
  await page.goto(base+'/opportunities');
  await page.screenshot({path:`artifacts/improvement-2026-10-27-${phase}-pipeline-1024.png`,fullPage:true});
  if (phase === 'after') {
    // Additional states of the existing scope pages, using a fictional contract fixture.
    const canonical = value => JSON.stringify(value, function(key,current) {
      return current && !Array.isArray(current) && typeof current==='object'
        ? Object.fromEntries(Object.entries(current).sort(([a],[b])=>a.localeCompare(b,'en'))) : current;
    });
    const payload = {schema_version:1,source_system:'ScopeDesk',case_id:'capture-fictional-scope',revision:1,review_status:'Reviewed',reviewed_at:'2026-10-27T00:00:00+00:00',client_display_name:'Cedar Example',scope:[{kind:'equipment',item:'Laptop',site:'Dubai',quantity:12,outcome:'reuse',location:'',collection:'',source_refs:['S1:L1']}],assumptions:[],followups:[{text:'Confirm the collection window.',refs:['S1:L1']}],source_references:[{ref:'S1:L1',origin:'enquiry'}]};
    payload.digest=createHash('sha256').update(canonical(payload)).digest('hex');
    await page.goto(base+'/scope-import');
    await page.locator('input[type=file]').setInputFiles({name:'fictional-scope.json',mimeType:'application/json',buffer:Buffer.from(canonical(payload))});
    await page.getByRole('button',{name:'Preview scope import',exact:true}).click();
    const preview = new URL(page.url()).pathname;
    await capture('scope-preview',preview);
    await page.locator('#opportunity-organisation').selectOption({index:1});
    await page.locator('#opportunity-contact').selectOption({index:1});
    await page.getByRole('button',{name:'Confirm reviewed scope import'}).click();
    await capture('scope-history-populated',new URL(page.url()).pathname+'/scopes');
  }
} finally { await browser.close(); }
