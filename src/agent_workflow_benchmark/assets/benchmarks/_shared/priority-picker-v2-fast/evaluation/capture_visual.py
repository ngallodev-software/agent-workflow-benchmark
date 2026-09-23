from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
from pathlib import Path
from typing import Any, Callable


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


def solution_check(
    id_: str,
    operation: Callable[[], tuple[bool, str]],
) -> dict[str, Any]:
    """Convert solution/UI failures into scored check failures.

    Only benchmark infrastructure/runtime failures should become harness failures.
    Missing controls, unsupported UI choices, JavaScript errors, and application
    behavior are solution outcomes and must remain scoreable evidence.
    """
    try:
        passed, detail = operation()
        return check(id_, passed, detail)
    except Exception as exc:
        return check(id_, False, f"solution check failed: {type(exc).__name__}: {exc}")


def write_failure(
    output: Path,
    lock: dict[str, Any],
    error: Exception,
    url: str,
    *,
    runtime: dict[str, Any] | None = None,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "assessment.json").write_text(
        json.dumps(
            {
                "schema": "agent-workflow/priority-picker-visual-assessment/v2",
                "capture_state": "harness_failure",
                "url": url,
                "runtime_lock": lock,
                "runtime": runtime or {},
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

    runtime: dict[str, Any] = {}
    try:
        from playwright.sync_api import sync_playwright

        executable = browser_path(lock)
        screenshots: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        console_errors: list[str] = []
        navigation_errors: list[str] = []
        observations: dict[str, Any] = {
            "live": {},
            "download": {"rows": None, "json_download": False, "filename": None},
            "empty_invalid": {"empty_ok": False, "invalid_ok": False},
        }

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
            runtime = {
                "playwright_version": actual_playwright,
                "browser_version": actual_browser,
                "browser_executable": executable,
                "runtime_match": runtime_match,
            }

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
                    lambda message: console_errors.append(
                        f"console:{message.type}:{message.text}"
                    )
                    if message.type == "error"
                    else None,
                )
                page.on(
                    "pageerror",
                    lambda error: console_errors.append(f"pageerror:{error}"),
                )
                try:
                    page.goto(args.url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(250)
                except Exception as exc:
                    navigation_errors.append(
                        f"{viewport['id']}:{type(exc).__name__}:{exc}"
                    )

                try:
                    overflow = bool(
                        page.evaluate(
                            "document.documentElement.scrollWidth > "
                            "document.documentElement.clientWidth"
                        )
                    )
                    overflow_results.append(not overflow)
                except Exception:
                    overflow_results.append(False)

                path = output / f"{viewport['id']}.png"
                try:
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
                except Exception as exc:
                    navigation_errors.append(
                        f"{viewport['id']}-evidence:{type(exc).__name__}:{exc}"
                    )

                if viewport["id"] == "desktop":
                    desktop_page = page
                else:
                    context.close()

            if desktop_page is None:
                raise RuntimeError("visual runtime lock has no desktop viewport")
            page = desktop_page

            def live_app() -> tuple[bool, str]:
                app_count = page.locator('[data-testid="priority-app"]').count()
                item_count = page.locator('[data-testid="priority-item"]').count()
                observations["live"] = {
                    "app_count": app_count,
                    "item_count": item_count,
                    "console_error_count": len(console_errors),
                    "navigation_error_count": len(navigation_errors),
                }
                passed = (
                    runtime_match
                    and app_count == 1
                    and item_count > 0
                    and not console_errors
                    and not navigation_errors
                )
                return (
                    passed,
                    "live URL loaded; "
                    f"playwright={actual_playwright}; browser={actual_browser}; "
                    f"app_count={app_count}; item_count={item_count}; "
                    f"errors={console_errors}; navigation_errors={navigation_errors}",
                )

            checks.append(solution_check("ui.live-app", live_app))

            def labels_landmark() -> tuple[bool, str]:
                labels = {
                    testid: page.locator(
                        f'label:has([data-testid="{testid}"])'
                    ).count()
                    for testid in (
                        "search-input",
                        "status-filter",
                        "risk-filter",
                        "sort-control",
                    )
                }
                main_count = page.locator("main").count()
                return (
                    all(value == 1 for value in labels.values()) and main_count == 1,
                    f"labels={labels}; main_count={main_count}",
                )

            checks.append(solution_check("ui.labels-landmark", labels_landmark))

            def search_filter_sort() -> tuple[bool, str]:
                items = page.locator('[data-testid="priority-item"]')
                initial_count = items.count()
                page.locator('[data-testid="search-input"]').fill("checkout")
                page.wait_for_timeout(50)
                search_ids = items.evaluate_all(
                    "nodes => nodes.map(node => node.dataset.id)"
                )
                page.locator('[data-testid="search-input"]').fill("")
                page.locator('[data-testid="status-filter"]').select_option("blocked")
                page.wait_for_timeout(50)
                status_count = items.count()
                page.locator('[data-testid="status-filter"]').select_option("all")

                before_ids = items.evaluate_all(
                    "nodes => nodes.map(node => node.dataset.id)"
                )
                sort_control = page.locator('[data-testid="sort-control"]')
                current_sort = sort_control.input_value()
                sort_values = sort_control.locator("option").evaluate_all(
                    "nodes => nodes.map(node => node.value)"
                )
                alternate = next(
                    (value for value in sort_values if value and value != current_sort),
                    None,
                )
                if alternate is None:
                    sort_changed = False
                    after_ids = before_ids
                else:
                    sort_control.select_option(alternate)
                    page.wait_for_timeout(50)
                    after_ids = items.evaluate_all(
                        "nodes => nodes.map(node => node.dataset.id)"
                    )
                    sort_changed = before_ids != after_ids

                passed = (
                    initial_count == 6
                    and search_ids == ["BKL-101"]
                    and status_count == 1
                    and alternate is not None
                    and sort_changed
                )
                return (
                    passed,
                    f"initial={initial_count}; search={search_ids}; blocked={status_count}; "
                    f"sort_options={sort_values}; selected={alternate}; "
                    f"before={before_ids}; after={after_ids}",
                )

            checks.append(solution_check("ui.search-filter-sort", search_filter_sort))

            def keyboard_detail() -> tuple[bool, str]:
                first = page.locator('[data-testid="priority-item"]').first
                first.focus()
                page.keyboard.press("Enter")
                detail_text = page.locator('[data-testid="item-detail"]').inner_text()
                passed = len(detail_text) > 60 and all(
                    term in detail_text.lower()
                    for term in ("impact", "urgency", "effort", "confidence", "risk")
                )
                return (
                    passed,
                    "keyboard activation detail="
                    + repr(detail_text[:300]),
                )

            checks.append(solution_check("ui.keyboard-detail", keyboard_detail))

            def visible_focus() -> tuple[bool, str]:
                search = page.locator('[data-testid="search-input"]')
                search.focus()
                focus_style = page.evaluate(
                    """() => {
                        const s = getComputedStyle(document.activeElement);
                        return {outlineStyle:s.outlineStyle, outlineWidth:s.outlineWidth,
                                boxShadow:s.boxShadow, borderColor:s.borderColor};
                    }"""
                )
                passed = (
                    focus_style["outlineStyle"] != "none"
                    and focus_style["outlineWidth"] not in {"0px", "0"}
                ) or focus_style["boxShadow"] != "none"
                return passed, f"computed active-control style={focus_style}"

            checks.append(solution_check("ui.visible-focus", visible_focus))

            checks.append(
                check(
                    "ui.responsive",
                    len(overflow_results) == len(lock["viewports"])
                    and all(overflow_results),
                    f"no-overflow results={overflow_results}; "
                    f"captured={len(screenshots)}/{len(lock['viewports'])}",
                )
            )

            def download_check() -> tuple[bool, str]:
                page.locator('[data-testid="search-input"]').fill("")
                page.locator('[data-testid="status-filter"]').select_option("all")
                with page.expect_download(timeout=5000) as download_info:
                    page.locator('[data-testid="export-button"]').click()
                download = download_info.value
                download_path = output / "priority-ordering.json"
                download.save_as(str(download_path))
                payload = json.loads(download_path.read_text(encoding="utf-8"))
                observations["download"] = {
                    "rows": len(payload) if isinstance(payload, list) else None,
                    "json_download": download.suggested_filename.endswith(".json") and isinstance(payload, list),
                    "filename": download.suggested_filename,
                    "ranks_complete": isinstance(payload, list) and [item.get("rank") for item in payload] == list(range(1, len(payload) + 1)),
                }
                passed = (
                    download.suggested_filename.endswith(".json")
                    and isinstance(payload, list)
                    and len(payload) == 6
                    and [item.get("rank") for item in payload] == list(range(1, 7))
                )
                return (
                    passed,
                    f"filename={download.suggested_filename}; "
                    f"rows={len(payload) if isinstance(payload, list) else 'invalid'}",
                )

            checks.append(solution_check("ui.download", download_check))

            def empty_invalid() -> tuple[bool, str]:
                page.locator('[data-testid="search-input"]').fill(
                    "no-such-backlog-item"
                )
                page.wait_for_timeout(50)
                empty_text = (
                    page.locator('[data-testid="priority-list"]').inner_text().lower()
                )
                empty_ok = (
                    page.locator('[data-testid="priority-item"]').count() == 0
                    and any(
                        term in empty_text
                        for term in ("no ", "empty", "match")
                    )
                )

                invalid_context = browser.new_context(
                    viewport={"width": 800, "height": 700},
                    accept_downloads=True,
                )
                try:
                    invalid_page = invalid_context.new_page()
                    invalid_page.route(
                        "**/api/items",
                        lambda route: route.fulfill(
                            status=422,
                            content_type="application/json",
                            body=json.dumps(
                                {"error": "synthetic invalid backlog"}
                            ),
                        ),
                    )
                    invalid_page.goto(
                        args.url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    invalid_page.wait_for_timeout(250)
                    invalid_text = invalid_page.locator("body").inner_text().lower()
                    invalid_ok = any(
                        term in invalid_text
                        for term in ("unable", "error", "invalid", "try again")
                    )
                finally:
                    invalid_context.close()
                observations["empty_invalid"] = {
                    "empty_ok": empty_ok,
                    "invalid_ok": invalid_ok,
                }
                return (
                    empty_ok and invalid_ok,
                    f"empty_text={empty_text[:200]!r}; invalid_state={invalid_ok}",
                )

            checks.append(solution_check("ui.empty-invalid", empty_invalid))
            browser.close()

        assessment = {
            "schema": "agent-workflow/priority-picker-visual-assessment/v2",
            "capture_state": "complete",
            "url": args.url,
            "runtime_lock": lock,
            "runtime": runtime,
            "checks": checks,
            "observations": observations,
            "screenshots": screenshots,
        }
        (output / "assessment.json").write_text(
            json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        write_failure(output, lock, exc, args.url, runtime=runtime)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
