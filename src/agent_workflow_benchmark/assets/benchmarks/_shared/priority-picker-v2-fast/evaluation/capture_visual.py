from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
from pathlib import Path
from typing import Any


def browser_path(lock: dict[str, Any]) -> str:
    for candidate in lock["browser_executable_candidates"]:
        if Path(candidate).is_file():
            return candidate
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("no Chromium executable matches the visual runtime lock")


def check(id_: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": id_, "passed": bool(passed), "detail": detail}


def write_failure(output: Path, lock: dict[str, Any], error: Exception, url: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "assessment.json").write_text(
        json.dumps(
            {
                "schema": "agent-workflow/priority-picker-visual-assessment/v2",
                "capture_state": "harness_failure",
                "url": url,
                "runtime_lock": lock,
                "runtime": {},
                "checks": [check("capture-harness", False, f"{type(error).__name__}: {error}")],
                "screenshots": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = json.loads(args.runtime_lock.read_text(encoding="utf-8"))
    try:
        from playwright.sync_api import sync_playwright

        executable = browser_path(lock)
        errors: list[str] = []
        screenshots: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                args=["--no-sandbox"],
            )
            actual_playwright = importlib.metadata.version("playwright")
            actual_browser = browser.version
            runtime_match = (
                actual_playwright == lock["playwright_version"]
                and actual_browser == lock["browser_version"]
            )
            desktop_page = None
            overflow_results: list[bool] = []
            for viewport in lock["viewports"]:
                context = browser.new_context(
                    viewport={"width": viewport["width"], "height": viewport["height"]},
                    device_scale_factor=lock["device_scale_factor"],
                    locale=lock["locale"],
                    timezone_id=lock["timezone"],
                    color_scheme=lock["color_scheme"],
                    reduced_motion=lock["reduced_motion"],
                    accept_downloads=True,
                )
                page = context.new_page()
                page.on(
                    "console",
                    lambda message: errors.append(f"console:{message.type}:{message.text}")
                    if message.type == "error"
                    else None,
                )
                page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
                page.goto(args.url, wait_until="networkidle", timeout=15000)
                page.locator('[data-testid="priority-item"]').first.wait_for(timeout=5000)
                overflow = bool(
                    page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                    )
                )
                overflow_results.append(not overflow)
                path = output / f"{viewport['id']}.png"
                page.screenshot(path=str(path), full_page=True)
                dom = output / f"{viewport['id']}.html"
                dom.write_text(page.content(), encoding="utf-8")
                screenshots.append(
                    {
                        "id": viewport["id"],
                        "path": str(path),
                        "width": viewport["width"],
                        "height": viewport["height"],
                    }
                )
                if viewport["id"] == "desktop":
                    desktop_page = page
                else:
                    context.close()
            if desktop_page is None:
                raise RuntimeError("visual runtime lock has no desktop viewport")
            page = desktop_page
            checks.append(
                check(
                    "ui.live-app",
                    runtime_match
                    and page.locator('[data-testid="priority-app"]').count() == 1
                    and page.locator('[data-testid="priority-item"]').count() > 0
                    and not errors,
                    f"live URL loaded; playwright={actual_playwright}; browser={actual_browser}; errors={errors}",
                )
            )
            labels_ok = all(
                page.locator(f'label:has([data-testid="{testid}"])').count() == 1
                for testid in (
                    "search-input",
                    "status-filter",
                    "risk-filter",
                    "sort-control",
                )
            )
            checks.append(
                check(
                    "ui.labels-landmark",
                    labels_ok and page.locator("main").count() == 1,
                    "search/status/risk/sort have persistent labels and one main landmark",
                )
            )

            initial_count = page.locator('[data-testid="priority-item"]').count()
            page.locator('[data-testid="search-input"]').fill("checkout")
            page.wait_for_timeout(50)
            search_ids = page.locator('[data-testid="priority-item"]').evaluate_all(
                "nodes => nodes.map(node => node.dataset.id)"
            )
            page.locator('[data-testid="search-input"]').fill("")
            page.locator('[data-testid="status-filter"]').select_option("blocked")
            page.wait_for_timeout(50)
            status_count = page.locator('[data-testid="priority-item"]').count()
            page.locator('[data-testid="status-filter"]').select_option("all")
            before_titles = page.locator('[data-testid="priority-item"] .card-title strong').all_inner_texts()
            page.locator('[data-testid="sort-control"]').select_option("title")
            page.wait_for_timeout(50)
            after_titles = page.locator('[data-testid="priority-item"] .card-title strong').all_inner_texts()
            interaction_ok = (
                initial_count == 6
                and search_ids == ["BKL-101"]
                and status_count == 1
                and after_titles == sorted(after_titles)
                and before_titles != after_titles
            )
            checks.append(
                check(
                    "ui.search-filter-sort",
                    interaction_ok,
                    f"initial={initial_count}; search={search_ids}; blocked={status_count}; sorted={after_titles}",
                )
            )

            first = page.locator('[data-testid="priority-item"]').first
            first.focus()
            page.keyboard.press("Enter")
            detail_text = page.locator('[data-testid="item-detail"]').inner_text()
            checks.append(
                check(
                    "ui.keyboard-detail",
                    len(detail_text) > 60
                    and all(
                        term in detail_text.lower()
                        for term in ("impact", "urgency", "effort", "confidence", "risk")
                    ),
                    "keyboard activation populates description and complete factor breakdown",
                )
            )

            search = page.locator('[data-testid="search-input"]')
            search.focus()
            focus_style = page.evaluate(
                """() => {
                    const s = getComputedStyle(document.activeElement);
                    return {outlineStyle:s.outlineStyle, outlineWidth:s.outlineWidth,
                            boxShadow:s.boxShadow, borderColor:s.borderColor};
                }"""
            )
            visible_focus = (
                focus_style["outlineStyle"] != "none"
                and focus_style["outlineWidth"] not in {"0px", "0"}
            ) or focus_style["boxShadow"] != "none"
            checks.append(
                check(
                    "ui.visible-focus",
                    visible_focus,
                    f"computed active-control style={focus_style}",
                )
            )
            checks.append(
                check(
                    "ui.responsive",
                    all(overflow_results),
                    f"no-overflow results={overflow_results}",
                )
            )

            page.locator('[data-testid="search-input"]').fill("")
            page.locator('[data-testid="status-filter"]').select_option("all")
            page.locator('[data-testid="sort-control"]').select_option("priority")
            with page.expect_download(timeout=5000) as download_info:
                page.locator('[data-testid="export-button"]').click()
            download = download_info.value
            download_path = output / "priority-ordering.json"
            download.save_as(str(download_path))
            payload = json.loads(download_path.read_text(encoding="utf-8"))
            download_ok = (
                download.suggested_filename.endswith(".json")
                and isinstance(payload, list)
                and len(payload) == 6
                and [item.get("rank") for item in payload] == list(range(1, 7))
            )
            checks.append(
                check(
                    "ui.download",
                    download_ok,
                    f"filename={download.suggested_filename}; rows={len(payload) if isinstance(payload, list) else 'invalid'}",
                )
            )

            page.locator('[data-testid="search-input"]').fill("no-such-backlog-item")
            page.wait_for_timeout(50)
            empty_text = page.locator('[data-testid="priority-list"]').inner_text().lower()
            empty_ok = page.locator('[data-testid="priority-item"]').count() == 0 and any(
                term in empty_text for term in ("no ", "empty", "match")
            )
            invalid_context = browser.new_context(
                viewport={"width": 800, "height": 700}, accept_downloads=True
            )
            invalid_page = invalid_context.new_page()
            invalid_page.route(
                "**/api/items",
                lambda route: route.fulfill(
                    status=422,
                    content_type="application/json",
                    body=json.dumps({"error": "synthetic invalid backlog"}),
                ),
            )
            invalid_page.goto(args.url, wait_until="networkidle", timeout=15000)
            invalid_text = invalid_page.locator("body").inner_text().lower()
            invalid_ok = any(
                term in invalid_text for term in ("unable", "error", "invalid", "try again")
            )
            invalid_context.close()
            checks.append(
                check(
                    "ui.empty-invalid",
                    empty_ok and invalid_ok,
                    f"empty_text={empty_text[:200]!r}; invalid_state={invalid_ok}",
                )
            )
            browser.close()
        assessment = {
            "schema": "agent-workflow/priority-picker-visual-assessment/v2",
            "capture_state": "complete",
            "url": args.url,
            "runtime_lock": lock,
            "runtime": {
                "playwright_version": actual_playwright,
                "browser_version": actual_browser,
                "browser_executable": executable,
                "runtime_match": runtime_match,
            },
            "checks": checks,
            "screenshots": screenshots,
        }
        (output / "assessment.json").write_text(
            json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        write_failure(output, lock, exc, args.url)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
