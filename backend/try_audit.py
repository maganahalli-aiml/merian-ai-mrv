"""Run one audit and print the verdicts and the memo (run from backend/):  uv run python try_audit.py approved|hold|rejected"""
import sys
import time

from agent.agents import ProcurementSupervisor

REQUESTS = {
    "approved": """
    Purchase Request - Aldermoor Industries Global Procurement:
    - Vendor: Mitsubishi Electric (Japan)
    - Item: 20 spare servo motors for the Aldermoor filling line
    - Total Cost: 38,000 EUR
    - Origin: JP (Japan)
    - Destination: DE (Aldermoor Industries, Hamburg, Germany)
    - FX Rate quoted: 1 EUR = 176.5 JPY
    """,
    "hold": """
    Purchase Request - Aldermoor Industries Global Procurement:
    - Vendor: Takumi Controls Europe B.V. (Netherlands)
    - Item: Industrial PLC Controllers + HMI Panels (Qty: 200) for the Aldermoor filling line
    - Total Cost: 480,000 EUR
    - Origin: JP (Japan)
    - Destination: DE (Aldermoor Industries, Hamburg, Germany)
    - FX Rate quoted: 1 EUR = 163.5 JPY
    """,
    "rejected": """
    Purchase Request - Aldermoor Industries Global Procurement:
    - Vendor: JSC Rosoboronexport (Russia)
    - Item: Precision steel components (Qty: 40 tonnes)
    - Total Cost: 150,000 EUR
    - Origin: RU (Russia)
    - Destination: DE (Aldermoor Industries, Hamburg, Germany)
    - FX Rate quoted: not applicable, invoiced in EUR
    """,
}

scenario = sys.argv[1] if len(sys.argv) > 1 else "hold"
started = time.time()
audit = ProcurementSupervisor().run_audit(REQUESTS[scenario])

print(f"\n=== {scenario}: audit finished in {time.time() - started:.0f} s")
for name in ("risk_result", "tax_result", "control_result"):
    verdicts = [line.strip() for line in audit[name].splitlines() if "VERDICT" in line]
    print(f"{name:15}", verdicts[0] if verdicts else "(no verdict line)")
print("\n" + audit["cfo_memo"])
