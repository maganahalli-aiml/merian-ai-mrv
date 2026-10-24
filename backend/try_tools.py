"""See a tool the way the model sees it, then check the FX rule twice (run from backend/):  uv run python try_tools.py"""
import requests

from agent.tools import validate_fx_hedge

print("name       :", validate_fx_hedge.name)
print("description:", validate_fx_hedge.description)
print("arguments  :", validate_fx_hedge.args)

live = requests.get("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=JPY", timeout=10).json()["rates"]["JPY"]
print("\nlive rate  :", live)
for factor in (1.01, 1.07):
    print(validate_fx_hedge.invoke({"currency_pair": "EUR_JPY", "rate_used": round(live * factor, 2)}))
