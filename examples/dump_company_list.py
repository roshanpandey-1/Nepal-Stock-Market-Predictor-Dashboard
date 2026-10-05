from nepse import Nepse
import csv

c = Nepse()
c.setTLSVerification(False)
companies = c.getCompanyList()

print(f"Total entries: {len(companies)}")

instrument_types = {}
for comp in companies:
    t = comp.get("instrumentType", "Unknown")
    instrument_types[t] = instrument_types.get(t, 0) + 1
print("By instrumentType:", instrument_types)

statuses = {}
for comp in companies:
    s = comp.get("status", "Unknown")
    statuses[s] = statuses.get(s, 0) + 1
print("By status:", statuses)

equity = [c2 for c2 in companies if c2.get("instrumentType") == "Equity"]
print(f"\nEquity instruments: {len(equity)}")
active_equity = [c2 for c2 in equity if c2.get("status") == "A"]
print(f"Active equity instruments: {len(active_equity)}")

with open("data/processed/nepse_live_company_list.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["symbol", "companyName", "sectorName", "status", "instrumentType"])
    for comp in active_equity:
        writer.writerow([
            comp.get("symbol"), comp.get("companyName"),
            comp.get("sectorName"), comp.get("status"), comp.get("instrumentType")
        ])
print("\nWrote data/processed/nepse_live_company_list.csv")
