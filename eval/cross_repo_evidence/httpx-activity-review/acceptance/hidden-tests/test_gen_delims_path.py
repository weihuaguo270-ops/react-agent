import httpx

def test_square_brackets_are_allowed_in_path():
    assert httpx.URL('http://example.com/a[b]').raw_path == b'/a[b]'
