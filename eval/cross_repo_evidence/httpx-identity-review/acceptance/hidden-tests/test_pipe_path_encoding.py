import httpx

def test_pipe_is_percent_encoded_in_path():
    assert httpx.URL('http://example.com/a|b').raw_path == b'/a%7Cb'
