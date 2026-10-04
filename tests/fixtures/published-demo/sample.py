"""Demonstration data: summarize a list of integers."""
import json

def summarize(values):
    return {"count": len(values), "total": sum(values)}

if __name__ == "__main__":
    print(json.dumps(summarize([1, 2, 3]), sort_keys=True))
