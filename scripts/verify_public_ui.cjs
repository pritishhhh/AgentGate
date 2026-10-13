// Public visitor QA reads only the intentionally published demo token.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
async function main(){
 const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
 try{
 const context=await browser.newContext({viewport:{width:1440,height:1100},permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.AGENTGATE_UI_URL||'http://127.0.0.1:8000/');
 await page.locator('#visitor-access').waitFor({state:'visible'});
 const token=await page.locator('#demo-token').inputValue();
 if(!token.startsWith('ag_demo_'))throw new Error('Visitor token is missing');
 await page.getByRole('button',{name:'Copy',exact:true}).click();
 await page.locator('#copy-demo-status').filter({hasText:'Copied.'}).waitFor();
 if(await page.evaluate(()=>navigator.clipboard.readText())!==token)throw new Error('Clipboard does not match public token');
 await page.getByRole('button',{name:'Use visitor token'}).click();
 await page.getByRole('button',{name:'Connect to AgentGate'}).click();
 await page.locator('#public-demo-notice').waitFor({state:'visible'});
 await page.getByRole('button',{name:'Tool lab',exact:false}).click();
 await page.locator('#tool-name').selectOption('read_document');
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'allow'}).waitFor();
 await page.locator('#tool-name').selectOption('query_records');
 await page.locator('#tool-args').fill(JSON.stringify({dataset:'payroll',limit:5}));
 await page.getByRole('button',{name:'Execute through gateway'}).click();
 await page.locator('#tool-result-badge').filter({hasText:'deny'}).waitFor();
 await page.getByRole('button',{name:'Access policy',exact:false}).click();
 await page.locator('#policy-json').filter({visible:true}).waitFor();
 if(!await page.locator('#policy-json').evaluate(el=>el.readOnly))throw new Error('Public policy must be read-only');
 if(await page.locator('#save-policy').isVisible())throw new Error('Public user can publish policy');
 await page.getByRole('button',{name:'Agent console',exact:false}).click();
 if(!await page.locator('#run-agent').isDisabled())throw new Error('Unconfigured public model is enabled');
 await page.getByRole('button',{name:'Overview',exact:false}).click();
 if(await page.locator('#metric-total').textContent()!=='2')throw new Error('Actual demo audit decisions are missing');
 await page.screenshot({path:'artifacts/public-demo.png',fullPage:true});
 await page.getByRole('button',{name:'Disconnect'}).click();
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'artifacts/public-login.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw new Error('Public login overflows on mobile');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log('Public visitor UI passed: token display/copy, login, real tools, denials, audit, read-only controls and mobile layout.');
 }finally{await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
