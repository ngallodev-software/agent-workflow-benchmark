from __future__ import annotations
from importlib.resources import files
from pathlib import Path

def asset_path(relative: str): return files("agent_workflow_benchmark").joinpath("assets", relative)
def copy_asset_tree(relative: str, destination: Path) -> None:
    source=asset_path(relative); destination.mkdir(parents=True,exist_ok=True)
    for item in source.iterdir():
        if item.name=="__pycache__" or item.name.endswith((".pyc",".pyo")): continue
        target=destination/item.name
        if item.is_dir(): copy_asset_tree(f"{relative}/{item.name}",target)
        else: target.write_bytes(item.read_bytes())
