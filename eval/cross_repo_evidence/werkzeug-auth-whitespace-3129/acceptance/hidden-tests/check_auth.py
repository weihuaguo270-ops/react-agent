import sys
sys.path.insert(0, sys.argv[1])
import werkzeug
from werkzeug.datastructures import WWWAuthenticate
print("imported", werkzeug.__file__, flush=True)
for scheme in ("bearer", "basic", "digest"):
    value = WWWAuthenticate(scheme).to_header()
    print(scheme, repr(value), flush=True)
    assert value == scheme.title(), (scheme, value)
assert WWWAuthenticate("bearer", token="abc123").to_header() == "Bearer abc123"
assert WWWAuthenticate("basic", {"realm": "private"}).to_header() == 'Basic realm=private'
print("acceptance passed", flush=True)
