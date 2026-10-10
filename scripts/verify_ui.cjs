// Headless visual/interaction QA. Credentials are read locally and never logged.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
async function main(){
 const credentials=JSON.parse(fs.readFileSync(path.join(process.env.AGENTGATE_DATA_DIR||'data','credentials.json'),'utf8'));
 const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
 const errors=[];
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8000');
 if(await page.getByText('First run?',{exact:false}).count())throw new Error('Removed setup note is still visible');
 await page.screenshot({path:'artifacts/login.png',fullPage:true});
 await page.locator('#token').fill(credentials.support.token);await page.getByRole('button',{name:'Connect to AgentGate'}).click();
 await page.locator('#app').waitFor({state:'visible'});
 await page.getByRole('button',{name:'Tool lab',exact:false}).click();
 await page.locator('#tool-name').selectOption('query_records');
 await page.locator('#tool-args').fill(JSON.stringify({dataset:'tickets',limit:5}));
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'allow'}).waitFor();
 await page.locator('#tool-args').fill(JSON.stringify({dataset:'payroll',limit:5}));
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'deny'}).waitFor();
 await page.locator('#tool-name').selectOption('export_report');
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'approval_required'}).waitFor();
 const ticket=await page.locator('#approval-id').inputValue();
 const adminContext=await browser.newContext(),admin=await adminContext.newPage();
 admin.on('pageerror',e=>errors.push(e.message));
 await admin.goto('http://127.0.0.1:8000');await admin.locator('#token').fill(credentials.admin.token);
 await admin.getByRole('button',{name:'Connect to AgentGate'}).click();await admin.locator('#app').waitFor({state:'visible'});
 await admin.getByRole('button',{name:'Approvals',exact:false}).click();
 const card=admin.locator('.list-card').filter({hasText:ticket});await card.getByRole('button',{name:'Approve',exact:true}).click();
 await card.getByRole('button',{name:'Approve',exact:true}).waitFor({state:'hidden'});
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'allow'}).waitFor();
 await page.getByRole('button',{name:'Download authorized CSV'}).waitFor();
 await page.screenshot({path:'artifacts/tool-lab.png',fullPage:true});
 await page.getByRole('button',{name:'Overview',exact:false}).click();
 await page.locator('#audit-empty').waitFor({state:'hidden'});
 await page.screenshot({path:'artifacts/dashboard.png',fullPage:true});
 await page.getByRole('button',{name:'Agent console',exact:false}).click();
 if(!process.argv.includes('--skip-model')){
 await page.locator('#prompt').fill('Use query_records to fetch 2 tickets and report their statuses.');
 await page.getByRole('button',{name:'Run task'}).click();
 await page.locator('.message.status').filter({hasText:'Completed in'}).waitFor({timeout:180000});
 await page.locator('#agent-decisions .decision-card').filter({hasText:'allow'}).waitFor();
 }
 await page.screenshot({path:process.argv.includes('--skip-model')?'artifacts/agent-console-layout.png':'artifacts/agent-console.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Overview',exact:false}).click();
 await page.screenshot({path:'artifacts/mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1))throw new Error('Mobile page overflows horizontally');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log('UI verified: login, allowed/denied tools, approval, CSV creation, audit rendering, desktop and mobile layouts. Live model: '+(process.argv.includes('--skip-model')?'not requested':'passed')+'.');
 await context.close();await adminContext.close();
 }finally{await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});

