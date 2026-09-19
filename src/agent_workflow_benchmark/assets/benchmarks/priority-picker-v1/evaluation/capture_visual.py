from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sys
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


def renderable_document(worktree: Path) -> str:
    """Inline the submitted UI and provide its local API response without network access.

    Managed browser policies can forbid every navigation, including loopback and file
    URLs. ``page.set_content`` still exercises the submitted HTML, CSS, and JavaScript
    while a narrow fetch shim supplies only the deterministic fixture payload.
    """
    web_root = worktree / "priority_picker" / "web"
    index = (web_root / "index.html").read_text(encoding="utf-8")
    styles = (web_root / "styles.css").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")
    sys.path.insert(0, str(worktree))
    try:
        from priority_picker.priority import load_backlog, rank_items

        payload = {"items": rank_items(load_backlog(worktree / "data" / "backlog.json"))}
    finally:
        try:
            sys.path.remove(str(worktree))
        except ValueError:
            pass
    fetch_shim = (
        "const fetch=async function(url){"
        "if(String(url).includes('/api/items'))return {ok:true,status:200,json:async()=>("
        + json.dumps(payload, separators=(",", ":"))
        + ")};throw new Error('benchmark capture blocked undeclared fetch: '+url);};\n"
    )
    style_tag = "<style>" + styles.replace("</style>", "<" + "/style>") + "</style>"
    script_tag = "<script>" + fetch_shim + script.replace("</script>", "<" + "/script>") + "</script>"
    import re

    index, style_count = re.subn(
        r'<link\b[^>]*href=["\'][^"\']*styles\.css["\'][^>]*>',
        lambda _match: style_tag,
        index,
        count=1,
        flags=re.IGNORECASE,
    )
    index, script_count = re.subn(
        r'<script\b[^>]*src=["\'][^"\']*app\.js["\'][^>]*>\s*</script>',
        lambda _match: script_tag,
        index,
        count=1,
        flags=re.IGNORECASE,
    )
    if style_count != 1 or script_count != 1:
        raise RuntimeError("submitted UI must reference exactly one styles.css and one app.js")
    return index


def write_failure(output: Path, lock: dict[str, Any], error: Exception) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "assessment.json").write_text(
        json.dumps(
            {
                "schema": "agent-workflow/priority-picker-visual-assessment/v1",
                "capture_state": "harness_failure",
                "runtime_lock": lock,
                "runtime": {},
                "checks": [check("capture-harness", False, f"{type(error).__name__}: {error}")],
                "screenshots": [],
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = json.loads(args.runtime_lock.read_text(encoding="utf-8"))
    try:
        from playwright.sync_api import sync_playwright

        executable = browser_path(lock)
        document = renderable_document(worktree)
        errors: list[str] = []
        screenshots: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable, args=["--no-sandbox"])
            actual_playwright = importlib.metadata.version("playwright")
            actual_browser = browser.version
            runtime_match = actual_playwright == lock["playwright_version"] and actual_browser == lock["browser_version"]
            checks.append(check("runtime-match", runtime_match, f"playwright={actual_playwright}; browser={actual_browser}"))
            first_page = None
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
                page.on("console", lambda message: errors.append(f"console:{message.type}:{message.text}") if message.type == "error" else None)
                page.on("pageerror", lambda error: errors.append(f"pageerror:{error}"))
                page.set_content(document, wait_until="networkidle", timeout=15000)
                page.locator('[data-testid="priority-item"]').first.wait_for(timeout=5000)
                if first_page is None:
                    first_page = page
                overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                checks.append(check(f"{viewport['id']}-no-overflow", not overflow, f"viewport {viewport['width']}x{viewport['height']}"))
                path = output / f"{viewport['id']}.png"
                page.screenshot(path=str(path), full_page=True)
                dom = output / f"{viewport['id']}.html"
                dom.write_text(page.content(), encoding="utf-8")
                screenshots.append({"id": viewport["id"], "path": str(path), "width": viewport["width"], "height": viewport["height"]})
                if viewport["id"] != "desktop":
                    context.close()
            assert first_page is not None
            page = first_page
            checks.append(check("app-loaded", page.locator('[data-testid="priority-app"]').count() == 1 and page.locator('[data-testid="priority-item"]').count() > 0, "application and ranked items render"))
            checks.append(check("main-landmark", page.locator("main").count() == 1, "one main landmark"))
            labels_ok = all(page.locator(f'label:has([data-testid="{testid}"])').count() == 1 for testid in ("search-input", "status-filter", "risk-filter", "sort-control"))
            checks.append(check("controls-labeled", labels_ok, "search, status, risk, and sort have persistent labels"))
            export_ok = page.locator('[data-testid="export-button"]').count() == 1 and bool(page.locator('[data-testid="export-button"]').inner_text().strip())
            checks.append(check("export-control", export_ok, "export control has an accessible name"))
            page.locator('[data-testid="search-input"]').focus()
            focused_before = page.evaluate("document.activeElement === document.querySelector('[data-testid=search-input]')")
            page.keyboard.press("Tab")
            focused_after = page.evaluate("document.activeElement !== document.body")
            checks.append(check("focus-visible", focused_before and focused_after, "keyboard focus enters and advances through controls"))
            first = page.locator('[data-testid="priority-item"]').first
            first.focus()
            page.keyboard.press("Enter")
            detail_text = page.locator('[data-testid="item-detail"]').inner_text()
            checks.append(check("keyboard-detail", len(detail_text) > 40, "keyboard activation populates item detail"))
            checks.append(check("no-console-errors", not errors, "; ".join(errors) if errors else "no console or page errors"))
            browser.close()
        assessment = {
            "schema": "agent-workflow/priority-picker-visual-assessment/v1",
            "capture_state": "complete",
            "runtime_lock": lock,
            "runtime": {"playwright_version": actual_playwright, "browser_version": actual_browser, "browser_executable": executable},
            "checks": checks,
            "screenshots": screenshots,
        }
        (output / "assessment.json").write_text(json.dumps(assessment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except Exception as exc:
        write_failure(output, lock, exc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
