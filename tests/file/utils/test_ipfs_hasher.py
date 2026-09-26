def test_ipfs_hasher_empty_file():
    import cid
    from dorsal.file.utils.ipfs_hasher import IPFSHasher

    # 1. Generate expected CIDv1 from known CIDv0
    known_cidv0 = "QmbFMke1KXqnYyBBWxB74N4c5SBnJMVAiMNRcGu6x1AwQH"
    expected = cid.make_cid(known_cidv0).to_v1().encode().decode()

    # 2. Run our hasher on an empty byte string
    hasher = IPFSHasher()
    hasher.update(b"")
    result = hasher.hexdigest()

    # 3. Assert they match
    assert result == expected
