"""
Rightmove __PAGE_MODEL__ resolver.
 
Rightmove uses a flyweight/deduplication pattern in the detail page JSON.
Instead of nesting values normally, every unique value is stored once in
a flat array, and objects reference positions in that array by integer index.
 
Real example from the page:
  arr[0]  = {"propertyData": 1, "metadata": 314, ...}  ← top-level schema
  arr[1]  = {"id": 2, "prices": 18, "address": 22, ...} ← propertyData schema
  arr[18] = {"primaryPrice": 19, ...}                    ← prices schema
  arr[19] = "£46,000,000"                                ← the actual string
 
So arr[1]["prices"] is NOT the price — it is 18, a reference to arr[18].
I must resolve it before reading any field.
 
──────────────────────────────────────────────────────────────────────────────
THE BUG I HIT AND FIXED
──────────────────────────────────────────────────────────────────────────────
In Python, bool is a subclass of int. This means:
 
    isinstance(True, int)  →  True   ← the trap
    isinstance(False, int) →  True   ← same
 
Rightmove stores boolean values like "published: True" in the flat array.
When the resolver encountered True, it saw isinstance(True, int) == True,
treated it as an index reference, and followed arr[1] — which is the entire
propertyData schema. It then recursively resolved every field, every image,
every description in the listing. Five concurrent workers each doing this
meant the scraper appeared stuck for minutes after receiving responses.
 
The depth=30 guard eventually stopped it, but only after a huge amount of
recursive work. The scraper wasn't infinite — it was just doing the work of
resolving the entire property tree 5 times per listing per boolean field.
 
Fix: check isinstance(value, bool) BEFORE isinstance(value, int).
Since bool is a subclass of int, the bool check must come first.
Booleans pass through as literals, which is what the schema intends.
 
Mental model: True is 1 in Python. Without the bool guard,
resolve(arr, True) silently became resolve(arr, arr[1]).
"""

import json
from typing import Any, List


def resolve(arr: List[Any], value: Any, depth: int = 0) -> Any:
    """
    Resolve a single value against the flat array.
 
    Rules:
    - bool   → return as-is (MUST be checked before int — bool subclasses int)
    - int in valid range → it's an index reference, follow it recursively
    - list   → resolve each element
    - dict   → resolve each value (keys are always literal strings)
    - str, None, float → return as-is
    """
    if depth > 30:
        return value

    if isinstance(value, bool):
        return value

    if isinstance(value, int) and 0 <= value < len(arr):
        return resolve(arr, arr[value], depth + 1)

    if isinstance(value, float) and value.is_integer():
        idx = int(value)
        if 0 <= idx < len(arr):
            return resolve(arr, arr[idx], depth + 1)

    if isinstance(value, list):
        return [resolve(arr, item, depth + 1) for item in value]

    if isinstance(value, dict):
        return {k: resolve(arr, v, depth + 1) for k, v in value.items()}

    return value


def parse_page_model(page_model: dict) -> dict:
    """
    Parse the raw __PAGE_MODEL__ dict and return a context object with
    helper functions for field access.
 
    Usage:
        ctx = parse_page_model(page_model)
        price_schema = ctx['get_schema']('prices')   # unresolved sub-schema
        price_str    = ctx['resolve'](price_schema['primaryPrice'])
        listing_id   = ctx['get']('id')              # fully resolved
    """
    arr = json.loads(page_model['data'])

    top_schema = arr[0]

    prop_data_index = top_schema['propertyData']
    schema = arr[prop_data_index]

    def get(field: str) -> Any:
        return resolve(arr, schema.get(field))

    def get_schema(field: str) -> dict:
        ref = schema.get(field)
        if not isinstance(ref, int) or ref >= len(arr):
            return {}
        obj = arr[ref]
        return obj if isinstance(obj, dict) else {}

    return {
        'arr': arr,
        'schema': schema,
        'get': get,
        'get_schema': get_schema,
        'resolve': lambda value: resolve(arr, value),
    }
