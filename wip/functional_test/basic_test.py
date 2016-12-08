def test_basic_request(session, url):
    resp = session.get(url('/'))
    assert resp.status_code == 200
