import json
from pathlib import Path
from sample import summarize
assert summarize([]) == {"count": 0, "total": 0}
assert summarize([1, 2, 3]) == {"count": 3, "total": 6}
assert summarize([-2, 5]) == {"count": 2, "total": 3}
