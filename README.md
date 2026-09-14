# Fiscal Space

A personal UK fiscal research tool for Patrick Schneider. Start with a concise Overview, then open Fiscal (Position, Composition, Outlook and fiscal rules), Pricing, Debt & financing, or Explore. Fiscal amounts default to % GDP with a £bn option; composition also supports shares of its named total. Charts retain source notes, data tables and CSV/SVG exports. View links preserve analytical selections.

## Hosted app

[Open the dashboard](https://patrickmschneider.github.io/fiscal-space/). GitHub Pages serves the app over HTTPS; no login, backend or paid subscription is required. The app and data are public.

The **Publish dashboard** GitHub Actions workflow deploys pushes to `main` and checks official sources daily at 13:17 UTC (13:17 London winter / 14:17 summer; GitHub schedules may run late). For an immediate refresh, open the repository’s Actions tab, select that workflow, and choose **Run workflow** with refresh enabled. A source failure retains validated previous data, displays its failure status, and marks the run failed after deploying. Enable repository Actions notifications in your GitHub notification settings if you want failure emails. GitHub can disable schedules on inactive public repositories after 60 days; re-enable the workflow if that happens.

The DMO calendar/notices and OBR forecast vintage still require maintenance when new publications appear; the daily job does not eliminate the documented coverage gaps.

## Run locally

Requires Node.js 22.12+ (tested on 24) and npm.

```sh
npm ci
npm run dev
```

Open the local address printed by Vite. The included official-data snapshots let the app run immediately. The local address works on the computer running it. The hosted app works across devices.

## Refresh data

Requires Python 3.11+ (tested on 3.13).

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.refresh
```

Use `--group fiscal`, `--group composition`, `--group debt`, `--group forecast` `--group curve`, `--group outlook` or `--group reliefs` for an individual source group. `--offline` replays locally archived downloads; `--validate` checks saved data. A failed group keeps its last good dataset, records the failure and returns a nonzero exit code. Downloads and release vintages are retained in ignored `data/archive/`; back up that directory if you need those vintages. Compact normalized vintages and input-checksum metadata are also preserved on the remote `data-history` branch. Raw source downloads remain local.

The repository includes fitted Bank of England curve outputs for this non-commercial academic dashboard, under the owner’s explicit decision to proceed with attribution despite unresolved reuse wording. This is not a claim of Open Government Licence coverage or specific Bank permission. The app and exports credit the Bank and its stated Bloomberg/Tradeweb inputs, distinguish dashboard calculations and disclaim endorsement. Original downloaded workbooks remain local. Run `python -m pipeline.refresh --group curve` to update the saved curves.

## Redesign coverage and maintenance

- Overview: dated rolling-year borrowing and debt, long spending/receipts history, pre-pandemic composition changes, compact forecast paths and market pricing.
- Fiscal: rolling/monthly/YTD position; composition snapshots, comparable history and reconciled two-year contributions; March 2026 EFO and a **labelled rounded reconstruction** of November 2025. Formal November rule assessments remain distinct from the March current-budget update. New EFO releases require adapter maintenance.
- Pricing: nominal and real gilt spot curves, RPI breakevens and matched-date changes, with shared comparison calendars.
- Debt & financing: gilt stock, maturity concentration, upcoming sales, redemptions and published auction results. Contractual amounts and auction statistics retain natural units.
- Explore: searchable ONS series, HMRC relief records, selected analytical measures, source downloads and methodology. Relief search comes before optional stories; missing/withheld/negligible values stay missing, component rows are excluded from aggregates, and structural/non-structural costs are not combined.
- Calendar: curated official events/releases checked 10 September 2026. Update `public/data/monitor.json` when confirmed events change. Viewing the app reads saved snapshots; it does not download official source workbooks.

Separate monthly receipts, spending and interest forecast profiles are not available in the imported official profile. Real-per-capita spending lacks matched population data; a numerical debt snowball/effective rate lacks matched stock-flow definitions. Current consensus feeds, policy-versus-economy forecast decompositions and headroom stress elasticities are not fabricated. These limitations are shown beside the relevant analysis.

Refresh metadata reports new/revised observations, source-section changes, forecast vintages and relief additions/deletions/reclassifications. Large historical revisions are flagged for review; a schema failure retains prior data. The durable archive preserves normalized data and input checksums; original source files remain in the local ignored archive.

## Current coverage

- ONS public sector finances through July 2026, with reconciled receipts, expenditure and borrowing; March 2026 OBR monthly borrowing forecast via ONS.
- HM Treasury PESA annual functional history, 2003-04–2025-26, plus the detailed five-year snapshot. Its TES denominator differs from the fiscal page's TME measure; the app shows the bridge.
- Compare budgets over time offers annual economic, functional and revenue breakdowns, two-year contribution tables, and an interest-paid/received bridge. Taxes and NICs are shown separately from total current receipts.
- DMO gilt stock dated 4 September 2026. Auction results include July 2025–June 2026 and selected later notices; July–August 2026 coverage is incomplete. The July–December financing calendar uses curated official notices and still needs source discovery when schedules change.
- Local Bank of England nominal and real spot curves and matched RPI breakevens through 7 September 2026. Pricing offers saved-date comparisons and changes in basis points. Breakevens include risk and liquidity premia; they are not pure inflation expectations.
- Fiscal headline/time-series flows can be shown in £bn or % of GDP. The denominator is the latest published four-quarter nominal GDP ending on/before each flow endpoint (at most two months earlier), with its date shown and exported. Monthly/YTD flows are not annualised; these dashboard ratios differ from official ONS fiscal ratios.

The app labels definitions, observation dates and partial coverage. Refreshing a curated DMO notice does not discover newly published notices. Machine-readable source mappings and reuse notes live in `catalogue/`.

## Checks

```sh
npm run build
npm test
source .venv/bin/activate
npm run test:data
npx playwright install chromium webkit
APP_URL=http://127.0.0.1:5173 npm run test:browser
```

Run the development server first and set `APP_URL` to its printed address. Browser checks cover both pages, mobile overflow, keyboard access, accessibility, URL state and exports.

## Project references

- [Implementation plan and future extensions](docs/PROJECT_PLAN.md)
- [Progress, limitations and next task](docs/STATUS.md)

Personal website integration remains outside scope.

Historical social-protection detail is pinned in `data/pesa-social-history.json`, with Treasury source URLs and SHA-256 checksums for every imported vintage. `python -m pipeline.pesa_history` rebuilds it from the official sources and rejects changed source files for review. Daily composition refreshes combine this back history with the current PESA table; the app labels source vintages and reconciles revisions to the latest parent total. Public debt transactions are separated using the existing long PESA history.

## Archive and rollback

Every build preserves a checksummed bundle on `data-history` before deployment. `deployment.json` on the live site identifies its snapshot and application commit. Archives contain compressed normalized data and source-checksum metadata, not original source workbooks. Git history preserves previous `latest.json` pointers. The archive pointer describes the latest build attempt; the live `deployment.json` is authoritative for what actually deployed.

To rehearse recovery without touching the working app, clone the archive branch and restore into a temporary folder:

```sh
git clone --branch data-history --single-branch https://github.com/patrickmschneider/fiscal-space.git /tmp/fiscal-space-history
python -m pipeline.archive_history --destination /tmp/fiscal-space-history --restore SNAPSHOT_ID --root /tmp/fiscal-space-restore
```

The command verifies the complete dataset bundle and reports `requiredCodeSha`. For a production rollback, recover that application commit in an isolated checkout, restore the matching snapshot (use `--code-sha` to enforce the match), and run the build and tests. Commit the recovered code/data to `main` while preserving the publishing workflow; the normal push deploys that pair without refreshing it first. Avoid force-pushing.
