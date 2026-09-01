"""前端冒烟 (Phase B/C 升级版): 新建→跑→WS→干预→全部视图 全旅程.

需 dev 服务已在跑:
    终端1: uv run uvicorn financial_sim.ui_service.main:app --port 8000
    终端2: cd frontend && npm run dev
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
    page.wait_for_selector("button.primary")
    page.wait_for_timeout(800)   # 等 Svelte 水合完成再点击
    page.locator("button.primary").click()
    page.wait_for_timeout(4000)

    # WS 状态徽章应达到 open
    badge = page.locator(".badge.good", has_text="WS 实时")
    badge.wait_for(timeout=10000)

    # 宏观看板: KPI + 图表
    assert page.locator(".kpi").count() >= 5, "KPI 卡片未渲染"
    assert page.locator("canvas").count() >= 1, "图表未渲染"

    # 播放控制: 跑起来, tick 推进
    page.click("button:has-text('▶')")
    page.wait_for_timeout(3000)
    t_text = page.locator("header .hint").first.inner_text()
    assert "月" in t_text

    # 干预闭环
    page.locator("button.primary", has_text="注入冲击").click()
    page.wait_for_timeout(3000)
    assert page.locator("text=冲击日志").count() == 1

    # 部门矩阵 (SFC Godley 视图)
    page.click("button:has-text('部门矩阵')")
    page.wait_for_timeout(1500)
    assert page.locator("table.data th", has_text="资产端").count() == 1, \
        "部门矩阵未渲染"

    # 家庭分布面板
    page.click("button:has-text('家庭')")
    page.wait_for_timeout(1500)
    assert page.locator(".kpi-value", has_text="1000").count(), \
        "家庭统计未加载 (n=1000)"

    # 下钻: 企业表 + L3
    page.click("button:has-text('下钻')")
    page.wait_for_timeout(1500)
    rows = page.locator("tbody tr").count()
    assert rows >= 1, "部门表格为空"
    page.locator("tbody tr").first.click()
    page.wait_for_timeout(1000)
    assert page.locator(".detail h4").count(), "L3 详情未打开"
    # 政府面板
    page.click("button:has-text('政府')")
    page.wait_for_timeout(1500)
    assert page.locator("text=bonds_outstanding").count(), "政府面板未渲染"

    # 网络视图 (canvas 力导向)
    page.click("button:has-text('网络')")
    page.wait_for_timeout(2000)
    assert page.locator("canvas").count() >= 1, "网络图未渲染"

    page.click("button:has-text('宏观')", timeout=5000)
    assert not errs, f"页面错误: {errs}"
    print("e2e smoke PASS")
    browser.close()
