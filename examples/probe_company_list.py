from nepse import Nepse
import json

c = Nepse()
c.setTLSVerification(False)

candidates = [m for m in dir(c) if not m.startswith('_')]
print("ALL METHODS:")
print(candidates)
print()

for name in ["getCompanyList", "getCompanyListInfo", "getSectorScrips", "getCompanyDetails",
             "getCompany", "getListedCompanies", "getSecurityList", "getFloorsheet",
             "getSectorWiseSummary", "getSecurityDetails"]:
    if hasattr(c, name):
        try:
            result = getattr(c, name)()
            print(f"--- {name}() ---")
            if isinstance(result, list):
                print("length:", len(result))
                print("sample:", json.dumps(result[0], default=str, indent=2) if result else None)
            elif isinstance(result, dict):
                print("keys:", list(result.keys())[:10])
                first_key = next(iter(result), None)
                print("sample value:", json.dumps(result[first_key], default=str, indent=2) if first_key else None)
            else:
                print(type(result), str(result)[:300])
        except Exception as e:
            print(f"--- {name}() FAILED: {e} ---")
        print()
