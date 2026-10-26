import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';

// The Australian edition is published beneath the UK app at au/.
test('Australian edition loads its own data, pages and charts beneath au/',async({page,request},testInfo)=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const fiscal=await (await request.get('au/data/fiscal.json')).json();
 expect(fiscal.scope).toContain('Australian Government');
 await page.goto('./au/?page=overview');
 await expect(page.getByText('A GUIDE TO THE AUSTRALIAN PUBLIC FINANCES')).toBeVisible();
 await expect(page.getByText(/The underlying cash deficit was|underlying cash surplus/).first()).toBeVisible();
 await expect(page.getByText('Some saved data could not be loaded')).toHaveCount(0);
 const editions=page.getByRole('group',{name:'Country edition'});
 await expect(editions.getByRole('link',{name:'Australia'})).toHaveAttribute('aria-current','page');
 await expect(editions.getByRole('link',{name:'UK',exact:true})).toHaveAttribute('href','../?page=overview');
 await page.goto('./au/?page=fiscal&section=position');
 await expect(page.getByRole('heading',{name:'Australia’s fiscal position.'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Underlying cash deficit'})).toBeVisible();
 await page.getByRole('button',{name:'Debt & financing',exact:true}).click();
 await expect(page.getByRole('heading',{name:'The stock. The cost. The calendar.'})).toBeVisible();
 await expect(page.getByText('Bonds outstanding · face value')).toBeVisible();
 await page.goto('./au/?page=pricing');
 for(const id of ['yield-curve','real-curve','breakeven'])await expect(page.locator(`[aria-labelledby="${id}-title"] .recharts-line-curve`).first()).toBeVisible();
 await expect(page.getByRole('heading',{name:'CPI breakeven inflation'})).toBeVisible();
 await expect(page.locator('[aria-labelledby="breakeven-10y-title"]')).toHaveCount(0);
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Download Nominal bond yield curve CSV',exact:true}).click();
 const path=testInfo.outputPath('au-curve.csv');await (await pending).saveAs(path);
 const text=await fs.readFile(path,'utf8');expect(text).toContain('Reserve Bank of Australia');expect(text).not.toContain('Bank of England');
 await page.goto('./au/?page=fiscal&section=composition');
 await expect(page.getByRole('heading',{name:'Spending and revenue composition'})).toBeVisible();
 await page.setViewportSize({width:375,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
 expect(accessibility.violations.map(v=>v.id)).toEqual([]);
 for(const view of ['?page=fiscal&section=outlook','?page=fiscal&section=rules','?page=fiscal&section=deficits','?page=explore&view=reliefs','?page=explore&view=methodology']){
  await page.goto(`./au/${view}`);await expect(page.locator('main footer')).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/\bOBR\b|\bONS\b|£|\bgilts?\b/);
 }
 expect(errors).toEqual([]);
});
