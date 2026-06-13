"""
Bid Checker — Playwright Scraper

On each run the scraper:
1. Logs in to crewbids.kalittaair.com
2. Checks the database for a stored Overview.xlsx for the current bid month
   (bid month = next calendar month, since we bid in month N for month N+1).
   If none exists it downloads it from Documents.aspx and stores it.
3. Downloads FO AllBids, Barry's bids, and CA AllBids XLS files.

Returns:
{
    'ca': bytes,       # CA AllBids XLS
    'fo': bytes,       # FO AllBids XLS
    'barry': bytes,    # Barry's personal bids XLS
    'overview': bytes, # Monthly Overview XLSX (from DB or freshly downloaded)
}
"""
import asyncio
import datetime
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger('bid_checker')

BASE_URL = 'https://crewbids.kalittaair.com'
LOGIN_URL = f'{BASE_URL}/Pages/Login.aspx'
BIDS_URL  = f'{BASE_URL}/Pages/ViewAllBids.aspx'
DOCS_URL  = f'{BASE_URL}/Pages/Documents.aspx'
RADIO_CA    = 'ContentPlaceHolder1_RadioButtonList1_0'
RADIO_FO    = 'ContentPlaceHolder1_RadioButtonList1_1'
DROPDOWN_ID = 'ContentPlaceHolder1_ddl_crewMembers'
FMT_SEL  = '#ContentPlaceHolder1_ReportViewer1_ctl01_ctl05_ctl00'
EXP_LINK = '#ContentPlaceHolder1_ReportViewer1_ctl01_ctl05_ctl01'


class ScraperError(Exception):
    pass


class OverviewNotFoundError(ScraperError):
    """Raised when the Overview XLSX link cannot be found on Documents.aspx.

    This is a recoverable condition — the caller can prompt for a manual
    upload rather than treating it as a hard failure.
    """


def _bid_month() -> datetime.date:
    """Return the first day of the month being bid (always next calendar month)."""
    today = datetime.date.today()
    if today.month == 12:
        return datetime.date(today.year + 1, 1, 1)
    return datetime.date(today.year, today.month + 1, 1)


def _is_bids_post(response):
    try:
        return 'ViewAllBids.aspx' in response.url and response.request.method == 'POST'
    except Exception:
        return False


async def _login(page, username, password):
    logger.info('Logging in')
    await page.goto(LOGIN_URL, wait_until='domcontentloaded', timeout=30_000)
    await page.locator('[name="Login1$UserName"]').fill(str(username))
    await page.locator('[name="Login1$Password"]').fill(str(password))
    async with page.expect_navigation(wait_until='domcontentloaded', timeout=20_000):
        await page.locator('[name="Login1$LoginButton"]').click()
    if 'Login' in page.url:
        raise ScraperError('Login failed')
    logger.info('Login OK at %s', page.url)


async def _download_overview(page, bid_month: datetime.date) -> bytes:
    """Download the monthly Overview.xlsx from Documents.aspx.

    Raises OverviewNotFoundError if the link cannot be located — the portal
    occasionally uses a different filename format between bid cycles.
    """
    # Portal uses "Month Year 777 Overview.xlsx" format (e.g. "July 2026 777 Overview.xlsx")
    link_text = f'{bid_month.strftime("%B %Y")} 777 Overview.xlsx'
    logger.info('Downloading Overview: %s', link_text)
    await page.goto(DOCS_URL, wait_until='domcontentloaded', timeout=30_000)
    try:
        async with page.expect_download(timeout=30_000) as dl:
            # exact=False: partial match so minor portal naming changes don't hard-crash
            await page.get_by_text(link_text, exact=False).click(timeout=15_000)
        download = await dl.value
    except Exception as exc:
        raise OverviewNotFoundError(
            f'Overview file not found on portal (looked for "{link_text}")'
        ) from exc

    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp_path = Path(tmp.name)
        await download.save_as(tmp_path)
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    if len(data) < 1000:
        raise ScraperError(f'Overview download too small ({len(data)} bytes)')
    logger.info('Overview downloaded: %d bytes', len(data))
    return data


async def _click_radio(page, radio_id, label):
    logger.info('Clicking %s radio', label)
    async with page.expect_response(_is_bids_post, timeout=60_000) as r:
        await page.click(f'#{radio_id}')
    await r.value
    await page.wait_for_selector(f'#{DROPDOWN_ID}', timeout=30_000)
    logger.info('%s radio postback done', label)


async def _select_dropdown(page, value, label):
    logger.info('Selecting dropdown %r for %s', value, label)
    async with page.expect_response(_is_bids_post, timeout=60_000) as r:
        await page.select_option(f'#{DROPDOWN_ID}', value=value)
    await r.value
    logger.info('Dropdown postback done for %s', label)


async def _export_xls(page, context) -> bytes:
    await page.wait_for_selector(f'{FMT_SEL}:not([disabled])', timeout=60_000)
    await page.select_option(FMT_SEL, 'Excel')
    async with page.expect_download(timeout=120_000) as dl_info:
        await page.click(EXP_LINK)
    download = await dl_info.value
    with tempfile.NamedTemporaryFile(suffix='.xls', delete=False) as tmp:
        tmp_path = Path(tmp.name)
        await download.save_as(tmp_path)
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    if len(data) < 1024:
        raise ScraperError(f'Download too small ({len(data)} bytes)')
    return data


async def scrape_bids_async(username, password, barry_employee_id='71837'):
    from playwright.async_api import async_playwright
    from asgiref.sync import sync_to_async
    from bid_checker.models import MonthlyOverview

    logger.info('Scraper starting')
    bid_mon = _bid_month()

    # Check DB for cached Overview — must use sync_to_async inside async context
    @sync_to_async
    def get_cached():
        return MonthlyOverview.objects.filter(month=bid_mon).first()

    @sync_to_async
    def save_overview(data):
        MonthlyOverview.objects.create(month=bid_mon, xlsx_data=data)

    cached = await get_cached()
    need_overview = cached is None
    if need_overview:
        logger.info('No Overview cached for %s — will download from site',
                    bid_mon.strftime('%B %Y'))
    else:
        logger.info('Using cached Overview for %s', bid_mon.strftime('%B %Y'))
        overview_bytes = bytes(cached.xlsx_data)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await _login(page, username, password)

            # Download Overview if not cached — OverviewNotFoundError propagates up
            if need_overview:
                overview_bytes = await _download_overview(page, bid_mon)
                await save_overview(overview_bytes)
                logger.info('Overview saved to database for %s',
                            bid_mon.strftime('%B %Y'))

            # Navigate to bids page — FO pre-selected for this user
            await page.goto(BIDS_URL, wait_until='domcontentloaded', timeout=30_000)
            await page.wait_for_selector(f'#{DROPDOWN_ID}', timeout=30_000)
            logger.info('Bids page loaded')

            # FO AllBids
            await _select_dropdown(page, 'View All', 'FO AllBids')
            fo_xls = await _export_xls(page, context)
            logger.info('FO XLS: %d bytes', len(fo_xls))

            # Barry's bids
            await _select_dropdown(page, barry_employee_id, "Barry's bids")
            barry_xls = await _export_xls(page, context)
            logger.info('Barry XLS: %d bytes', len(barry_xls))

            # CA AllBids — radio swap resets dropdown to 'Select Name'
            await _click_radio(page, RADIO_CA, 'CA')
            await _select_dropdown(page, 'View All', 'CA AllBids')
            ca_xls = await _export_xls(page, context)
            logger.info('CA XLS: %d bytes', len(ca_xls))

        except (ScraperError, OverviewNotFoundError):
            raise
        except Exception as e:
            raise ScraperError(f'Unexpected error: {e}') from e
        finally:
            await browser.close()

    logger.info('Scraper complete')
    return {
        'ca':       ca_xls,
        'fo':       fo_xls,
        'barry':    barry_xls,
        'overview': overview_bytes,
    }


def scrape_bids(username, password, barry_employee_id='71837'):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(
        scrape_bids_async(username, password, barry_employee_id))
