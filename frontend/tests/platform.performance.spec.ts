import { test, expect } from "@playwright/test";

// Real isolated API with selected delays makes request waterfalls observable.
test("case tabs load on demand, preserve drafts and ignore stale case responses", async ({page,context,request}) => {
  const signup=await request.post("http://127.0.0.1:8025/platform/account/signup",{data:{workspace:"Synthetic performance store",name:"Performance owner",email:"performance-owner@example.test",password:"synthetic-performance-password"}});
  expect(signup.status()).toBe(201);
  const {token}=await signup.json();
  const headers={Authorization:"Bearer "+token};
  await context.addCookies([{name:"resolve_merchant_session",value:token,url:"http://127.0.0.1:3125",httpOnly:true,sameSite:"Lax"}]);
  const create=async(title:string)=>{const response=await request.post("http://127.0.0.1:8025/resolution-cases",{headers,data:{title}});expect(response.status()).toBe(201);return (await response.json()).id;};
  const first=await create("Fast primary case"), second=await create("Delayed secondary case");
  const requests:string[]=[];
  page.on("request",r=>{const path=new URL(r.url()).pathname;if(path.startsWith("/api/"))requests.push(path);});
  await page.goto(`/workspace?case=${first}`);
  await expect(page.getByRole("heading",{name:"Fast primary case",exact:true})).toBeVisible();
  await expect.poll(()=>requests.filter(p=>p.endsWith("/support-requests")).length).toBeGreaterThan(0);
  for(const suffix of ["/timeline","/investigations","/helpdesk","/offers","/returns","/dispute-packages","/disputes","/customer-evidence"]){expect(requests.some(p=>p.endsWith(suffix)),suffix).toBe(false);}
  const initialCalls=new Set(requests).size;
  const tab=(name:string)=>page.getByRole("button",{name,exact:true});
  await tab("Evidence timeline").click();
  await expect(page.locator(".timeline-card .event-list li").first()).toBeVisible();
  await tab("Overview").click();await tab("Evidence timeline").click();
  expect(requests.filter(p=>p.endsWith("/timeline")).length).toBe(1);
  await tab("Customer portal").click();
  await expect(page.getByRole("heading",{name:"Share with customer",exact:true})).toBeVisible();
  const title=page.getByRole("textbox",{name:"Customer heading",exact:true});
  await expect(title).toBeEnabled();await title.fill("Retained customer draft");
  const customerCalls=requests.filter(p=>p.endsWith("/customer-link")).length;
  await tab("Overview").click();await tab("Customer portal").click();
  await expect(title).toHaveValue("Retained customer draft");
  expect(requests.filter(p=>p.endsWith("/customer-link")).length).toBe(customerCalls);
  await page.route(`**/api/resolve/resolution-cases/${second}`,async route=>{await new Promise(resolve=>setTimeout(resolve,1000));await route.continue();});
  await page.locator(".case-row").filter({hasText:"Delayed secondary case"}).click();
  await page.locator(".case-row").filter({hasText:"Fast primary case"}).click();
  await expect(page.locator(".case-heading h2")).toHaveText("Fast primary case");
  await page.waitForTimeout(1500);
  await expect(page.locator(".case-heading h2")).toHaveText("Fast primary case");
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({path:"../.local/ui/platform-artifacts/performance-case-mobile.png",fullPage:true});
  console.log(JSON.stringify({initialUniqueApiPaths:initialCalls,timelineRequests:1,customerPanelRefetchesOnTabReturn:0}));
});
