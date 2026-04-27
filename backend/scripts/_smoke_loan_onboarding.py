"""One-off smoke test for Loan Onboarding micro-app registration.

Run from backend/ with: PYTHONPATH=. python scripts/_smoke_loan_onboarding.py
Safe to delete after scaffolding phase.
"""
from app.micro_apps.registry import discover_micro_apps

apps = discover_micro_apps()
print("Registered micro-apps:", list(apps.keys()))

lo = apps.get("loan-onboarding")
if lo is None:
    raise SystemExit("FAIL: loan-onboarding not registered")

print(f"  slug     = {lo.slug!r}")
print(f"  name     = {lo.name!r}")
print(f"  icon     = {lo.icon!r}")
models = lo.get_models()
print(f"  models   = {len(models)}: {[m.__tablename__ for m in models]}")
router = lo.get_router()
print(f"  routes   = {len(router.routes)} route(s) at root")
print("OK")
