import sys
import json
from pathlib import Path
from decimal import Decimal
import asyncio

# Set up paths so we can import from src
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from ledgerlens.workflow import run_workflow, run_demo, DatasetSplit

def _default_serializer(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

def main():
    out_dir = project_root / "frontend" / "public" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Dev + Demo
    dev_res = run_workflow(DatasetSplit.DEV, project_root)
    demo_res = run_demo(project_root)
    # Merge demo_story_cases into dev
    dev_res["demo_story_cases"] = demo_res.get("demo_story_cases", [])
    if "_raw_audit" in dev_res:
        del dev_res["_raw_audit"]
        
    with open(out_dir / "dev.json", "w", encoding="utf-8") as f:
        json.dump(dev_res, f, default=_default_serializer, indent=2)
        
    # 2. Validation
    val_res = run_workflow(DatasetSplit.VALIDATION, project_root)
    if "_raw_audit" in val_res:
        del val_res["_raw_audit"]
    with open(out_dir / "validation.json", "w", encoding="utf-8") as f:
        json.dump(val_res, f, default=_default_serializer, indent=2)
        
    # 3. Holdout
    holdout_res = run_workflow(DatasetSplit.HOLDOUT, project_root)
    if "_raw_audit" in holdout_res:
        del holdout_res["_raw_audit"]
    with open(out_dir / "holdout.json", "w", encoding="utf-8") as f:
        json.dump(holdout_res, f, default=_default_serializer, indent=2)

if __name__ == "__main__":
    main()
