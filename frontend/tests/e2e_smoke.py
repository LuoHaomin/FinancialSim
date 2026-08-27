"""Phase 4 MVP 冒烟: 新建→跑→干预→下钻 全旅程 (需 dev 服务已在跑).

    /tmp/pwvenv/bin/python frontend/tests/e2e_smoke.py [base_url]
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.click("text=新建仿真")
    page.wait_for_timeout(5000)

    assert page.locator(".chart canvas").count() == 1, "图表未渲染"
    page.click("text=注入冲击")
    page.wait_for_timeout(2500)
    page.click("text=部门下钻", timeout=8000)
    page.wait_for_timeout(1500)
    rows = page.locator("tbody tr").count()
    assert rows >= 1, "部门表格为空"
    page.locator("tbody tr").first.click()
    page.wait_for_timeout(1000)
    assert page.locator(".detail h4").count(), "L3 详情未打开"
    page.click("text=宏观", timeout=5000)
    log_rows = page.locator(".panel table tbody tr").count()
    assert log_rows >= 1, "冲击日志为空"
    assert not errs, f"页面错误: {errs}"
    print("e2e smoke PASS")
    browser.close()
